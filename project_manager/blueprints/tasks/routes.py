import os
from collections import Counter
from datetime import date, timedelta
from math import ceil
import unicodedata
from urllib.parse import urlsplit
from uuid import uuid4

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.tasks import bp
from project_manager.extensions import db
from project_manager.models import (
    Project,
    ProjectResource,
    Resource,
    ResourceAvailability,
    SystemCatalogOptionConfig,
    Task,
    TaskAssignee,
    TaskAttachment,
    TaskComment,
    TaskDependency,
    TaskResource,
    TeamCalendarHolidayConfig,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.task_business_rules import (
    CLOSED_STATUSES,
    has_open_subtasks,
    is_closed_status,
    recalculate_parent_task,
    task_has_subtasks,
    validate_parent_assignment,
)
from project_manager.services.team_business_rules import (
    calculate_resource_net_availability,
    find_applicable_cost_id,
    validate_assignment,
    validate_task_assignment_project_consistency,
)
from project_manager.utils.dates import parse_date_input
from project_manager.utils.numbers import parse_decimal_input

TASK_ALLOWED_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "png",
    "jpg",
    "jpeg",
    "txt",
}
TASK_SCHEDULE_MODES = ("manual", "automatic")
DEFAULT_DEPENDENCY_TYPE = "FS"
STATUS_PENDING_HINTS = ("pend", "to do", "todo", "abiert", "nuevo", "open")
STATUS_IN_PROGRESS_HINTS = ("progreso", "progress", "doing", "curso", "iniciado", "started")
STATUS_COMPLETED_HINTS = ("complet", "cerrad", "closed", "done", "finaliz", "terminad")


@bp.before_request
def _authorize_tasks_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    endpoint = request.endpoint or ""
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))

    if is_write:
        required_by_endpoint = {
            "tasks.manage_tasks": ["tasks.create", "tasks.edit"],
            "tasks.edit_task": ["tasks.edit"],
            "tasks.delete_task": ["tasks.delete", "tasks.edit"],
            "tasks.add_dependency": ["tasks.dependencies.manage", "tasks.edit"],
            "tasks.delete_dependency": ["tasks.dependencies.manage", "tasks.edit"],
            "tasks.add_task_collaborator": ["tasks.edit"],
            "tasks.delete_task_collaborator": ["tasks.edit"],
            "tasks.update_task_status": ["tasks.status.update", "tasks.edit"],
        }
        if endpoint == "tasks.task_detail":
            if request.form.get("comment_body") is not None:
                required = ["tasks.comments.manage", "tasks.edit"]
            elif request.files.get("attachment") is not None:
                required = ["tasks.attachments.manage", "tasks.edit"]
            else:
                required = ["tasks.edit"]
        else:
            required = required_by_endpoint.get(endpoint, ["tasks.edit"])
    else:
        read_required_by_endpoint = {
            "tasks.gantt": ["tasks.gantt.view", "tasks.view"],
            "tasks.download_attachment": ["tasks.attachments.manage", "tasks.view"],
        }
        required = read_required_by_endpoint.get(endpoint, ["tasks.view"])

    if not any(has_permission(g.user, permission_key) for permission_key in required):
        flash("No tienes permisos para acceder al módulo de tareas.", "danger")
        return redirect(url_for("main.home"))


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


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


def _pending_status_default(options: list[str]) -> str:
    return _pick_status_by_hints(options, STATUS_PENDING_HINTS) or (options[0] if options else "Pendiente")


def _in_progress_status_default(options: list[str], fallback: str | None = None) -> str:
    return _pick_status_by_hints(options, STATUS_IN_PROGRESS_HINTS) or fallback or "En progreso"


def _completed_status_default(options: list[str], fallback: str | None = None) -> str:
    explicit_closed = next((option for option in options if is_closed_status(option)), None)
    return explicit_closed or _pick_status_by_hints(options, STATUS_COMPLETED_HINTS) or fallback or "Completada"


def _status_badge_class(status_value: str | None) -> str:
    normalized = _normalize_text(status_value)
    if is_closed_status(normalized) or _status_matches(normalized, STATUS_COMPLETED_HINTS):
        return "success"
    if _status_matches(normalized, ("bloq", "blocked", "hold")):
        return "danger"
    if _status_matches(normalized, STATUS_IN_PROGRESS_HINTS):
        return "info"
    if _status_matches(normalized, STATUS_PENDING_HINTS):
        return "secondary"
    return "light"


def _to_int(value: str | None):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_positive_int(value: str | None):
    raw = _safe_strip(value)
    if not raw:
        return None
    try:
        converted = int(raw)
        return converted if converted > 0 else None
    except (TypeError, ValueError):
        return None


def _to_decimal(value: str | None):
    return parse_decimal_input(value)


_parse_date = parse_date_input


def _safe_next_url() -> str | None:
    raw_next = _safe_strip(request.values.get("next"))
    if not raw_next:
        return None
    parsed = urlsplit(raw_next)
    if parsed.scheme or parsed.netloc:
        return None
    if not raw_next.startswith("/") or raw_next.startswith("//"):
        return None
    return raw_next


def _task_detail_redirect(project_id: int, task_id: int):
    next_url = _safe_next_url()
    if next_url:
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id, next=next_url))
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))


def _load_project_or_404(project_id: int) -> Project:
    if project_id and not g.user.full_access and g.user.username != "admin":
        allowed_ids = allowed_project_ids(g.user)
        if allowed_ids is not None and project_id not in set(allowed_ids):
            abort(403)
    stmt = select(Project).options(selectinload(Project.client)).where(Project.id == project_id)
    project = db.session.execute(stmt).scalar_one_or_none()
    if not project:
        abort(404)
    return project


def _task_list_stmt(project_id: int):
    root_task_id = case(
        (Task.parent_task_id.is_(None), Task.id),
        else_=Task.parent_task_id,
    )
    parent_first = case((Task.parent_task_id.is_(None), 0), else_=1)
    return (
        select(Task)
        .where(Task.project_id == project_id)
        .options(selectinload(Task.parent_task))
        .order_by(
            Task.sort_order.asc(),
            root_task_id.asc(),
            parent_first.asc(),
            Task.project_task_id.asc(),
            Task.id.asc(),
        )
    )


def _task_list_stmt_filtered(project_id: int, hide_completed: bool):
    stmt = _task_list_stmt(project_id)
    if not hide_completed:
        return stmt
    return stmt.where(
        or_(
            Task.status.is_(None),
            func.lower(func.trim(Task.status)).notin_(list(CLOSED_STATUSES)),
        )
    )


def _task_status_options() -> list[str]:
    if not g.get("user"):
        return []
    return db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_statuses",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()


def _task_type_options() -> list[str]:
    if not g.get("user"):
        return ["Tarea", "Hito"]
    values = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_types",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    if not values:
        seed_default_catalogs_for_user(g.user.id)
        db.session.commit()
        values = db.session.execute(
            select(SystemCatalogOptionConfig.name)
            .where(
                SystemCatalogOptionConfig.owner_user_id == g.user.id,
                SystemCatalogOptionConfig.module_key == "projects",
                SystemCatalogOptionConfig.catalog_key == "task_types",
                SystemCatalogOptionConfig.is_active.is_(True),
            )
            .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
        ).scalars().all()
    return values or ["Tarea", "Hito"]


def _task_priority_options() -> list[str]:
    if not g.get("user"):
        return []
    values = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_priorities",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    if not values:
        seed_default_catalogs_for_user(g.user.id)
        db.session.commit()
        values = db.session.execute(
            select(SystemCatalogOptionConfig.name)
            .where(
                SystemCatalogOptionConfig.owner_user_id == g.user.id,
                SystemCatalogOptionConfig.module_key == "projects",
                SystemCatalogOptionConfig.catalog_key == "task_priorities",
                SystemCatalogOptionConfig.is_active.is_(True),
            )
            .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
        ).scalars().all()
    return values


def _normalize_schedule_mode(raw_value: str | None, fallback: str = "automatic") -> str:
    value = _safe_strip(raw_value).lower()
    if value in set(TASK_SCHEDULE_MODES):
        return value
    return fallback


def _project_use_calendar_days(project: Project) -> bool:
    raw_value = getattr(project, "schedule_use_calendar_days", False)
    if isinstance(raw_value, str):
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw_value)


def _is_project_working_day(day: date, use_calendar_days: bool) -> bool:
    return True if use_calendar_days else day.weekday() < 5


def _next_project_working_day(day: date, use_calendar_days: bool) -> date:
    current = day
    while not _is_project_working_day(current, use_calendar_days):
        current += timedelta(days=1)
    return current


def _add_project_days(start_day: date, day_count: int, use_calendar_days: bool) -> date:
    day_count = max(1, int(day_count))
    current = _next_project_working_day(start_day, use_calendar_days)
    consumed = 1
    while consumed < day_count:
        current += timedelta(days=1)
        if _is_project_working_day(current, use_calendar_days):
            consumed += 1
    return current


def _count_project_days(start_day: date, end_day: date, use_calendar_days: bool) -> int:
    if end_day < start_day:
        return 0
    cursor = start_day
    count = 0
    while cursor <= end_day:
        if _is_project_working_day(cursor, use_calendar_days):
            count += 1
        cursor += timedelta(days=1)
    return max(1, count)


def _predecessor_ids_from_form(form) -> list[int]:
    ids: list[int] = []
    for raw in form.getlist("predecessor_task_ids"):
        value = _to_int(raw)
        if value:
            ids.append(value)
    unique_ids: list[int] = []
    seen: set[int] = set()
    for item in ids:
        if item in seen:
            continue
        seen.add(item)
        unique_ids.append(item)
    return unique_ids


def _next_project_task_id(project_id: int) -> int:
    current_max = db.session.execute(
        select(Task.project_task_id)
        .where(Task.project_id == project_id)
        .order_by(Task.project_task_id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (current_max or 0) + 1


def _validate_predecessor_links(
    project_id: int,
    predecessor_ids: list[int],
    *,
    current_task_id: int | None = None,
) -> list[str]:
    errors: list[str] = []
    if not predecessor_ids:
        return errors

    tasks = db.session.execute(
        select(Task.id, Task.project_id, Task.project_task_id, Task.due_date).where(Task.id.in_(predecessor_ids))
    ).all()
    found_ids = {row[0] for row in tasks}
    for predecessor_id in predecessor_ids:
        if predecessor_id not in found_ids:
            errors.append(f"La tarea predecesora #{predecessor_id} no existe.")
            continue
        row = next((item for item in tasks if item[0] == predecessor_id), None)
        display_id = row[2] if row and row[2] else predecessor_id
        if row and row[1] != project_id:
            errors.append(f"La tarea predecesora #{display_id} no pertenece al proyecto.")
    if current_task_id and current_task_id in set(predecessor_ids):
        errors.append("Una tarea no puede ser predecesora de sí misma.")
    return errors


def _sync_task_predecessors(task_id: int, predecessor_ids: list[int]) -> None:
    db.session.execute(
        TaskDependency.__table__.delete().where(TaskDependency.successor_task_id == task_id)
    )
    for predecessor_id in predecessor_ids:
        db.session.add(
            TaskDependency(
                predecessor_task_id=predecessor_id,
                successor_task_id=task_id,
                dependency_type=DEFAULT_DEPENDENCY_TYPE,
            )
        )


def _extend_resource_availability_until(resource_id: int, up_to: date) -> bool:
    row = db.session.execute(
        select(ResourceAvailability)
        .where(
            ResourceAvailability.resource_id == resource_id,
            ResourceAvailability.is_active.is_(True),
            ResourceAvailability.valid_from <= up_to,
        )
        .order_by(ResourceAvailability.valid_from.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not row:
        return False
    if row.valid_to is None or row.valid_to >= up_to:
        return True
    next_row = db.session.execute(
        select(ResourceAvailability)
        .where(
            ResourceAvailability.resource_id == resource_id,
            ResourceAvailability.is_active.is_(True),
            ResourceAvailability.valid_from > row.valid_from,
        )
        .order_by(ResourceAvailability.valid_from.asc())
        .limit(1)
    ).scalar_one_or_none()
    target_end = up_to
    if next_row and next_row.valid_from <= target_end:
        target_end = next_row.valid_from - timedelta(days=1)
    if target_end < row.valid_from:
        return False
    row.valid_to = target_end
    return True


def _simulate_resource_schedule(
    day_rows: list[dict],
    *,
    use_calendar_days: bool,
    required_hours: float | None,
    required_days: int | None,
) -> tuple[date | None, date | None, bool, date | None]:
    used_start: date | None = None
    used_end: date | None = None
    remaining_hours = required_hours if required_hours is not None else 0.0
    remaining_days = required_days if required_days is not None else 0
    missing_availability_day: date | None = None

    for row in day_rows:
        day = date.fromisoformat(row["date"])
        if not _is_project_working_day(day, use_calendar_days):
            continue
        if not bool(row.get("is_working_day", False)):
            continue
        if bool(row.get("calendar_holiday", False)):
            continue
        if row.get("availability_id") is None and missing_availability_day is None:
            missing_availability_day = day
        net_available = float(row.get("net_available_hours") or 0.0)
        if net_available <= 0:
            continue
        if used_start is None:
            used_start = day
        used_end = day

        if required_hours is not None:
            remaining_hours -= net_available
            if remaining_hours <= 0:
                return used_start, used_end, True, missing_availability_day
        else:
            remaining_days -= 1
            if remaining_days <= 0:
                return used_start, used_end, True, missing_availability_day

    return used_start, used_end, False, missing_availability_day


def _resource_capacity_in_window(
    day_rows: list[dict],
    *,
    start_date: date,
    end_date: date,
    use_calendar_days: bool,
    required_days: int | None,
    required_hours: float | None,
) -> tuple[bool, date | None, bool]:
    """
    Valida capacidad del recurso dentro de una ventana fija [start_date, end_date].
    Devuelve:
    - completed: si cubre lo requerido dentro de la ventana
    - first_missing_day: primer día laborable/proyecto sin capacidad suficiente
    - missing_by_absent_availability: si faltó por ausencia de tramo de disponibilidad
    """
    covered_days = 0
    covered_hours = 0.0
    first_missing_day: date | None = None
    missing_by_absent_availability = False

    for row in day_rows:
        day = date.fromisoformat(row["date"])
        if day < start_date or day > end_date:
            continue
        if not _is_project_working_day(day, use_calendar_days):
            continue
        if bool(row.get("calendar_holiday", False)):
            if first_missing_day is None:
                first_missing_day = day
            continue
        if not bool(row.get("is_working_day", False)):
            if first_missing_day is None:
                first_missing_day = day
            if row.get("availability_id") is None:
                missing_by_absent_availability = True
            continue

        net_available = float(row.get("net_available_hours") or 0.0)
        if net_available <= 0:
            if first_missing_day is None:
                first_missing_day = day
            if row.get("availability_id") is None:
                missing_by_absent_availability = True
            continue

        covered_days += 1
        covered_hours += net_available

    if required_days is not None:
        return covered_days >= max(1, int(required_days)), first_missing_day, missing_by_absent_availability
    if required_hours is not None:
        return covered_hours >= float(required_hours), first_missing_day, missing_by_absent_availability
    return True, None, False


def _auto_schedule_task(
    project: Project,
    payload: dict,
    *,
    predecessor_ids: list[int],
    current_task_id: int | None = None,
    extend_resource_availability: bool = False,
) -> list[str]:
    errors: list[str] = []
    use_calendar_days = _project_use_calendar_days(project)
    predecessor_due_dates = db.session.execute(
        select(Task.id, Task.project_task_id, Task.start_date, Task.due_date).where(Task.id.in_(predecessor_ids))
    ).all() if predecessor_ids else []
    predecessor_max_due = None
    for predecessor_id, predecessor_project_task_id, predecessor_start_date, due_date in predecessor_due_dates:
        predecessor_reference_date = due_date or predecessor_start_date
        if predecessor_reference_date is None:
            display_id = predecessor_project_task_id or predecessor_id
            errors.append(f"La tarea predecesora #{display_id} no tiene fecha de referencia.")
            continue
        predecessor_max_due = (
            predecessor_reference_date
            if predecessor_max_due is None
            else max(predecessor_max_due, predecessor_reference_date)
        )
    if errors:
        return errors

    if predecessor_max_due:
        # Con predecesoras, la regla principal es "a continuación":
        # arrancar inmediatamente después de la última predecesora.
        earliest_start = predecessor_max_due + timedelta(days=1)
    else:
        earliest_start = payload.get("start_date") or project.estimated_start_date or date.today()
    earliest_start = _next_project_working_day(earliest_start, use_calendar_days)

    if payload.get("is_milestone"):
        payload["start_date"] = earliest_start
        payload["due_date"] = None
        payload["estimated_duration_days"] = None
        return errors

    duration_days = payload.get("estimated_duration_days")
    required_days = int(duration_days) if duration_days and int(duration_days) > 0 else None
    required_hours = float(payload.get("estimated_hours")) if payload.get("estimated_hours") is not None else None
    if required_hours is not None and required_hours <= 0:
        required_hours = None
    if required_hours is None and required_days is None:
        if payload.get("start_date") and payload.get("due_date"):
            required_days = _count_project_days(payload["start_date"], payload["due_date"], use_calendar_days)
        else:
            required_days = 1

    responsible_resource_id = payload.get("responsible_resource_id")
    if not responsible_resource_id:
        payload["start_date"] = earliest_start
        if required_days is not None:
            payload["due_date"] = _add_project_days(earliest_start, required_days, use_calendar_days)
            payload["estimated_duration_days"] = required_days
        elif payload.get("due_date"):
            payload["estimated_duration_days"] = _count_project_days(
                payload["start_date"], payload["due_date"], use_calendar_days
            )
        return errors

    if required_days is not None:
        # Regla de negocio:
        # En planificación de proyecto, la duración define el rango temporal.
        # La disponibilidad diaria del recurso no debe modificar fechas
        # cuando la duración está explicitada.
        target_start = earliest_start
        target_end = _add_project_days(target_start, required_days, use_calendar_days)
        payload["start_date"] = target_start
        payload["due_date"] = target_end
        payload["estimated_duration_days"] = required_days
        return errors

    horizon_end = earliest_start + timedelta(days=730)
    availability_payload = calculate_resource_net_availability(
        responsible_resource_id,
        earliest_start,
        horizon_end,
        owner_user_id=g.user.id if g.get("user") else None,
    )
    start_date, end_date, completed, missing_availability_day = _simulate_resource_schedule(
        availability_payload.get("days", []),
        use_calendar_days=use_calendar_days,
        required_hours=required_hours,
        required_days=None,
    )

    if not completed and missing_availability_day and extend_resource_availability:
        guessed_days = required_days or max(1, ceil((required_hours or 8.0) / 8.0))
        target_end = _add_project_days(earliest_start, guessed_days, use_calendar_days)
        _extend_resource_availability_until(responsible_resource_id, target_end)
        availability_payload = calculate_resource_net_availability(
            responsible_resource_id,
            earliest_start,
            horizon_end,
            owner_user_id=g.user.id if g.get("user") else None,
        )
        start_date, end_date, completed, missing_availability_day = _simulate_resource_schedule(
            availability_payload.get("days", []),
            use_calendar_days=use_calendar_days,
            required_hours=required_hours,
            required_days=None,
        )

    if not completed:
        if missing_availability_day and not extend_resource_availability:
            errors.append(
                "El recurso no tiene disponibilidad configurada para cubrir la tarea. "
                "Marcá 'Extender disponibilidad' para ampliar la vigencia automáticamente."
            )
        else:
            errors.append(
                "No hay disponibilidad neta suficiente del recurso para el esfuerzo/plazo indicado."
            )
        return errors

    payload["start_date"] = start_date
    payload["due_date"] = end_date
    if required_days is not None:
        # Con duración explícita en días, preservar el valor ingresado por usuario
        # aunque el rango calendario se extienda por disponibilidad.
        payload["estimated_duration_days"] = required_days
    elif start_date and end_date:
        payload["estimated_duration_days"] = _count_project_days(start_date, end_date, use_calendar_days)
    return errors


def _task_children_metadata(tasks: list[Task]):
    child_count_by_parent = {}
    for task in tasks:
        if task.parent_task_id:
            child_count_by_parent[task.parent_task_id] = child_count_by_parent.get(task.parent_task_id, 0) + 1
    parent_task_ids = sorted(child_count_by_parent.keys())
    return parent_task_ids, child_count_by_parent


def _resolve_project_calendar_name(project: Project) -> str | None:
    if project.project_manager_resource_id:
        pm_resource = db.session.get(Resource, project.project_manager_resource_id)
        if pm_resource and _safe_strip(pm_resource.calendar_name):
            return _safe_strip(pm_resource.calendar_name)

    calendar_counter: Counter[str] = Counter()

    task_resource_rows = db.session.execute(
        select(Resource.calendar_name)
        .join(Task, Task.responsible_resource_id == Resource.id)
        .where(Task.project_id == project.id)
    ).scalars().all()
    for calendar_name in task_resource_rows:
        cleaned = _safe_strip(calendar_name)
        if cleaned:
            calendar_counter[cleaned] += 1

    project_resource_rows = db.session.execute(
        select(Resource.calendar_name)
        .join(ProjectResource, ProjectResource.resource_id == Resource.id)
        .where(ProjectResource.project_id == project.id, ProjectResource.is_active.is_(True))
    ).scalars().all()
    for calendar_name in project_resource_rows:
        cleaned = _safe_strip(calendar_name)
        if cleaned:
            calendar_counter[cleaned] += 1

    if not calendar_counter:
        return None
    return calendar_counter.most_common(1)[0][0]


def _project_holiday_dates(project: Project) -> list[str]:
    if not g.get("user"):
        return []
    calendar_name = _resolve_project_calendar_name(project)
    if not calendar_name:
        return []
    rows = db.session.execute(
        select(TeamCalendarHolidayConfig.holiday_date)
        .where(
            TeamCalendarHolidayConfig.owner_user_id == g.user.id,
            TeamCalendarHolidayConfig.calendar_name == calendar_name,
            TeamCalendarHolidayConfig.is_active.is_(True),
        )
        .order_by(TeamCalendarHolidayConfig.holiday_date.asc())
    ).scalars().all()
    return [holiday_date.isoformat() for holiday_date in rows if holiday_date]


def _build_gantt_context(project_id: int):
    project = db.session.get(Project, project_id)
    use_calendar_days = _project_use_calendar_days(project) if project else False
    tasks = db.session.execute(
        select(Task)
        .where(Task.project_id == project_id)
        .options(selectinload(Task.parent_task))
        .order_by(Task.start_date.asc().nullslast(), Task.id.asc())
    ).scalars().all()
    dependencies = db.session.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.successor_task_id == Task.id)
        .where(Task.project_id == project_id)
        .order_by(TaskDependency.id.asc())
    ).scalars().all()
    dependency_by_successor = {}
    for dep in dependencies:
        dependency_by_successor.setdefault(dep.successor_task_id, []).append(dep.predecessor_task_id)
    duration_by_task_id = {}
    visual_end_by_task_id = {}
    for task in tasks:
        if task.start_date and task.estimated_duration_days and task.estimated_duration_days > 0:
            visual_end = _add_project_days(task.start_date, int(task.estimated_duration_days), use_calendar_days)
            visual_end_by_task_id[task.id] = visual_end
            duration_by_task_id[task.id] = int(task.estimated_duration_days)
        elif task.start_date and task.due_date:
            visual_end_by_task_id[task.id] = task.due_date
            duration_by_task_id[task.id] = _count_project_days(task.start_date, task.due_date, use_calendar_days)
        else:
            visual_end_by_task_id[task.id] = task.start_date
            duration_by_task_id[task.id] = task.estimated_duration_days
    holiday_dates = _project_holiday_dates(project) if project else []
    return {
        "tasks": tasks,
        "dependency_by_successor": dependency_by_successor,
        "duration_by_task_id": duration_by_task_id,
        "visual_end_by_task_id": visual_end_by_task_id,
        "holiday_dates": holiday_dates,
        "use_calendar_days": bool(use_calendar_days),
    }


def _ensure_same_project_task_or_none(project_id: int, task_id: int | None):
    if not task_id:
        return None
    task = db.session.get(Task, task_id)
    if not task or task.project_id != project_id:
        return None
    return task


def _validate_task_payload(project_id: int, form, current_task_id: int | None = None, current_task: Task | None = None):
    errors = []
    project = db.session.get(Project, project_id)
    use_calendar_days = _project_use_calendar_days(project) if project else False
    title = _safe_strip(form.get("title"))
    if len(title) < 3:
        errors.append("El título de la tarea debe tener al menos 3 caracteres.")

    start_date = _parse_date(form.get("start_date"))
    due_date = _parse_date(form.get("due_date"))
    raw_estimated_duration_days = _safe_strip(form.get("estimated_duration_days"))
    estimated_duration_days = _to_int(raw_estimated_duration_days)
    estimated_hours = _to_decimal(form.get("estimated_hours"))
    logged_hours = _to_decimal(form.get("logged_hours"))

    task_type = _safe_strip(form.get("task_type"))
    available_task_types = _task_type_options()
    if not task_type:
        task_type = "Tarea" if "Tarea" in set(available_task_types) else (available_task_types[0] if available_task_types else "")
    if task_type and task_type not in set(available_task_types):
        errors.append("El tipo de tarea seleccionado no es válido.")
    is_milestone = (task_type or "").strip().lower() == "hito"

    # Duración (calendario) y esfuerzo (horas) son conceptos distintos.
    if is_milestone:
        due_date = None
        estimated_duration_days = None
    else:
        # Reglas:
        # 1) Si hay inicio + duración explícita -> calcular fin desde duración.
        # 2) Si hay inicio + fin y no hay duración explícita -> calcular duración.
        # 3) Si hay inicio + duración y no hay fin -> autocompletar fin.
        if start_date and estimated_duration_days is not None and raw_estimated_duration_days != "":
            due_date = _add_project_days(start_date, max(estimated_duration_days, 1), use_calendar_days)
        elif start_date and due_date:
            estimated_duration_days = _count_project_days(start_date, due_date, use_calendar_days)
        elif start_date and estimated_duration_days and not due_date:
            due_date = _add_project_days(start_date, max(estimated_duration_days, 1), use_calendar_days)
    actual_start_date = _parse_date(form.get("actual_start_date"))
    actual_end_date = _parse_date(form.get("actual_end_date"))
    if start_date and due_date and start_date > due_date:
        errors.append("La fecha de inicio no puede ser posterior al vencimiento.")
    if not is_milestone and estimated_duration_days is not None and estimated_duration_days <= 0:
        errors.append("La duración debe ser mayor a 0 días.")
    if estimated_hours is not None and estimated_hours < 0:
        errors.append("El esfuerzo estimado no puede ser negativo.")
    if logged_hours is not None and logged_hours < 0:
        errors.append("Las horas imputadas no pueden ser negativas.")
    if actual_start_date and actual_end_date and actual_start_date > actual_end_date:
        errors.append("La fecha real de inicio no puede ser posterior al cierre real.")

    progress_percent = _to_int(form.get("progress_percent"))
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        errors.append("El porcentaje de avance debe estar entre 0 y 100.")

    default_project_task_id = current_task.project_task_id if current_task else _next_project_task_id(project_id)
    project_task_id = _to_positive_int(form.get("project_task_id")) or default_project_task_id
    if project_task_id <= 0:
        errors.append("El ID de tarea del proyecto debe ser mayor a 0.")
    duplicate_stmt = select(Task.id).where(
        Task.project_id == project_id,
        Task.project_task_id == project_task_id,
    )
    if current_task_id:
        duplicate_stmt = duplicate_stmt.where(Task.id != current_task_id)
    duplicate_id = db.session.execute(duplicate_stmt).scalar_one_or_none()
    if duplicate_id:
        errors.append("Ya existe una tarea en este proyecto con ese ID.")

    parent_task_id = _to_int(form.get("parent_task_id"))
    errors.extend(validate_parent_assignment(project_id, parent_task_id, current_task_id))

    available_statuses = _task_status_options()
    raw_status_value = _safe_strip(form.get("status"))
    if current_task:
        status_value = raw_status_value or (current_task.status or _pending_status_default(available_statuses))
    else:
        status_value = raw_status_value or _pending_status_default(available_statuses)
    if status_value and available_statuses and status_value not in set(available_statuses):
        errors.append("El estado seleccionado no es válido.")
    if current_task and task_has_subtasks(current_task.id):
        # Campos calculados: no pueden editarse manualmente si la tarea es padre.
        if start_date != current_task.start_date or due_date != current_task.due_date:
            errors.append("Las fechas del padre se calculan automáticamente a partir de sus subtareas.")
        if (progress_percent if progress_percent is not None else 0) != (current_task.progress_percent or 0):
            errors.append("El avance del padre se calcula automáticamente a partir de sus subtareas.")
        if logged_hours not in (None, 0):
            errors.append("No se permite imputación directa de horas en tareas padre con subtareas.")
        if is_closed_status(status_value) and has_open_subtasks(current_task.id):
            errors.append("No se puede cerrar una tarea padre con subtareas abiertas.")

    responsible_resource_id = _to_int(form.get("responsible_resource_id"))
    responsible_name = ""
    if responsible_resource_id:
        resource = db.session.get(Resource, responsible_resource_id)
        if not resource or not resource.is_active:
            errors.append("El responsable seleccionado no es válido.")
        else:
            responsible_name = resource.full_name

    priority_value = _safe_strip(form.get("priority"))
    available_priorities = _task_priority_options()
    if priority_value and priority_value not in set(available_priorities):
        errors.append("La prioridad seleccionada no es válida.")
    default_mode = current_task.schedule_mode if current_task and current_task.schedule_mode else "automatic"
    schedule_mode = _normalize_schedule_mode(form.get("schedule_mode"), fallback=default_mode)
    if schedule_mode not in set(TASK_SCHEDULE_MODES):
        errors.append("Modo de planificación inválido.")

    if progress_percent is None:
        progress_percent = current_task.progress_percent if current_task else 0
    progress_percent = max(0, min(int(progress_percent), 100))
    if is_closed_status(status_value):
        progress_percent = 100
    elif progress_percent >= 100:
        status_value = _completed_status_default(available_statuses, fallback=status_value)
        progress_percent = 100
    elif progress_percent > 0 and not is_closed_status(status_value):
        status_value = _in_progress_status_default(available_statuses, fallback=status_value)

    payload = {
        "title": title,
        "project_task_id": project_task_id,
        "description": _safe_strip(form.get("description")),
        "task_type": task_type,
        "status": status_value,
        "priority": priority_value,
        "schedule_mode": schedule_mode,
        "responsible": responsible_name,
        "responsible_resource_id": responsible_resource_id,
        "creator": _safe_strip(form.get("creator")) or (g.user.username if g.user else None),
        "parent_task_id": parent_task_id,
        "start_date": start_date,
        "due_date": due_date,
        "actual_start_date": actual_start_date,
        "actual_end_date": actual_end_date,
        "estimated_duration_days": estimated_duration_days,
        "estimated_hours": estimated_hours,
        "logged_hours": logged_hours,
        "progress_percent": progress_percent if progress_percent is not None else 0,
        "sort_order": _to_int(form.get("sort_order")) or 0,
        "tags": _safe_strip(form.get("tags")),
        "is_milestone": is_milestone,
    }
    return payload, errors


def _is_attachment_allowed(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in TASK_ALLOWED_ATTACHMENT_EXTENSIONS


def _save_task_attachment(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None, None

    original_name = secure_filename(file_storage.filename)
    if not original_name or not _is_attachment_allowed(original_name):
        return None, None, "Formato de adjunto no permitido."

    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{ext}"
    folder = current_app.config["TASK_ATTACHMENT_UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, stored_name))
    return stored_name, original_name, None


def _build_adjacency_for_project(project_id: int):
    deps = db.session.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.predecessor_task_id == Task.id)
        .where(Task.project_id == project_id)
    ).scalars().all()
    graph = {}
    for dep in deps:
        graph.setdefault(dep.predecessor_task_id, set()).add(dep.successor_task_id)
    return graph


def _task_payload_from_entity(task: Task) -> dict:
    return {
        "start_date": task.start_date,
        "due_date": task.due_date,
        "estimated_duration_days": task.estimated_duration_days,
        "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
        "responsible_resource_id": task.responsible_resource_id,
        "is_milestone": bool(task.is_milestone),
    }


def _cascade_auto_schedule_successors(project: Project, source_task_id: int) -> tuple[list[int], list[str]]:
    warnings: list[str] = []
    updated_task_ids: list[int] = []
    queue = list(
        db.session.execute(
            select(TaskDependency.successor_task_id).where(TaskDependency.predecessor_task_id == source_task_id)
        ).scalars().all()
    )
    visited: set[int] = set()

    while queue:
        successor_id = queue.pop(0)
        if successor_id in visited:
            continue
        visited.add(successor_id)

        successor = db.session.get(Task, successor_id)
        if not successor or successor.project_id != project.id:
            continue
        if successor.schedule_mode != "automatic":
            continue

        predecessor_ids = db.session.execute(
            select(TaskDependency.predecessor_task_id).where(TaskDependency.successor_task_id == successor.id)
        ).scalars().all()
        payload = _task_payload_from_entity(successor)
        errors = _auto_schedule_task(
            project,
            payload,
            predecessor_ids=predecessor_ids,
            current_task_id=successor.id,
            extend_resource_availability=False,
        )
        if errors:
            display_id = successor.project_task_id or successor.id
            warnings.append(
                f"No se pudo recalcular automáticamente la tarea #{display_id}: {errors[0]}"
            )
            continue

        has_changes = False
        for key in ("start_date", "due_date", "estimated_duration_days"):
            if getattr(successor, key) != payload.get(key):
                setattr(successor, key, payload.get(key))
                has_changes = True
        if has_changes:
            updated_task_ids.append(successor.id)
            queue.extend(
                db.session.execute(
                    select(TaskDependency.successor_task_id).where(TaskDependency.predecessor_task_id == successor.id)
                ).scalars().all()
            )
            if successor.parent_task_id:
                recalculate_parent_task(
                    successor.parent_task_id,
                    reason="dependency_chain_reschedule",
                    trigger_task_id=successor.id,
                )

    return updated_task_ids, warnings


def _has_path(graph: dict[int, set[int]], start: int, target: int) -> bool:
    stack = [start]
    seen = set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, ()))
    return False


@bp.route("/", methods=["GET", "POST"])
@login_required
def manage_tasks(project_id: int):
    project = _load_project_or_404(project_id)
    page = _to_int(request.args.get("page")) or 1
    hide_completed = request.args.get("hide_completed", "0") == "1"
    edit_task_id = _to_int(request.args.get("edit_id"))
    edit_task = _ensure_same_project_task_or_none(project.id, edit_task_id)

    if request.method == "POST":
        predecessor_ids = _predecessor_ids_from_form(request.form)
        extend_availability = request.form.get("extend_resource_availability") == "1"
        payload, errors = _validate_task_payload(project.id, request.form)
        errors.extend(_validate_predecessor_links(project.id, predecessor_ids))
        if payload.get("schedule_mode") == "automatic":
            errors.extend(
                _auto_schedule_task(
                    project,
                    payload,
                    predecessor_ids=predecessor_ids,
                    extend_resource_availability=extend_availability,
                )
            )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            task = Task(project_id=project.id, **payload)
            db.session.add(task)
            db.session.flush()
            _sync_task_predecessors(task.id, predecessor_ids)
            if task.parent_task_id:
                recalculate_parent_task(
                    task.parent_task_id,
                    reason="subtask_created",
                    trigger_task_id=task.id,
                )
            db.session.commit()
            flash("Tarea creada.", "success")
            return redirect(
                url_for(
                    "tasks.manage_tasks",
                    project_id=project.id,
                    page=page,
                    hide_completed=1 if hide_completed else 0,
                )
            )

    tasks_pagination = db.paginate(
        _task_list_stmt_filtered(project.id, hide_completed=hide_completed),
        page=page,
        per_page=15,
        error_out=False,
    )
    parent_task_ids, child_count_by_parent = _task_children_metadata(tasks_pagination.items)
    parent_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id, Task.parent_task_id.is_(None)).order_by(Task.title.asc())
    ).scalars().all()
    dependency_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id).order_by(Task.created_at.desc(), Task.id.desc())
    ).scalars().all()
    active_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    return render_template(
        "tasks/task_list.html",
        project=project,
        tasks=tasks_pagination.items,
        tasks_pagination=tasks_pagination,
        parent_candidates=parent_candidates,
        edit_task=edit_task,
        form_values=request.form if request.method == "POST" else {},
        next_project_task_id=_next_project_task_id(project.id),
        current_page=page,
        hide_completed=hide_completed,
        parent_task_ids=parent_task_ids,
        child_count_by_parent=child_count_by_parent,
        edit_task_has_subtasks=task_has_subtasks(edit_task.id) if edit_task else False,
        edit_task_open_subtasks=has_open_subtasks(edit_task.id) if edit_task else False,
        task_statuses=_task_status_options(),
        task_types=_task_type_options(),
        task_priorities=_task_priority_options(),
        default_pending_status=_pending_status_default(_task_status_options()),
        dependency_candidates=dependency_candidates,
        selected_predecessor_ids=_predecessor_ids_from_form(request.form) if request.method == "POST" else [],
        task_schedule_modes=TASK_SCHEDULE_MODES,
        closed_statuses=sorted(CLOSED_STATUSES),
        status_badge_class=_status_badge_class,
        active_resources=active_resources,
        current_list_url=request.full_path.rstrip("?"),
    )


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(project_id: int, task_id: int):
    project = _load_project_or_404(project_id)
    task = _ensure_same_project_task_or_none(project.id, task_id)
    if not task:
        abort(404)

    page = _to_int(request.args.get("page")) or 1
    hide_completed = request.args.get("hide_completed", "0") == "1"
    if request.method == "POST":
        predecessor_ids = _predecessor_ids_from_form(request.form)
        extend_availability = request.form.get("extend_resource_availability") == "1"
        old_parent_id = task.parent_task_id
        old_start_date = task.start_date
        old_due_date = task.due_date
        old_duration_days = task.estimated_duration_days
        payload, errors = _validate_task_payload(project.id, request.form, current_task_id=task.id, current_task=task)
        errors.extend(_validate_predecessor_links(project.id, predecessor_ids, current_task_id=task.id))
        if payload.get("schedule_mode") == "automatic":
            errors.extend(
                _auto_schedule_task(
                    project,
                    payload,
                    predecessor_ids=predecessor_ids,
                    current_task_id=task.id,
                    extend_resource_availability=extend_availability,
                )
            )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            graph = _build_adjacency_for_project(project.id)
            for predecessor_id in predecessor_ids:
                if _has_path(graph, task.id, predecessor_id):
                    flash("No se puede crear dependencia circular.", "danger")
                    return redirect(
                        url_for(
                            "tasks.edit_task",
                            project_id=project.id,
                            task_id=task.id,
                            page=page,
                            hide_completed=1 if hide_completed else 0,
                            next=_safe_next_url() or request.args.get("next"),
                        )
                    )
            for key, value in payload.items():
                setattr(task, key, value)
            db.session.flush()
            _sync_task_predecessors(task.id, predecessor_ids)
            if old_parent_id and old_parent_id != task.parent_task_id:
                recalculate_parent_task(old_parent_id, reason="subtask_moved", trigger_task_id=task.id)
            if task.parent_task_id:
                recalculate_parent_task(task.parent_task_id, reason="subtask_updated", trigger_task_id=task.id)
            changed_timing = (
                old_start_date != task.start_date
                or old_due_date != task.due_date
                or old_duration_days != task.estimated_duration_days
            )
            cascade_warnings: list[str] = []
            cascade_count = 0
            if changed_timing:
                updated_successors, cascade_warnings = _cascade_auto_schedule_successors(project, task.id)
                cascade_count = len(updated_successors)
            db.session.commit()
            if cascade_count:
                flash(f"Se recalcularon {cascade_count} tarea(s) sucesora(s).", "info")
            for warning in cascade_warnings:
                flash(warning, "warning")
            flash("Tarea actualizada.", "success")
            return redirect(
                url_for(
                    "tasks.manage_tasks",
                    project_id=project.id,
                    page=page,
                    hide_completed=1 if hide_completed else 0,
                )
            )

    tasks_pagination = db.paginate(
        _task_list_stmt_filtered(project.id, hide_completed=hide_completed),
        page=page,
        per_page=15,
        error_out=False,
    )
    parent_task_ids, child_count_by_parent = _task_children_metadata(tasks_pagination.items)
    parent_candidates = db.session.execute(
        select(Task)
        .where(Task.project_id == project.id, Task.parent_task_id.is_(None), Task.id != task.id)
        .order_by(Task.title.asc())
    ).scalars().all()
    dependency_candidates = db.session.execute(
        select(Task)
        .where(Task.project_id == project.id, Task.id != task.id)
        .order_by(Task.created_at.desc(), Task.id.desc())
    ).scalars().all()
    active_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    return render_template(
        "tasks/task_list.html",
        project=project,
        tasks=tasks_pagination.items,
        tasks_pagination=tasks_pagination,
        parent_candidates=parent_candidates,
        edit_task=task,
        form_values=request.form if request.method == "POST" else {},
        next_project_task_id=_next_project_task_id(project.id),
        current_page=page,
        hide_completed=hide_completed,
        parent_task_ids=parent_task_ids,
        child_count_by_parent=child_count_by_parent,
        edit_task_has_subtasks=task_has_subtasks(task.id),
        edit_task_open_subtasks=has_open_subtasks(task.id),
        task_statuses=_task_status_options(),
        task_types=_task_type_options(),
        task_priorities=_task_priority_options(),
        default_pending_status=_pending_status_default(_task_status_options()),
        dependency_candidates=dependency_candidates,
        selected_predecessor_ids=(
            _predecessor_ids_from_form(request.form)
            if request.method == "POST"
            else [link.predecessor_task_id for link in task.predecessor_links]
        ),
        task_schedule_modes=TASK_SCHEDULE_MODES,
        closed_statuses=sorted(CLOSED_STATUSES),
        status_badge_class=_status_badge_class,
        active_resources=active_resources,
        current_list_url=request.full_path.rstrip("?"),
    )


@bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(project_id: int, task_id: int):
    page = _to_int(request.args.get("page")) or 1
    hide_completed = request.args.get("hide_completed", "0") == "1"
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)
    parent_id = task.parent_task_id
    db.session.delete(task)
    db.session.flush()
    if parent_id:
        recalculate_parent_task(parent_id, reason="subtask_deleted", trigger_task_id=task_id)
    db.session.commit()
    flash("Tarea eliminada.", "info")
    return redirect(
        url_for(
            "tasks.manage_tasks",
            project_id=project_id,
            page=page,
            hide_completed=1 if hide_completed else 0,
        )
    )


@bp.route("/<int:task_id>/dependencies", methods=["POST"])
@login_required
def add_dependency(project_id: int, task_id: int):
    successor = _ensure_same_project_task_or_none(project_id, task_id)
    predecessor_id = _to_int(request.form.get("predecessor_task_id"))
    if not successor:
        abort(404)
    predecessor = _ensure_same_project_task_or_none(project_id, predecessor_id)
    if not predecessor:
        flash("La tarea predecesora no es válida.", "danger")
        return _task_detail_redirect(project_id, task_id)
    if predecessor.id == successor.id:
        flash("Una tarea no puede depender de sí misma.", "danger")
        return _task_detail_redirect(project_id, task_id)

    exists = db.session.execute(
        select(TaskDependency).where(
            TaskDependency.predecessor_task_id == predecessor.id,
            TaskDependency.successor_task_id == successor.id,
        )
    ).scalar_one_or_none()
    if exists:
        flash("La dependencia ya existe.", "warning")
        return _task_detail_redirect(project_id, task_id)

    graph = _build_adjacency_for_project(project_id)
    if _has_path(graph, successor.id, predecessor.id):
        flash("No se puede crear dependencia circular.", "danger")
        return _task_detail_redirect(project_id, task_id)

    db.session.add(
        TaskDependency(
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
            dependency_type=DEFAULT_DEPENDENCY_TYPE,
        )
    )
    db.session.commit()
    flash("Dependencia agregada.", "success")
    return _task_detail_redirect(project_id, task_id)


@bp.route("/dependencies/<int:dependency_id>/delete", methods=["POST"])
@login_required
def delete_dependency(project_id: int, dependency_id: int):
    dep = db.session.get(TaskDependency, dependency_id)
    if not dep:
        abort(404)
    predecessor = db.session.get(Task, dep.predecessor_task_id)
    successor = db.session.get(Task, dep.successor_task_id)
    if not predecessor or not successor or predecessor.project_id != project_id or successor.project_id != project_id:
        abort(404)
    target_task_id = successor.id
    db.session.delete(dep)
    db.session.commit()
    flash("Dependencia eliminada.", "info")
    return _task_detail_redirect(project_id, target_task_id)


@bp.route("/<int:task_id>", methods=["GET", "POST"])
@login_required
def task_detail(project_id: int, task_id: int):
    project = _load_project_or_404(project_id)
    task = _ensure_same_project_task_or_none(project.id, task_id)
    if not task:
        abort(404)

    if request.method == "POST":
        comment_body = _safe_strip(request.form.get("comment_body"))
        if comment_body:
            db.session.add(
                TaskComment(
                    task_id=task.id,
                    author=g.user.username if g.user else None,
                    body=comment_body,
                )
            )
            flash("Comentario agregado.", "success")

        file_name, original_name, error = _save_task_attachment(request.files.get("attachment"))
        if error:
            flash(error, "danger")
        elif file_name:
            db.session.add(
                TaskAttachment(
                    task_id=task.id,
                    file_name=file_name,
                    original_name=original_name,
                    uploaded_by=g.user.username if g.user else None,
                )
            )
            flash("Adjunto agregado.", "success")

        db.session.commit()
        return _task_detail_redirect(project.id, task.id)

    predecessor_candidates = db.session.execute(
        select(Task)
        .where(Task.project_id == project.id, Task.id != task.id)
        .order_by(Task.created_at.desc(), Task.id.desc())
    ).scalars().all()

    dependencies = db.session.execute(
        select(TaskDependency)
        .where(
            (TaskDependency.predecessor_task_id == task.id)
            | (TaskDependency.successor_task_id == task.id)
        )
        .options(
            selectinload(TaskDependency.predecessor_task),
            selectinload(TaskDependency.successor_task),
        )
    ).scalars().all()
    collaborators = db.session.execute(
        select(TaskResource)
        .where(TaskResource.task_id == task.id, TaskResource.is_active.is_(True))
        .options(selectinload(TaskResource.resource))
        .order_by(TaskResource.id.desc())
    ).scalars().all()
    available_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    next_url = _safe_next_url()
    return render_template(
        "tasks/task_detail.html",
        project=project,
        task=task,
        predecessor_candidates=predecessor_candidates,
        dependencies=dependencies,
        task_statuses=_task_status_options(),
        closed_statuses=sorted(CLOSED_STATUSES),
        task_has_open_subtasks=has_open_subtasks(task.id),
        collaborators=collaborators,
        available_resources=available_resources,
        next_url=next_url,
        back_url=next_url or url_for("tasks.manage_tasks", project_id=project.id),
    )


@bp.route("/<int:task_id>/collaborators/add", methods=["POST"])
@login_required
def add_task_collaborator(project_id: int, task_id: int):
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)

    resource_id = _to_int(request.form.get("resource_id"))
    if not resource_id:
        flash("Selecciona un recurso.", "danger")
        return _task_detail_redirect(project_id, task_id)

    errors = validate_assignment(resource_id, role_id=None)
    errors.extend(validate_task_assignment_project_consistency(task.id, resource_id))
    if errors:
        for error in errors:
            flash(error, "danger")
        return _task_detail_redirect(project_id, task_id)

    exists = db.session.execute(
        select(TaskResource.id).where(
            TaskResource.task_id == task.id,
            TaskResource.resource_id == resource_id,
            TaskResource.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if exists:
        flash("El colaborador ya está asignado.", "warning")
    else:
        reference_date = task.start_date or date.today()
        applied_cost_id = find_applicable_cost_id(resource_id, reference_date)
        db.session.add(
            TaskResource(
                task_id=task.id,
                resource_id=resource_id,
                resource_cost_id=applied_cost_id,
                is_primary=False,
                is_active=True,
            )
        )
        db.session.commit()
        flash("Colaborador agregado.", "success")
    return _task_detail_redirect(project_id, task_id)


@bp.route("/collaborators/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_task_collaborator(project_id: int, assignment_id: int):
    assignment = db.session.get(TaskResource, assignment_id)
    if not assignment:
        abort(404)
    task = db.session.get(Task, assignment.task_id)
    if not task or task.project_id != project_id:
        abort(404)
    db.session.delete(assignment)
    db.session.commit()
    flash("Colaborador removido.", "info")
    return _task_detail_redirect(project_id, task.id)


@bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def update_task_status(project_id: int, task_id: int):
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)

    next_status = _safe_strip(request.form.get("status"))
    if not next_status:
        flash("Debes seleccionar un estado.", "warning")
        return _task_detail_redirect(project_id, task_id)

    if task_has_subtasks(task.id) and is_closed_status(next_status) and has_open_subtasks(task.id):
        flash("No se puede cerrar la tarea mientras tenga subtareas abiertas.", "danger")
        return _task_detail_redirect(project_id, task_id)

    available_statuses = _task_status_options()
    if next_status not in set(available_statuses):
        flash("El estado seleccionado no es válido.", "danger")
        return _task_detail_redirect(project_id, task_id)
    previous_status = task.status
    task.status = next_status
    if is_closed_status(next_status):
        task.progress_percent = 100
    elif (task.progress_percent or 0) >= 100:
        task.status = _completed_status_default(available_statuses, fallback=next_status)
        task.progress_percent = 100
    elif (task.progress_percent or 0) > 0:
        task.status = _in_progress_status_default(available_statuses, fallback=next_status)
    db.session.flush()
    if task.parent_task_id and previous_status != next_status:
        recalculate_parent_task(task.parent_task_id, reason="subtask_status_updated", trigger_task_id=task.id)
    db.session.commit()
    flash("Estado actualizado.", "success")
    return _task_detail_redirect(project_id, task_id)


@bp.route("/attachments/<int:attachment_id>/download")
@login_required
def download_attachment(project_id: int, attachment_id: int):
    attachment = db.session.get(TaskAttachment, attachment_id)
    if not attachment:
        abort(404)
    task = db.session.get(Task, attachment.task_id)
    if not task or task.project_id != project_id:
        abort(404)
    return send_from_directory(
        current_app.config["TASK_ATTACHMENT_UPLOAD_FOLDER"],
        attachment.file_name,
        as_attachment=True,
        download_name=attachment.original_name,
    )


@bp.route("/gantt")
@login_required
def gantt(project_id: int):
    project = _load_project_or_404(project_id)
    use_calendar_days = _project_use_calendar_days(project)
    tasks = db.session.execute(
        select(Task).where(Task.project_id == project.id).order_by(Task.start_date.asc().nullslast(), Task.id.asc())
    ).scalars().all()
    dependencies = db.session.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.successor_task_id == Task.id)
        .where(Task.project_id == project.id)
        .order_by(TaskDependency.id.asc())
    ).scalars().all()
    dependency_by_successor = {}
    for dep in dependencies:
        dependency_by_successor.setdefault(dep.successor_task_id, []).append(dep.predecessor_task_id)

    duration_by_task_id = {}
    visual_end_by_task_id = {}
    for task in tasks:
        if task.start_date and task.estimated_duration_days and task.estimated_duration_days > 0:
            visual_end = _add_project_days(task.start_date, int(task.estimated_duration_days), use_calendar_days)
            visual_end_by_task_id[task.id] = visual_end
            duration_by_task_id[task.id] = int(task.estimated_duration_days)
        elif task.start_date and task.due_date:
            visual_end_by_task_id[task.id] = task.due_date
            duration_by_task_id[task.id] = _count_project_days(task.start_date, task.due_date, use_calendar_days)
        else:
            visual_end_by_task_id[task.id] = task.start_date
            duration_by_task_id[task.id] = task.estimated_duration_days

    return render_template(
        "tasks/gantt.html",
        project=project,
        tasks=tasks,
        dependency_by_successor=dependency_by_successor,
        duration_by_task_id=duration_by_task_id,
        visual_end_by_task_id=visual_end_by_task_id,
        holiday_dates=_project_holiday_dates(project),
        use_calendar_days=bool(use_calendar_days),
        back_url=_safe_next_url() or url_for("tasks.manage_tasks", project_id=project.id),
    )
