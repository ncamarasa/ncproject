from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, select

from project_manager.extensions import db
from project_manager.models import (
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceAvailabilityException,
    ResourceCost,
    ResourceRole,
    RoleSalePrice,
    Task,
    TaskResource,
    TeamCalendarHolidayConfig,
    TeamRole,
)


VALID_RESOURCE_TYPES = {"interno", "externo", "internal", "external"}
VALID_AVAILABILITY_TYPES = {"full_time", "part_time", "custom"}
VALID_EXCEPTION_TYPES = {"time_off", "vacation", "leave", "holiday", "blocked"}
VALID_WEEKDAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CANONICAL_SYSTEM_TEAM_ROLES: dict[str, tuple[str, ...]] = {
    "Project Manager": ("project manager", "pm"),
    "Ejecutivo comercial": ("ejecutivo comercial", "ejecutivo de cuenta"),
    "Gerente de cuenta": ("gerente de cuenta", "responsable cliente", "account manager"),
    "Responsable delivery": (
        "responsable delivery",
        "delivery manager",
        "responsable tecnico",
        "responsable técnico",
    ),
}


def normalize_email(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    return v or None


def _merge_role_links(old_role_id: int, target_role_id: int) -> None:
    links = db.session.execute(
        select(ResourceRole.id, ResourceRole.resource_id).where(ResourceRole.role_id == old_role_id)
    ).all()
    for link_id, resource_id in links:
        duplicate = db.session.execute(
            select(ResourceRole.id).where(
                ResourceRole.resource_id == resource_id,
                ResourceRole.role_id == target_role_id,
            )
        ).scalar_one_or_none()
        if duplicate:
            row = db.session.get(ResourceRole, link_id)
            if row:
                db.session.delete(row)
            continue
        row = db.session.get(ResourceRole, link_id)
        if row:
            row.role_id = target_role_id

    db.session.execute(
        ProjectResource.__table__.update()
        .where(ProjectResource.role_id == old_role_id)
        .values(role_id=target_role_id)
    )
    db.session.execute(
        TaskResource.__table__.update()
        .where(TaskResource.role_id == old_role_id)
        .values(role_id=target_role_id)
    )


def ensure_system_team_roles() -> None:
    for canonical_name, aliases in CANONICAL_SYSTEM_TEAM_ROLES.items():
        normalized_aliases = {alias.strip().lower() for alias in aliases}
        roles = db.session.execute(
            select(TeamRole).where(db.func.lower(TeamRole.name).in_(normalized_aliases)).order_by(TeamRole.id.asc())
        ).scalars().all()

        if not roles:
            db.session.add(
                TeamRole(
                    name=canonical_name,
                    description=None,
                    is_active=True,
                    is_system=True,
                    is_editable=False,
                    is_deletable=False,
                )
            )
            continue

        target = next((role for role in roles if role.name.strip().lower() == canonical_name.lower()), roles[0])
        for role in roles:
            if role.id == target.id:
                continue
            _merge_role_links(role.id, target.id)
            db.session.delete(role)

        target.name = canonical_name
        target.is_active = True
        target.is_system = True
        target.is_editable = False
        target.is_deletable = False

    db.session.flush()


def sync_resource_full_name(resource: Resource) -> None:
    resource.full_name = f"{(resource.first_name or '').strip()} {(resource.last_name or '').strip()}".strip()


def validate_resource_payload(
    payload: dict,
    current_resource_id: int | None = None,
    allowed_resource_types: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    resource_type = (payload.get("resource_type") or "").strip().lower()
    email = normalize_email(payload.get("email"))

    if len(first_name) < 2:
        errors.append("Nombre inválido.")
    if len(last_name) < 2:
        errors.append("Apellido inválido.")
    valid_resource_types = set(allowed_resource_types or list(VALID_RESOURCE_TYPES))
    if resource_type not in valid_resource_types:
        errors.append("Tipo de recurso inválido.")
    if email and "@" not in email:
        errors.append("Email inválido.")

    if email:
        stmt = select(Resource.id).where(Resource.email.ilike(email))
        if current_resource_id:
            stmt = stmt.where(Resource.id != current_resource_id)
        if db.session.execute(stmt).scalar_one_or_none():
            errors.append("Ya existe un recurso con ese email.")

    return errors


def _ranges_overlap(start_a: date, end_a: date | None, start_b: date, end_b: date | None) -> bool:
    real_end_a = end_a or date.max
    real_end_b = end_b or date.max
    return start_a <= real_end_b and start_b <= real_end_a


def _has_overlap(existing_rows: list, start: date, end: date | None, current_id: int | None = None) -> bool:
    for row in existing_rows:
        if current_id and row.id == current_id:
            continue
        if _ranges_overlap(start, end, row.valid_from, row.valid_to):
            return True
    return False


def normalize_working_days(raw_value: str | list[str] | tuple[str, ...] | None) -> str:
    if raw_value is None:
        return "mon,tue,wed,thu,fri"
    if isinstance(raw_value, str):
        tokens = [item.strip().lower() for item in raw_value.split(",") if item.strip()]
    else:
        tokens = [str(item).strip().lower() for item in raw_value if str(item).strip()]
    unique_tokens = [item for item in VALID_WEEKDAY_CODES if item in set(tokens)]
    return ",".join(unique_tokens) if unique_tokens else "mon,tue,wed,thu,fri"


def _working_day_count(working_days: str | None) -> int:
    normalized = normalize_working_days(working_days)
    return len([item for item in normalized.split(",") if item in set(VALID_WEEKDAY_CODES)])


def validate_availability_payload(
    resource_id: int,
    payload: dict,
    current_id: int | None = None,
    allowed_availability_types: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []

    availability_type = (payload.get("availability_type") or "").strip().lower()
    weekly_hours = payload.get("weekly_hours")
    daily_hours = payload.get("daily_hours")
    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    working_days = normalize_working_days(payload.get("working_days"))

    valid_availability_types = set(allowed_availability_types or list(VALID_AVAILABILITY_TYPES))
    if availability_type not in valid_availability_types:
        errors.append("Tipo de disponibilidad inválido.")
    if weekly_hours is None and daily_hours is None:
        errors.append("Debes informar horas diarias o semanales.")
    if weekly_hours is not None and Decimal(weekly_hours) <= 0:
        errors.append("Horas semanales deben ser mayores a 0.")
    if daily_hours is not None and Decimal(daily_hours) <= 0:
        errors.append("Horas diarias inválidas.")
    if not valid_from:
        errors.append("Fecha desde es obligatoria.")
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("Rango de fechas inválido.")

    working_count = max(1, _working_day_count(working_days))
    weekly_hours_effective = None
    if weekly_hours is not None:
        weekly_hours_effective = Decimal(weekly_hours)
    elif daily_hours is not None:
        weekly_hours_effective = Decimal(daily_hours) * Decimal(working_count)

    if availability_type == "full_time" and weekly_hours_effective is not None and weekly_hours_effective != Decimal("40"):
        errors.append("Full time debe ser 40 horas semanales.")
    if _working_day_count(working_days) <= 0:
        errors.append("Debes informar al menos un día laborable.")

    if valid_from:
        existing = db.session.execute(
            select(ResourceAvailability).where(
                ResourceAvailability.resource_id == resource_id,
                ResourceAvailability.is_active.is_(True),
            )
        ).scalars().all()
        if _has_overlap(existing, valid_from, valid_to, current_id=current_id):
            errors.append("No puede haber superposición de disponibilidades para el mismo recurso.")

    return errors


def validate_availability_exception_payload(
    resource_id: int,
    payload: dict,
    current_id: int | None = None,
    allowed_exception_types: list[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    exception_type = (payload.get("exception_type") or "").strip().lower()
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    hours_lost = payload.get("hours_lost")

    valid_exception_types = set(allowed_exception_types or list(VALID_EXCEPTION_TYPES))
    if exception_type not in valid_exception_types:
        errors.append("Tipo de excepción inválido.")
    if not start_date:
        errors.append("Fecha desde es obligatoria.")
    if start_date and end_date and start_date > end_date:
        errors.append("Rango de fechas inválido.")
    if hours_lost is not None and Decimal(hours_lost) <= 0:
        errors.append("Horas afectadas deben ser mayores a 0.")

    if start_date:
        existing = db.session.execute(
            select(ResourceAvailabilityException).where(
                ResourceAvailabilityException.resource_id == resource_id,
                ResourceAvailabilityException.is_active.is_(True),
            )
        ).scalars().all()
        for row in existing:
            if current_id and row.id == current_id:
                continue
            if _ranges_overlap(start_date, end_date, row.start_date, row.end_date):
                errors.append("No puede haber superposición de excepciones para el mismo recurso.")
                break

    return errors


def estimate_planned_daily_hours(planned_hours, start_date: date | None, end_date: date | None):
    if planned_hours is None or start_date is None or end_date is None:
        return None
    if end_date < start_date:
        return None
    business_days = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            business_days += 1
        cursor += timedelta(days=1)
    if business_days <= 0:
        return None
    return Decimal(planned_hours) / Decimal(business_days)


def _iter_dates(start_date: date, end_date: date):
    cursor = start_date
    while cursor <= end_date:
        yield cursor
        cursor += timedelta(days=1)


def calculate_resource_net_availability(
    resource_id: int,
    start_date: date,
    end_date: date,
    *,
    owner_user_id: int | None = None,
) -> dict:
    if end_date < start_date:
        raise ValueError("Rango inválido.")

    resource = db.session.get(Resource, resource_id)
    if not resource:
        raise ValueError("Recurso inválido.")

    availabilities = db.session.execute(
        select(ResourceAvailability).where(
            ResourceAvailability.resource_id == resource_id,
            ResourceAvailability.is_active.is_(True),
            ResourceAvailability.valid_from <= end_date,
            or_(ResourceAvailability.valid_to.is_(None), ResourceAvailability.valid_to >= start_date),
        )
    ).scalars().all()
    availabilities_by_day: dict[date, ResourceAvailability] = {}
    for day in _iter_dates(start_date, end_date):
        selected = None
        for row in availabilities:
            if row.valid_from <= day and (row.valid_to is None or row.valid_to >= day):
                if selected is None or row.valid_from > selected.valid_from:
                    selected = row
        if selected:
            availabilities_by_day[day] = selected

    exceptions = db.session.execute(
        select(ResourceAvailabilityException).where(
            ResourceAvailabilityException.resource_id == resource_id,
            ResourceAvailabilityException.is_active.is_(True),
            ResourceAvailabilityException.start_date <= end_date,
            or_(ResourceAvailabilityException.end_date.is_(None), ResourceAvailabilityException.end_date >= start_date),
        )
    ).scalars().all()
    exceptions_by_day: dict[date, list[ResourceAvailabilityException]] = defaultdict(list)
    for row in exceptions:
        row_end = row.end_date or end_date
        overlap_start = max(start_date, row.start_date)
        overlap_end = min(end_date, row_end)
        if overlap_end < overlap_start:
            continue
        for day in _iter_dates(overlap_start, overlap_end):
            exceptions_by_day[day].append(row)

    calendar_holidays_by_day: dict[date, TeamCalendarHolidayConfig] = {}
    if resource.calendar_name:
        holidays_stmt = select(TeamCalendarHolidayConfig).where(
            TeamCalendarHolidayConfig.calendar_name == resource.calendar_name,
            TeamCalendarHolidayConfig.is_active.is_(True),
            TeamCalendarHolidayConfig.holiday_date >= start_date,
            TeamCalendarHolidayConfig.holiday_date <= end_date,
        )
        if owner_user_id is not None:
            holidays_stmt = holidays_stmt.where(TeamCalendarHolidayConfig.owner_user_id == owner_user_id)
        holidays = db.session.execute(holidays_stmt).scalars().all()
        calendar_holidays_by_day = {row.holiday_date: row for row in holidays}

    project_assignments = db.session.execute(
        select(ProjectResource).where(
            ProjectResource.resource_id == resource_id,
            ProjectResource.is_active.is_(True),
            or_(ProjectResource.start_date.is_(None), ProjectResource.start_date <= end_date),
            or_(ProjectResource.end_date.is_(None), ProjectResource.end_date >= start_date),
        )
    ).scalars().all()

    task_assignment_rows = db.session.execute(
        select(TaskResource, Task.start_date, Task.due_date)
        .outerjoin(Task, Task.id == TaskResource.task_id)
        .where(
            TaskResource.resource_id == resource_id,
            TaskResource.is_active.is_(True),
        )
    ).all()

    project_assigned_by_day: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    task_assigned_by_day: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))

    for row in project_assignments:
        row_start = row.start_date or start_date
        row_end = row.end_date or end_date
        overlap_start = max(start_date, row_start)
        overlap_end = min(end_date, row_end)
        if overlap_end < overlap_start:
            continue
        per_day = row.planned_daily_hours or estimate_planned_daily_hours(row.planned_hours, row_start, row_end)
        if per_day is None:
            continue
        per_day_dec = Decimal(per_day)
        for day in _iter_dates(overlap_start, overlap_end):
            project_assigned_by_day[day] += per_day_dec

    for assignment, task_start_date, task_due_date in task_assignment_rows:
        row_start = assignment.start_date or task_start_date or start_date
        row_end = assignment.end_date or task_due_date or end_date
        overlap_start = max(start_date, row_start)
        overlap_end = min(end_date, row_end)
        if overlap_end < overlap_start:
            continue
        per_day = assignment.planned_daily_hours or estimate_planned_daily_hours(assignment.planned_hours, row_start, row_end)
        if per_day is None:
            continue
        per_day_dec = Decimal(per_day)
        for day in _iter_dates(overlap_start, overlap_end):
            task_assigned_by_day[day] += per_day_dec

    days: list[dict] = []
    totals = {
        "base_hours": Decimal("0"),
        "exception_hours": Decimal("0"),
        "assigned_hours": Decimal("0"),
        "net_available_hours": Decimal("0"),
        "overbooked_hours": Decimal("0"),
    }
    weekday_set = set(VALID_WEEKDAY_CODES)

    for day in _iter_dates(start_date, end_date):
        availability = availabilities_by_day.get(day)
        base_hours = Decimal("0")
        is_working_day = False
        if availability:
            working_days = normalize_working_days(availability.working_days).split(",")
            day_code = VALID_WEEKDAY_CODES[day.weekday()]
            is_working_day = day_code in set(working_days) & weekday_set
            if is_working_day:
                if availability.daily_hours is not None:
                    base_hours = Decimal(availability.daily_hours)
                else:
                    working_count = max(1, _working_day_count(availability.working_days))
                    base_hours = Decimal(availability.weekly_hours) / Decimal(working_count)

        is_calendar_holiday = day in calendar_holidays_by_day
        # Feriados de calendario se comportan como días no laborables:
        # la base del día debe ser 0, igual que fines de semana.
        if is_calendar_holiday:
            base_hours = Decimal("0")
            is_working_day = False

        exception_hours = Decimal("0")
        has_full_day_exception = False
        for exception in exceptions_by_day.get(day, []):
            if exception.hours_lost is not None:
                exception_hours += Decimal(exception.hours_lost)
            else:
                has_full_day_exception = True
                exception_hours += base_hours
        if base_hours > 0 and (has_full_day_exception or exception_hours >= base_hours):
            # Si la excepción consume la jornada completa, el día se trata
            # como no laborable para mantener consistencia visual y funcional.
            base_hours = Decimal("0")
            is_working_day = False
            exception_hours = Decimal("0")
        else:
            exception_hours = max(Decimal("0"), min(exception_hours, base_hours))

        # Evita doble conteo cuando hay planificación a nivel proyecto y a nivel tarea.
        # Si ambas existen el mismo día, se usa la mayor demanda.
        assigned_hours = max(
            project_assigned_by_day.get(day, Decimal("0")),
            task_assigned_by_day.get(day, Decimal("0")),
        )
        raw_net = base_hours - exception_hours - assigned_hours
        net_available = max(Decimal("0"), raw_net)
        overbooked = max(Decimal("0"), Decimal("0") - raw_net)

        totals["base_hours"] += base_hours
        totals["exception_hours"] += exception_hours
        totals["assigned_hours"] += assigned_hours
        totals["net_available_hours"] += net_available
        totals["overbooked_hours"] += overbooked

        days.append(
            {
                "date": day.isoformat(),
                "availability_id": availability.id if availability else None,
                "calendar_holiday": bool(is_calendar_holiday),
                "calendar_holiday_label": calendar_holidays_by_day.get(day).label if is_calendar_holiday else None,
                "is_working_day": is_working_day,
                "base_hours": float(base_hours),
                "exception_hours": float(exception_hours),
                "assigned_hours": float(assigned_hours),
                "raw_net_hours": float(raw_net),
                "net_available_hours": float(net_available),
                "overbooked_hours": float(overbooked),
            }
        )

    return {
        "resource_id": resource_id,
        "date_from": start_date.isoformat(),
        "date_to": end_date.isoformat(),
        "totals": {
            "base_hours": float(totals["base_hours"]),
            "exception_hours": float(totals["exception_hours"]),
            "assigned_hours": float(totals["assigned_hours"]),
            "net_available_hours": float(totals["net_available_hours"]),
            "overbooked_hours": float(totals["overbooked_hours"]),
        },
        "days": days,
    }


def validate_cost_payload(resource_id: int, payload: dict, current_id: int | None = None) -> list[str]:
    errors: list[str] = []

    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    hourly_cost = payload.get("hourly_cost")
    monthly_cost = payload.get("monthly_cost")
    cost_type = (payload.get("cost_type") or "").strip().lower()
    currency = (payload.get("currency") or "").strip().upper()

    if not valid_from:
        errors.append("Fecha desde es obligatoria.")
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("Rango de fechas inválido.")
    has_hourly = hourly_cost is not None
    has_monthly = monthly_cost is not None
    if has_hourly == has_monthly:
        errors.append("Debes informar un costo por hora o un costo mensual (uno solo).")
    if has_hourly and Decimal(hourly_cost) <= 0:
        errors.append("Costo por hora debe ser mayor a 0.")
    if has_monthly and Decimal(monthly_cost) <= 0:
        errors.append("Costo mensual debe ser mayor a 0.")
    if cost_type and cost_type not in {"hourly", "monthly"}:
        errors.append("Tipo de costo inválido.")
    if len(currency) < 3:
        errors.append("Moneda inválida.")

    if valid_from:
        existing = db.session.execute(
            select(ResourceCost).where(
                ResourceCost.resource_id == resource_id,
            )
        ).scalars().all()
        invalid_overlap = False
        for row in existing:
            if current_id and row.id == current_id:
                continue
            if not _ranges_overlap(valid_from, valid_to, row.valid_from, row.valid_to):
                continue
            # Se permite solape solo con un costo anterior abierto, porque se cierra automáticamente.
            is_auto_closable_previous = row.valid_from < valid_from and (row.valid_to is None or row.valid_to >= valid_from)
            if not is_auto_closable_previous:
                invalid_overlap = True
                break
        if invalid_overlap:
            errors.append("No puede haber superposición de costos para el mismo recurso.")

    return errors


def close_previous_cost_if_needed(resource_id: int, new_valid_from: date, current_cost_id: int | None = None) -> None:
    previous = db.session.execute(
        select(ResourceCost)
        .where(
            ResourceCost.resource_id == resource_id,
            ResourceCost.id != (current_cost_id or 0),
            ResourceCost.valid_from < new_valid_from,
            or_(ResourceCost.valid_to.is_(None), ResourceCost.valid_to >= new_valid_from),
        )
        .order_by(ResourceCost.valid_from.desc())
    ).scalars().first()

    if previous:
        previous.valid_to = new_valid_from - timedelta(days=1)


def find_applicable_cost_id(resource_id: int, reference_date: date) -> int | None:
    return db.session.execute(
        select(ResourceCost.id)
        .where(
            ResourceCost.resource_id == resource_id,
            ResourceCost.valid_from <= reference_date,
            or_(ResourceCost.valid_to.is_(None), ResourceCost.valid_to >= reference_date),
        )
        .order_by(ResourceCost.valid_from.desc(), ResourceCost.id.desc())
    ).scalar()


def resource_cost_usage_count(cost_id: int) -> int:
    project_count = db.session.execute(
        select(db.func.count()).select_from(ProjectResource).where(ProjectResource.resource_cost_id == cost_id)
    ).scalar_one()
    task_count = db.session.execute(
        select(db.func.count()).select_from(TaskResource).where(TaskResource.resource_cost_id == cost_id)
    ).scalar_one()
    return int(project_count or 0) + int(task_count or 0)


def validate_role_sale_price_payload(role_id: int, payload: dict, current_id: int | None = None) -> list[str]:
    errors: list[str] = []
    role = db.session.get(TeamRole, role_id)
    if not role or not role.is_active:
        errors.append("Rol inválido.")
        return errors

    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    hourly_price = payload.get("hourly_price")
    monthly_price = payload.get("monthly_price")
    currency = (payload.get("currency") or "").strip().upper()

    if not valid_from:
        errors.append("Fecha desde es obligatoria.")
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("Rango de fechas inválido.")
    has_hourly = hourly_price is not None
    has_monthly = monthly_price is not None
    if has_hourly == has_monthly:
        errors.append("Debes informar precio por hora o por mes (uno solo).")
    if has_hourly and Decimal(hourly_price) <= 0:
        errors.append("Precio por hora debe ser mayor a 0.")
    if has_monthly and Decimal(monthly_price) <= 0:
        errors.append("Precio mensual debe ser mayor a 0.")
    if len(currency) < 3:
        errors.append("Moneda inválida.")

    if valid_from:
        existing = db.session.execute(select(RoleSalePrice).where(RoleSalePrice.role_id == role_id)).scalars().all()
        invalid_overlap = False
        for row in existing:
            if current_id and row.id == current_id:
                continue
            if _ranges_overlap(valid_from, valid_to, row.valid_from, row.valid_to):
                invalid_overlap = True
                break
        if invalid_overlap:
            errors.append("No puede haber superposición de vigencias para el mismo rol.")

    return errors


def close_previous_role_sale_price_if_needed(role_id: int, new_valid_from: date, current_id: int | None = None):
    previous = db.session.execute(
        select(RoleSalePrice)
        .where(
            RoleSalePrice.role_id == role_id,
            RoleSalePrice.id != (current_id or 0),
            RoleSalePrice.valid_from < new_valid_from,
            or_(RoleSalePrice.valid_to.is_(None), RoleSalePrice.valid_to >= new_valid_from),
        )
        .order_by(RoleSalePrice.valid_from.desc(), RoleSalePrice.id.desc())
    ).scalar_one_or_none()
    if previous:
        previous.valid_to = new_valid_from - timedelta(days=1)


def find_applicable_role_sale_price_id(role_id: int, reference_date: date) -> int | None:
    return db.session.execute(
        select(RoleSalePrice.id)
        .where(
            RoleSalePrice.role_id == role_id,
            RoleSalePrice.valid_from <= reference_date,
            or_(RoleSalePrice.valid_to.is_(None), RoleSalePrice.valid_to >= reference_date),
        )
        .order_by(RoleSalePrice.valid_from.desc(), RoleSalePrice.id.desc())
    ).scalar()


def validate_assignment(resource_id: int, role_id: int | None) -> list[str]:
    errors: list[str] = []
    resource = db.session.get(Resource, resource_id)
    if not resource or not resource.is_active:
        errors.append("No se puede asignar un recurso inexistente o inactivo.")

    if role_id:
        role = db.session.get(TeamRole, role_id)
        if not role or not role.is_active:
            errors.append("No se puede asignar un rol inexistente o inactivo.")

    return errors


def validate_task_assignment_project_consistency(task_id: int, resource_id: int) -> list[str]:
    task = db.session.get(Task, task_id)
    if not task:
        return ["La tarea no existe."]

    exists = db.session.execute(
        select(ProjectResource.id).where(
            ProjectResource.project_id == task.project_id,
            ProjectResource.resource_id == resource_id,
            ProjectResource.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if not exists:
        return ["El recurso debe estar asignado al proyecto antes de asignarlo a la tarea."]

    return []
