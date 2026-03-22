from datetime import date, datetime
from decimal import Decimal
import unicodedata

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.control import bp
from project_manager.extensions import db
from project_manager.models import (
    Project,
    ProjectBaseline,
    ProjectHealthSnapshot,
    SystemCatalogOptionConfig,
    Task,
    TaskWorklog,
    TimesheetHeader,
    TimesheetLine,
    TimesheetPeriod,
)
from project_manager.services.control_service import (
    approve_timesheet,
    create_project_baseline,
    reject_timesheet,
    snapshot_project_health,
    timesheet_capacity_summary,
)
from project_manager.services.task_business_rules import is_closed_status, recalculate_parent_task
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
    return values or ["Pendiente", "En progreso", "Completada"]


def _in_progress_status_default(options: list[str], fallback: str | None = None) -> str:
    hints = ("progreso", "progress", "doing", "curso", "iniciado", "started")
    return _pick_status_by_hints(options, hints) or fallback or "En progreso"


def _completed_status_default(options: list[str], fallback: str | None = None) -> str:
    hints = ("complet", "cerrad", "closed", "done", "finaliz", "terminad")
    explicit_closed = next((option for option in options if is_closed_status(option)), None)
    return explicit_closed or _pick_status_by_hints(options, hints) or fallback or "Completada"


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
def _authorize_control():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    if not (
        has_permission(g.user, "control.view")
        or has_permission(g.user, "control.baseline.manage")
        or has_permission(g.user, "control.timesheets.approve")
    ):
        flash("No tienes permisos para acceder a Control.", "danger")
        return redirect(url_for("main.home"))


def _projects_scope_stmt():
    stmt = select(Project).where(Project.is_active.is_(True)).order_by(Project.name.asc())
    scope = allowed_project_ids(g.user)
    if scope is not None:
        if not scope:
            return stmt.where(Project.id == -1)
        stmt = stmt.where(Project.id.in_(scope))
    return stmt


@bp.route("/")
@login_required
def dashboard():
    projects = db.session.execute(_projects_scope_stmt()).scalars().all()
    health_rows = db.session.execute(
        select(ProjectHealthSnapshot)
        .order_by(ProjectHealthSnapshot.snapshot_date.desc(), ProjectHealthSnapshot.id.desc())
    ).scalars().all()
    latest_by_project: dict[int, ProjectHealthSnapshot] = {}
    for row in health_rows:
        if row.project_id not in latest_by_project:
            latest_by_project[row.project_id] = row
    return render_template("control/dashboard.html", projects=projects, latest_by_project=latest_by_project)


@bp.route("/projects/<int:project_id>/baselines", methods=["GET", "POST"])
@login_required
def project_baselines(project_id: int):
    project = db.session.get(Project, project_id)
    if not project:
        return redirect(url_for("control.dashboard"))
    scope = allowed_project_ids(g.user)
    if scope is not None and project_id not in scope:
        flash("No tienes alcance sobre ese proyecto.", "danger")
        return redirect(url_for("control.dashboard"))

    if request.method == "POST":
        if not has_permission(g.user, "control.baseline.manage"):
            flash("No tienes permisos para crear baseline.", "danger")
            return redirect(url_for("control.project_baselines", project_id=project_id))
        action = _safe_strip(request.form.get("action")) or "create_baseline"
        if action == "snapshot":
            baseline = db.session.execute(
                select(ProjectBaseline)
                .where(ProjectBaseline.project_id == project_id)
                .order_by(ProjectBaseline.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            snapshot_project_health(project, baseline)
            db.session.commit()
            flash("Snapshot de salud actualizado.", "success")
            return redirect(url_for("control.project_baselines", project_id=project_id))
        label = _safe_strip(request.form.get("label"))
        notes = _safe_strip(request.form.get("notes"))
        baseline = create_project_baseline(project, created_by_user_id=g.user.id if g.get("user") else None, label=label, notes=notes)
        snapshot_project_health(project, baseline)
        db.session.commit()
        flash(f"Baseline v{baseline.version} creada.", "success")
        return redirect(url_for("control.project_baselines", project_id=project_id))

    baselines = db.session.execute(
        select(ProjectBaseline)
        .where(ProjectBaseline.project_id == project_id)
        .order_by(ProjectBaseline.version.desc())
    ).scalars().all()
    health_rows = db.session.execute(
        select(ProjectHealthSnapshot)
        .where(ProjectHealthSnapshot.project_id == project_id)
        .order_by(ProjectHealthSnapshot.snapshot_date.desc(), ProjectHealthSnapshot.id.desc())
        .limit(30)
    ).scalars().all()
    return render_template(
        "control/project_baselines.html",
        project=project,
        baselines=baselines,
        health_rows=health_rows,
    )


@bp.route("/timesheets", methods=["GET", "POST"])
@login_required
def timesheets():
    if not has_permission(g.user, "control.timesheets.approve"):
        flash("No tienes permisos para aprobar timesheets.", "danger")
        return redirect(url_for("control.dashboard"))

    status = _safe_strip(request.args.get("status")) or "submitted"
    stmt = select(TimesheetHeader).order_by(TimesheetHeader.week_start.desc(), TimesheetHeader.id.desc())
    if status:
        stmt = stmt.where(TimesheetHeader.status == status)
    rows = db.session.execute(stmt).scalars().all()
    rows_with_summary = [
        {"header": row, "summary": timesheet_capacity_summary(row, owner_user_id=g.user.id if g.get("user") else None)}
        for row in rows
    ]
    return render_template("control/timesheets.html", rows=rows_with_summary, status=status)


@bp.route("/timesheets/<int:header_id>", methods=["GET", "POST"])
@login_required
def review_timesheet(header_id: int):
    if not has_permission(g.user, "control.timesheets.approve"):
        flash("No tienes permisos para aprobar timesheets.", "danger")
        return redirect(url_for("control.dashboard"))

    header = db.session.execute(
        select(TimesheetHeader)
        .where(TimesheetHeader.id == header_id)
        .options(selectinload(TimesheetHeader.resource), selectinload(TimesheetHeader.user), selectinload(TimesheetHeader.period))
    ).scalar_one_or_none()
    if not header:
        flash("Timesheet inválido.", "danger")
        return redirect(url_for("control.timesheets"))

    if request.method == "POST":
        action = _safe_strip(request.form.get("action"))
        if action == "update_line":
            line_id = _to_int(request.form.get("line_id"))
            line = db.session.execute(
                select(TimesheetLine).where(TimesheetLine.id == line_id, TimesheetLine.header_id == header.id)
            ).scalar_one_or_none()
            if not line:
                flash("Línea de timesheet inválida.", "danger")
                return redirect(url_for("control.review_timesheet", header_id=header.id))

            hours = _to_decimal(request.form.get("hours"))
            progress = _to_int(request.form.get("progress_percent_after"))
            note = _safe_strip(request.form.get("note"))
            errors: list[str] = []
            if hours is None or hours <= 0:
                errors.append("Las horas deben ser mayores a 0.")
            elif hours > Decimal("24"):
                errors.append("Las horas por registro no pueden superar 24.")
            if progress is not None and not 0 <= progress <= 100:
                errors.append("El avance debe estar entre 0 y 100.")
            if header.status == "approved":
                errors.append("No se puede editar un timesheet aprobado.")
            if header.period and header.period.is_closed:
                errors.append("No se puede editar: el período está cerrado.")
            if errors:
                for error in errors:
                    flash(error, "danger")
                return redirect(url_for("control.review_timesheet", header_id=header.id))

            line.hours = hours
            line.progress_percent_after = progress
            line.note = note or None
            if line.worklog:
                line.worklog.hours = hours
                line.worklog.progress_percent_after = progress
                line.worklog.note = note or None
                task = db.session.get(Task, line.worklog.task_id)
                if task:
                    _sync_task_from_worklogs(task)
                    if task.parent_task_id:
                        recalculate_parent_task(task.parent_task_id, reason="worklog_update", trigger_task_id=task.id)
            db.session.commit()
            summary = timesheet_capacity_summary(header, owner_user_id=g.user.id if g.get("user") else None)
            if summary["overage_hours"] > 0:
                flash(
                    f"Este timesheet quedó con {summary['overage_hours']} hs extra sobre capacidad semanal.",
                    "warning",
                )
            flash("Línea actualizada.", "success")
            return redirect(url_for("control.review_timesheet", header_id=header.id))

        if action == "approve":
            approve_timesheet(header, approver_user_id=g.user.id)
            db.session.commit()
            flash("Timesheet aprobado.", "success")
            return redirect(url_for("control.timesheets", status="submitted"))

        if action == "reject":
            comment = _safe_strip(request.form.get("comment"))
            if len(comment) < 3:
                flash("Debes informar motivo de rechazo.", "danger")
                return redirect(url_for("control.review_timesheet", header_id=header.id))
            reject_timesheet(header, approver_user_id=g.user.id, comment=comment)
            db.session.commit()
            flash("Timesheet rechazado.", "warning")
            return redirect(url_for("control.timesheets", status="submitted"))

    lines = db.session.execute(
        select(TimesheetLine)
        .where(TimesheetLine.header_id == header.id)
        .options(selectinload(TimesheetLine.task).selectinload(Task.project))
        .order_by(TimesheetLine.work_date.asc(), TimesheetLine.id.asc())
    ).scalars().all()
    total_hours = sum((Decimal(item.hours or 0) for item in lines), Decimal("0.00"))
    summary = timesheet_capacity_summary(header, owner_user_id=g.user.id if g.get("user") else None)
    return render_template("control/timesheet_review.html", header=header, lines=lines, total_hours=total_hours, summary=summary)


@bp.route("/periods", methods=["GET", "POST"])
@login_required
def periods():
    if not has_permission(g.user, "control.periods.manage"):
        flash("No tienes permisos para gestionar períodos.", "danger")
        return redirect(url_for("control.dashboard"))

    if request.method == "POST":
        action = _safe_strip(request.form.get("action"))
        if action == "create":
            start_date = parse_date_input(request.form.get("start_date"))
            end_date = parse_date_input(request.form.get("end_date"))
            if not start_date or not end_date:
                flash("Debes informar fechas válidas.", "danger")
                return redirect(url_for("control.periods"))
            if end_date < start_date:
                flash("Rango de período inválido.", "danger")
                return redirect(url_for("control.periods"))
            overlap = db.session.execute(
                select(TimesheetPeriod.id).where(
                    TimesheetPeriod.start_date <= end_date,
                    TimesheetPeriod.end_date >= start_date,
                ).limit(1)
            ).scalar_one_or_none()
            if overlap:
                flash("Ya existe un período que se superpone.", "danger")
                return redirect(url_for("control.periods"))
            db.session.add(TimesheetPeriod(start_date=start_date, end_date=end_date, is_closed=False))
            db.session.commit()
            flash("Período creado.", "success")
            return redirect(url_for("control.periods"))

        if action in {"close", "open"}:
            period_id = _to_int(request.form.get("period_id"))
            period = db.session.get(TimesheetPeriod, period_id) if period_id else None
            if not period:
                flash("Período inválido.", "danger")
                return redirect(url_for("control.periods"))
            period.is_closed = action == "close"
            period.closed_by_user_id = g.user.id if action == "close" else None
            period.closed_at = datetime.utcnow() if action == "close" else None
            db.session.commit()
            flash("Período actualizado.", "success")
            return redirect(url_for("control.periods"))

    rows = db.session.execute(select(TimesheetPeriod).order_by(TimesheetPeriod.start_date.desc())).scalars().all()
    return render_template("control/periods.html", rows=rows)
