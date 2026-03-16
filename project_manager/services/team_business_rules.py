from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import or_, select

from project_manager.extensions import db
from project_manager.models import (
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceCost,
    Task,
    TeamRole,
)


VALID_RESOURCE_TYPES = {"internal", "external"}
VALID_AVAILABILITY_TYPES = {"full_time", "part_time", "custom"}


def normalize_email(value: str | None) -> str | None:
    v = (value or "").strip().lower()
    return v or None


def sync_resource_full_name(resource: Resource) -> None:
    resource.full_name = f"{(resource.first_name or '').strip()} {(resource.last_name or '').strip()}".strip()


def validate_resource_payload(payload: dict, current_resource_id: int | None = None) -> list[str]:
    errors: list[str] = []
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    resource_type = (payload.get("resource_type") or "").strip().lower()
    email = normalize_email(payload.get("email"))

    if len(first_name) < 2:
        errors.append("Nombre inválido.")
    if len(last_name) < 2:
        errors.append("Apellido inválido.")
    if resource_type not in VALID_RESOURCE_TYPES:
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


def validate_availability_payload(resource_id: int, payload: dict, current_id: int | None = None) -> list[str]:
    errors: list[str] = []

    availability_type = (payload.get("availability_type") or "").strip().lower()
    weekly_hours = payload.get("weekly_hours")
    daily_hours = payload.get("daily_hours")
    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")

    if availability_type not in VALID_AVAILABILITY_TYPES:
        errors.append("Tipo de disponibilidad inválido.")
    if weekly_hours is None or Decimal(weekly_hours) <= 0:
        errors.append("Horas semanales deben ser mayores a 0.")
    if daily_hours is not None and Decimal(daily_hours) <= 0:
        errors.append("Horas diarias inválidas.")
    if not valid_from:
        errors.append("Fecha desde es obligatoria.")
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("Rango de fechas inválido.")

    if availability_type == "full_time" and weekly_hours is not None and Decimal(weekly_hours) != Decimal("40"):
        errors.append("Full time debe ser 40 horas semanales.")

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


def validate_cost_payload(resource_id: int, payload: dict, current_id: int | None = None) -> list[str]:
    errors: list[str] = []

    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")
    hourly_cost = payload.get("hourly_cost")
    monthly_cost = payload.get("monthly_cost")
    currency = (payload.get("currency") or "").strip().upper()

    if not valid_from:
        errors.append("Fecha desde es obligatoria.")
    if valid_from and valid_to and valid_from > valid_to:
        errors.append("Rango de fechas inválido.")
    if hourly_cost is None or Decimal(hourly_cost) <= 0:
        errors.append("Costo por hora debe ser mayor a 0.")
    if monthly_cost is not None and Decimal(monthly_cost) < 0:
        errors.append("Costo mensual inválido.")
    if len(currency) < 3:
        errors.append("Moneda inválida.")

    if valid_from:
        existing = db.session.execute(
            select(ResourceCost).where(
                ResourceCost.resource_id == resource_id,
                ResourceCost.is_active.is_(True),
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
            ResourceCost.is_active.is_(True),
            ResourceCost.id != (current_cost_id or 0),
            ResourceCost.valid_from < new_valid_from,
            or_(ResourceCost.valid_to.is_(None), ResourceCost.valid_to >= new_valid_from),
        )
        .order_by(ResourceCost.valid_from.desc())
    ).scalars().first()

    if previous:
        previous.valid_to = new_valid_from - timedelta(days=1)


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
