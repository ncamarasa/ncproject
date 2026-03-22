from datetime import date, timedelta
from decimal import Decimal
import math
import unicodedata

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.work import bp
from project_manager.extensions import db
from project_manager.models import (
    Project,
    Resource,
    SystemCatalogOptionConfig,
    Task,
    TaskResource,
    TaskWorklog,
    TimesheetHeader,
    TimesheetLine,
    User,
)
from project_manager.services.control_service import (
    can_edit_timesheet_header,
    ensure_timesheet_header,
    is_day_in_closed_period,
    submit_timesheet,
    week_bounds,
)
from project_manager.services.task_business_rules import is_closed_status, recalculate_parent_task
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import calculate_resource_net_availability
from project_manager.utils.dates import parse_date_input
from project_manager.utils.numbers import parse_decimal_input


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_decimal(value: str | None):
    return parse_decimal_input(value)


def _to_bool(value: str | None) -> bool:
    return _safe_strip(value).lower() in {"1", "true", "on", "yes", "si", "sí"}


def _priority_filter_key(value: str | None) -> str:
    key = _normalize_text(value)
    if key in {"critica", "alta", "media", "baja"}:
        return key
    return ""


def _priority_filter_match(priority_label: str | None, filter_key: str) -> bool:
    if not filter_key:
        return True
    return _normalize_text(priority_label) == filter_key


def _normalize_text(value: str | None) -> str:
    raw = _safe_strip(value).lower()
    normalized = unicodedata.normalize("NFD", raw)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _status_matches(value: str | None, hints: tuple[str, ...]) -> bool:
    normalized = _normalize_text(value)
    return any(hint in normalized for hint in hints)


def _pick_status_by_hints(options: list[str], hints: tuple[str, ...]) -> str | None:
    for option in options:
        if _status_matches(option, hints):
            return option
    return None


def _task_status_options(owner_user_id: int | None) -> list[str]:
    if not owner_user_id:
        return ["Pendiente", "En progreso", "Completada"]
    values = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == owner_user_id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_statuses",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    if values:
        return values
    seed_default_catalogs_for_user(owner_user_id)
    db.session.flush()
    values = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == owner_user_id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_statuses",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    return values or ["Pendiente", "En progreso", "Completada"]


def _in_progress_status_default(options: list[str], fallback: str | None = None) -> str:
    hints = ("progreso", "progress", "doing", "curso", "iniciado", "started")
    return _pick_status_by_hints(options, hints) or fallback or "En progreso"


def _completed_status_default(options: list[str], fallback: str | None = None) -> str:
    hints = ("complet", "cerrad", "closed", "done", "finaliz", "terminad")
    explicit_closed = next((option for option in options if is_closed_status(option)), None)
    return explicit_closed or _pick_status_by_hints(options, hints) or fallback or "Completada"


def _is_admin_like(user: User | None) -> bool:
    if not user:
        return False
    return user.username == "admin" or has_permission(user, "users.manage")


def _resource_for_user(user: User | None) -> Resource | None:
    if not user:
        return None
    email = _safe_strip(user.email).lower()
    if not email:
        return None
    return db.session.execute(
        select(Resource).where(Resource.is_active.is_(True), Resource.email.ilike(email))
    ).scalar_one_or_none()


def _assigned_tasks_stmt(resource_id: int, user: User):
    scope = allowed_project_ids(user)
    task_resource_exists = exists(
        select(TaskResource.id).where(
            TaskResource.task_id == Task.id,
            TaskResource.resource_id == resource_id,
            TaskResource.is_active.is_(True),
        )
    )
    stmt = (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .where(
            Task.is_active.is_(True),
            Project.is_active.is_(True),
            or_(Task.responsible_resource_id == resource_id, task_resource_exists),
        )
        .options(selectinload(Task.project))
        .order_by(Task.due_date.asc().nullslast(), Task.start_date.asc().nullslast(), Task.id.asc())
    )
    if scope is not None:
        if not scope:
            return stmt.where(Task.id == -1)
        stmt = stmt.where(Task.project_id.in_(scope))
    return stmt


def _resource_is_assigned_task(task: Task, resource_id: int) -> bool:
    if task.responsible_resource_id == resource_id:
        return True
    exists_row = db.session.execute(
        select(TaskResource.id).where(
            TaskResource.task_id == task.id,
            TaskResource.resource_id == resource_id,
            TaskResource.is_active.is_(True),
        )
    ).scalar_one_or_none()
    return exists_row is not None


def _count_business_days(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0
    total = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            total += 1
        cursor += timedelta(days=1)
    return total


def _resource_week_capacity(resource_id: int, day: date, *, owner_user_id: int | None = None) -> dict:
    week_start, week_end = week_bounds(day)
    payload = calculate_resource_net_availability(
        resource_id,
        week_start,
        week_end,
        owner_user_id=owner_user_id,
    )
    total_base = Decimal(str(payload.get("totals", {}).get("base_hours", 0) or 0))
    total_exception = Decimal(str(payload.get("totals", {}).get("exception_hours", 0) or 0))
    capacity_hours = max(Decimal("0.00"), total_base - total_exception)

    effective_day_hours = [
        max(Decimal("0.00"), Decimal(str(row.get("base_hours", 0) or 0)) - Decimal(str(row.get("exception_hours", 0) or 0)))
        for row in payload.get("days", [])
        if Decimal(str(row.get("base_hours", 0) or 0)) > 0
    ]
    avg_daily_capacity = (
        (sum(effective_day_hours, Decimal("0.00")) / Decimal(len(effective_day_hours)))
        if effective_day_hours
        else Decimal("0.00")
    )
    return {
        "week_start": week_start,
        "week_end": week_end,
        "capacity_hours": capacity_hours,
        "avg_daily_capacity": avg_daily_capacity,
    }


def _resource_logged_week_hours(resource_id: int, week_start: date, week_end: date, *, exclude_log_id: int | None = None) -> Decimal:
    stmt = select(func.coalesce(func.sum(TaskWorklog.hours), 0)).where(
        TaskWorklog.resource_id == resource_id,
        TaskWorklog.is_active.is_(True),
        TaskWorklog.work_date >= week_start,
        TaskWorklog.work_date <= week_end,
    )
    if exclude_log_id:
        stmt = stmt.where(TaskWorklog.id != exclude_log_id)
    value = db.session.execute(stmt).scalar_one()
    return Decimal(value or 0)


def _task_priority_meta(task: Task, reference_day: date, avg_daily_capacity: Decimal) -> dict:
    estimated = Decimal(task.estimated_hours or 0)
    logged = Decimal(task.logged_hours or 0)
    pending_hours = max(Decimal("0.00"), estimated - logged) if estimated > 0 else None

    due_date = task.due_date
    days_to_due = (due_date - reference_day).days if due_date else None
    business_days_to_due = _count_business_days(reference_day, due_date) if due_date and due_date >= reference_day else 0
    required_days = None
    if pending_hours is not None and pending_hours > 0 and avg_daily_capacity > 0:
        required_days = int(math.ceil(float(pending_hours / avg_daily_capacity)))
    slack_days = None if required_days is None or days_to_due is None else days_to_due - required_days

    risk_rank = 4
    priority_label = "Sin fecha"
    if due_date:
        if days_to_due < 0 or (slack_days is not None and slack_days < 0):
            risk_rank = 0
            priority_label = "Crítica"
        elif days_to_due <= 2 or (slack_days is not None and slack_days < 1):
            risk_rank = 1
            priority_label = "Alta"
        elif days_to_due <= 5 or (slack_days is not None and slack_days < 3):
            risk_rank = 2
            priority_label = "Media"
        else:
            risk_rank = 3
            priority_label = "Baja"

    return {
        "pending_hours": float(pending_hours) if pending_hours is not None else None,
        "days_to_due": days_to_due,
        "business_days_to_due": business_days_to_due if due_date else None,
        "required_days": required_days,
        "slack_days": slack_days,
        "priority_label": priority_label,
        "risk_rank": risk_rank,
        "sort_key": (
            risk_rank,
            due_date or date.max,
            float(pending_hours) if pending_hours is not None else 0.0,
            task.id,
        ),
    }


def _sync_task_from_worklogs(task: Task) -> None:
    logs = db.session.execute(
        select(TaskWorklog)
        .where(TaskWorklog.task_id == task.id, TaskWorklog.is_active.is_(True))
        .order_by(TaskWorklog.work_date.asc(), TaskWorklog.id.asc())
    ).scalars().all()
    if not logs:
        task.logged_hours = Decimal("0.00")
        task.actual_start_date = None
        task.actual_end_date = None
        return

    total_hours = sum((Decimal(log.hours or 0) for log in logs), Decimal("0.00"))
    task.logged_hours = total_hours
    task.actual_start_date = logs[0].work_date

    # Avance automático: horas imputadas / horas estimadas (capado en 100%).
    auto_progress = None
    estimated_hours = Decimal(task.estimated_hours or 0)
    if estimated_hours > 0:
        auto_progress = int(round(float((total_hours / estimated_hours) * Decimal("100"))))
        auto_progress = max(0, min(auto_progress, 100))
    if auto_progress is not None:
        task.progress_percent = auto_progress

    status_options = _task_status_options(g.user.id if g.get("user") else None)
    current_status = task.status or ""
    if int(task.progress_percent or 0) >= 100:
        task.status = _completed_status_default(status_options, fallback=current_status)
    elif int(task.progress_percent or 0) > 0 and not is_closed_status(current_status):
        task.status = _in_progress_status_default(status_options, fallback=current_status)

    task.actual_end_date = logs[-1].work_date if int(task.progress_percent or 0) >= 100 else None


@bp.before_request
def _authorize_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    can_view = has_permission(g.user, "work.view") or has_permission(g.user, "tasks.view")
    can_write = (
        has_permission(g.user, "work.log_hours")
        or has_permission(g.user, "tasks.edit")
        or has_permission(g.user, "tasks.worklog.manage")
    )
    if not can_view:
        flash("No tienes permisos para acceder a Mi Trabajo.", "danger")
        return redirect(url_for("main.home"))
    if is_write and not can_write:
        flash("No tienes permisos para registrar trabajo.", "danger")
        return redirect(url_for("work.my_tasks"))


@bp.route("/tasks", methods=["GET", "POST"])
@login_required
def my_tasks():
    is_admin = _is_admin_like(g.user)
    selected_user_id = _to_int(request.values.get("user_id")) if is_admin else g.user.id
    if not selected_user_id:
        selected_user_id = g.user.id

    users = []
    if is_admin:
        users = db.session.execute(
            select(User).where(User.is_active.is_(True)).order_by(User.username.asc())
        ).scalars().all()

    selected_user = db.session.get(User, selected_user_id) if selected_user_id else g.user
    if not selected_user or (not is_admin and selected_user.id != g.user.id):
        selected_user = g.user

    selected_resource = _resource_for_user(selected_user)
    task_rows = []
    recent_logs = []
    default_work_date = date.today()
    selected_priority_filter = _priority_filter_key(request.args.get("priority"))
    hide_no_due = _to_bool(request.args.get("hide_no_due"))
    edit_log_id = _to_int(request.values.get("edit_log_id"))
    edit_log = None

    if request.method == "POST":
        if g.user.read_only:
            flash("Tu usuario es de solo lectura.", "danger")
            return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))

        action = _safe_strip(request.form.get("action")) or "log"
        if action == "submit_week":
            submit_date = parse_date_input(request.form.get("work_date")) or default_work_date
            if not selected_resource:
                flash("El usuario seleccionado no está vinculado a un recurso activo (por email).", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))
            week_start, _ = week_bounds(submit_date)
            header = db.session.execute(
                select(TimesheetHeader).where(
                    TimesheetHeader.resource_id == selected_resource.id,
                    TimesheetHeader.week_start == week_start,
                )
            ).scalar_one_or_none()
            if not header:
                flash("No hay horas cargadas para esa semana.", "warning")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=submit_date.isoformat()))
            if header.status == "approved":
                flash("La semana ya está aprobada. No se puede reenviar.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=submit_date.isoformat()))
            if header.status == "submitted":
                flash("La semana ya fue enviada y está pendiente de revisión PMO.", "info")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=submit_date.isoformat()))
            submit_timesheet(header)
            db.session.commit()
            summary = _resource_week_capacity(
                selected_resource.id,
                submit_date,
                owner_user_id=g.user.id if g.get("user") else None,
            )
            logged = _resource_logged_week_hours(selected_resource.id, summary["week_start"], summary["week_end"])
            overage = max(Decimal("0.00"), logged - summary["capacity_hours"])
            if overage > 0:
                flash(f"Semana enviada con exceso de {overage} hs para validación PMO.", "warning")
            flash("Semana enviada para aprobación.", "success")
            return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=submit_date.isoformat()))

        if action in {"update_log", "delete_log"}:
            log_id = _to_int(request.form.get("log_id"))
            log = db.session.get(TaskWorklog, log_id) if log_id else None
            if not log or not log.is_active:
                flash("Registro de trabajo no válido.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))
            if not selected_resource or log.resource_id != selected_resource.id:
                flash("Solo puedes editar registros del recurso seleccionado.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))
            task = db.session.get(Task, log.task_id)
            if not task:
                flash("La tarea del registro no existe.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))
            scope = allowed_project_ids(g.user)
            if scope is not None and task.project_id not in scope:
                flash("No tienes acceso al proyecto de la tarea.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None))

            header = log.timesheet_header
            if header and not can_edit_timesheet_header(header):
                flash("No se puede editar: la semana está enviada/aprobada o el período está cerrado.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=log.work_date.isoformat()))
            if not header and is_day_in_closed_period(log.work_date):
                flash("No se puede editar: la fecha pertenece a un período cerrado.", "danger")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=log.work_date.isoformat()))

            if action == "delete_log":
                line = db.session.execute(
                    select(TimesheetLine).where(TimesheetLine.worklog_id == log.id)
                ).scalar_one_or_none()
                if line:
                    db.session.delete(line)
                log.is_active = False
                _sync_task_from_worklogs(task)
                if task.parent_task_id:
                    recalculate_parent_task(task.parent_task_id, reason="worklog_delete", trigger_task_id=task.id)
                db.session.commit()
                flash("Registro eliminado.", "info")
                return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=log.work_date.isoformat()))

            # update_log
            hours = _to_decimal(request.form.get("hours"))
            note = _safe_strip(request.form.get("note"))
            allow_overage = _to_bool(request.form.get("allow_overage"))
            errors = []
            if hours is None or hours <= 0:
                errors.append("Las horas deben ser mayores a 0.")
            elif hours > Decimal("24"):
                errors.append("Las horas por registro no pueden superar 24.")
            overage_info = None
            if not errors:
                week_ctx = _resource_week_capacity(
                    selected_resource.id,
                    log.work_date,
                    owner_user_id=g.user.id if g.get("user") else None,
                )
                already_logged = _resource_logged_week_hours(
                    selected_resource.id,
                    week_ctx["week_start"],
                    week_ctx["week_end"],
                    exclude_log_id=log.id,
                )
                projected_total = already_logged + Decimal(hours)
                overage_hours = max(Decimal("0.00"), projected_total - week_ctx["capacity_hours"])
                overage_info = {
                    "capacity": week_ctx["capacity_hours"],
                    "already_logged": already_logged,
                    "projected_total": projected_total,
                    "overage_hours": overage_hours,
                }
                if overage_hours > 0 and not allow_overage:
                    errors.append(
                        "La edición supera la disponibilidad semanal configurada. "
                        f"Disponible: {week_ctx['capacity_hours']} hs, cargadas: {already_logged} hs, "
                        f"proyectadas: {projected_total} hs, exceso: {overage_hours} hs. "
                        "Marca 'Permitir horas extra' para enviarla a revisión de PMO."
                    )
            if errors:
                for error in errors:
                    flash(error, "danger")
                return redirect(
                    url_for(
                        "work.my_tasks",
                        user_id=selected_user.id if is_admin else None,
                        work_date=log.work_date.isoformat(),
                        edit_log_id=log.id,
                    )
                )

            log.hours = hours
            log.progress_percent_after = None
            log.note = note or None
            line = db.session.execute(
                select(TimesheetLine).where(TimesheetLine.worklog_id == log.id)
            ).scalar_one_or_none()
            if line:
                line.hours = hours
                line.progress_percent_after = None
                line.note = note or None
            _sync_task_from_worklogs(task)
            if task.parent_task_id:
                recalculate_parent_task(task.parent_task_id, reason="worklog_update", trigger_task_id=task.id)
            db.session.commit()
            if overage_info and overage_info["overage_hours"] > 0:
                flash(
                    f"Registro actualizado con exceso semanal de {overage_info['overage_hours']} hs "
                    "pendiente de validación PMO.",
                    "warning",
                )
            flash("Registro actualizado.", "success")
            return redirect(url_for("work.my_tasks", user_id=selected_user.id if is_admin else None, work_date=log.work_date.isoformat()))

        task_id = _to_int(request.form.get("task_id"))
        work_date = parse_date_input(request.form.get("work_date"))
        hours = _to_decimal(request.form.get("hours"))
        note = _safe_strip(request.form.get("note"))
        allow_overage = _to_bool(request.form.get("allow_overage"))

        errors = []
        if not selected_resource:
            errors.append("El usuario seleccionado no está vinculado a un recurso activo (por email).")
        task = db.session.get(Task, task_id) if task_id else None
        if not task:
            errors.append("La tarea no es válida.")
        if not work_date:
            errors.append("Debes indicar una fecha de trabajo válida.")
        if work_date and is_day_in_closed_period(work_date):
            errors.append("La fecha pertenece a un período cerrado.")
        if hours is None or hours <= 0:
            errors.append("Las horas deben ser mayores a 0.")
        elif hours > Decimal("24"):
            errors.append("Las horas por registro no pueden superar 24.")
        if task and selected_resource and not _resource_is_assigned_task(task, selected_resource.id):
            errors.append("Solo puedes imputar sobre tareas asignadas al recurso seleccionado.")

        scope = allowed_project_ids(g.user)
        if task and scope is not None and task.project_id not in scope:
            errors.append("No tienes acceso al proyecto de la tarea seleccionada.")

        overage_info = None
        if not errors and selected_resource and work_date and hours:
            week_ctx = _resource_week_capacity(
                selected_resource.id,
                work_date,
                owner_user_id=g.user.id if g.get("user") else None,
            )
            already_logged = _resource_logged_week_hours(
                selected_resource.id,
                week_ctx["week_start"],
                week_ctx["week_end"],
            )
            projected_total = already_logged + Decimal(hours)
            overage_hours = max(Decimal("0.00"), projected_total - week_ctx["capacity_hours"])
            overage_info = {
                "capacity": week_ctx["capacity_hours"],
                "already_logged": already_logged,
                "projected_total": projected_total,
                "overage_hours": overage_hours,
            }
            if overage_hours > 0 and not allow_overage:
                errors.append(
                    "Esta carga supera la disponibilidad semanal configurada. "
                    f"Disponible: {week_ctx['capacity_hours']} hs, cargadas: {already_logged} hs, "
                    f"proyectadas: {projected_total} hs, exceso: {overage_hours} hs. "
                    "Marca 'Permitir horas extra' para enviarla a revisión de PMO."
                )

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            header = ensure_timesheet_header(selected_resource.id, g.user.id if g.get("user") else None, work_date)
            if not can_edit_timesheet_header(header):
                flash("No se puede registrar: la semana está aprobada o cerrada.", "danger")
                return redirect(
                    url_for(
                        "work.my_tasks",
                        user_id=selected_user.id if is_admin else None,
                        work_date=work_date.isoformat(),
                    )
                )
            worklog = TaskWorklog(
                task_id=task.id,
                resource_id=selected_resource.id,
                user_id=g.user.id,
                timesheet_header_id=header.id,
                work_date=work_date,
                hours=hours,
                progress_percent_after=None,
                note=note or None,
            )
            db.session.add(worklog)
            db.session.flush()
            db.session.add(
                TimesheetLine(
                    header_id=header.id,
                    task_id=task.id,
                    worklog_id=worklog.id,
                    work_date=work_date,
                    hours=hours,
                    note=note or None,
                    progress_percent_after=None,
                )
            )
            _sync_task_from_worklogs(task)
            db.session.flush()
            if task.parent_task_id:
                recalculate_parent_task(task.parent_task_id, reason="worklog_update", trigger_task_id=task.id)
            db.session.commit()
            if overage_info and overage_info["overage_hours"] > 0:
                flash(
                    f"Registro guardado con exceso semanal de {overage_info['overage_hours']} hs "
                    "pendiente de validación PMO.",
                    "warning",
                )
            flash("Registro de trabajo guardado.", "success")
            return redirect(
                url_for(
                    "work.my_tasks",
                    user_id=selected_user.id if is_admin else None,
                    work_date=work_date.isoformat(),
                )
            )

    requested_date = parse_date_input(request.args.get("work_date"))
    if requested_date:
        default_work_date = requested_date

    week_status = None
    week_start, week_end = week_bounds(default_work_date)
    week_capacity = None
    week_logged = Decimal("0.00")
    week_remaining = Decimal("0.00")
    week_overage = Decimal("0.00")
    task_meta_by_id: dict[int, dict] = {}
    priority_counts = {
        "critica": 0,
        "alta": 0,
        "media": 0,
        "baja": 0,
        "sin_fecha": 0,
        "total": 0,
    }
    if selected_resource:
        task_rows = db.session.execute(_assigned_tasks_stmt(selected_resource.id, g.user)).scalars().all()
        week_capacity = _resource_week_capacity(
            selected_resource.id,
            default_work_date,
            owner_user_id=g.user.id if g.get("user") else None,
        )
        week_start = week_capacity["week_start"]
        week_end = week_capacity["week_end"]
        week_logged = _resource_logged_week_hours(selected_resource.id, week_start, week_end)
        week_remaining = max(Decimal("0.00"), week_capacity["capacity_hours"] - week_logged)
        week_overage = max(Decimal("0.00"), week_logged - week_capacity["capacity_hours"])
        for task in task_rows:
            task_meta_by_id[task.id] = _task_priority_meta(task, default_work_date, week_capacity["avg_daily_capacity"])
            label = _normalize_text(task_meta_by_id[task.id].get("priority_label"))
            if label == "critica":
                priority_counts["critica"] += 1
            elif label == "alta":
                priority_counts["alta"] += 1
            elif label == "media":
                priority_counts["media"] += 1
            elif label == "baja":
                priority_counts["baja"] += 1
            else:
                priority_counts["sin_fecha"] += 1
            priority_counts["total"] += 1
        task_rows = sorted(task_rows, key=lambda item: task_meta_by_id[item.id]["sort_key"])
        if selected_priority_filter:
            task_rows = [
                item
                for item in task_rows
                if _priority_filter_match(task_meta_by_id.get(item.id, {}).get("priority_label"), selected_priority_filter)
            ]
        if hide_no_due:
            task_rows = [item for item in task_rows if item.due_date is not None]
        header = db.session.execute(
            select(TimesheetHeader).where(
                TimesheetHeader.resource_id == selected_resource.id,
                TimesheetHeader.week_start == week_start,
            )
        ).scalar_one_or_none()
        week_status = header.status if header else "draft"
        recent_logs = db.session.execute(
            select(TaskWorklog)
            .join(Task, Task.id == TaskWorklog.task_id)
            .join(Project, Project.id == Task.project_id)
            .where(
                TaskWorklog.resource_id == selected_resource.id,
                TaskWorklog.is_active.is_(True),
                Task.is_active.is_(True),
                Project.is_active.is_(True),
            )
            .options(selectinload(TaskWorklog.task).selectinload(Task.project))
            .order_by(TaskWorklog.work_date.desc(), TaskWorklog.id.desc())
            .limit(25)
        ).scalars().all()
        if edit_log_id:
            edit_log = db.session.execute(
                select(TaskWorklog)
                .join(Task, Task.id == TaskWorklog.task_id)
                .join(Project, Project.id == Task.project_id)
                .where(
                    TaskWorklog.id == edit_log_id,
                    TaskWorklog.resource_id == selected_resource.id,
                    TaskWorklog.is_active.is_(True),
                    Task.is_active.is_(True),
                    Project.is_active.is_(True),
                )
                .options(selectinload(TaskWorklog.task).selectinload(Task.project))
            ).scalar_one_or_none()

    return render_template(
        "work/my_tasks.html",
        is_admin=is_admin,
        users=users,
        selected_user=selected_user,
        selected_resource=selected_resource,
        tasks=task_rows,
        recent_logs=recent_logs,
        edit_log=edit_log,
        default_work_date=default_work_date,
        week_start=week_start,
        week_end=week_end,
        week_status=week_status,
        week_capacity=week_capacity,
        week_logged=week_logged,
        week_remaining=week_remaining,
        week_overage=week_overage,
        task_meta_by_id=task_meta_by_id,
        selected_priority_filter=selected_priority_filter,
        hide_no_due=hide_no_due,
        priority_counts=priority_counts,
    )
