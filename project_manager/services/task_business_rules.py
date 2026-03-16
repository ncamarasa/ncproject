from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import g, has_request_context
from sqlalchemy import select

from project_manager.extensions import db
from project_manager.models import AuditTrailLog, Task

CLOSED_STATUSES = {"completada", "cerrada", "closed", "done", "finalizada"}


def _normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def is_closed_status(value: str | None) -> bool:
    return _normalize_status(value) in CLOSED_STATUSES


def _actor_user_id() -> int | None:
    if has_request_context() and getattr(g, "user", None):
        return g.user.id
    return None


def task_has_subtasks(task_id: int | None) -> bool:
    if not task_id:
        return False
    exists = db.session.execute(select(Task.id).where(Task.parent_task_id == task_id).limit(1)).scalar_one_or_none()
    return exists is not None


def has_open_subtasks(task_id: int | None) -> bool:
    if not task_id:
        return False
    subtasks = db.session.execute(select(Task).where(Task.parent_task_id == task_id)).scalars().all()
    return any(not is_closed_status(t.status) for t in subtasks)


def _has_ancestor(task: Task | None, ancestor_id: int) -> bool:
    cursor = task
    while cursor and cursor.parent_task_id:
        if cursor.parent_task_id == ancestor_id:
            return True
        cursor = db.session.get(Task, cursor.parent_task_id)
    return False


def validate_parent_assignment(project_id: int, parent_task_id: int | None, current_task_id: int | None) -> list[str]:
    errors: list[str] = []
    if not parent_task_id:
        return errors

    parent = db.session.get(Task, parent_task_id)
    if not parent or parent.project_id != project_id:
        errors.append("La tarea padre no pertenece al proyecto.")
        return errors

    if parent.parent_task_id is not None:
        errors.append("Máximo 2 niveles permitidos: no se puede asignar una subtarea como tarea padre.")

    if current_task_id:
        if parent_task_id == current_task_id:
            errors.append("Una tarea no puede ser padre de sí misma.")
        current = db.session.get(Task, current_task_id)
        if current and task_has_subtasks(current.id):
            errors.append("Una tarea con subtareas no puede convertirse en subtarea (máximo 2 niveles).")
        if _has_ancestor(parent, current_task_id):
            errors.append("No se permite circularidad en la jerarquía de tareas.")

    return errors


def calculate_parent_rollup(subtasks: list[Task]) -> dict:
    if not subtasks:
        return {"start_date": None, "due_date": None, "progress_percent": 0}

    start_candidates = [t.start_date for t in subtasks if t.start_date is not None]
    due_candidates = [t.due_date for t in subtasks if t.due_date is not None]
    start_date = min(start_candidates) if start_candidates else None
    due_date = max(due_candidates) if due_candidates else None

    all_with_hours = all(t.estimated_hours is not None for t in subtasks)
    if all_with_hours:
        total_hours = sum(Decimal(t.estimated_hours) for t in subtasks if Decimal(t.estimated_hours) > 0)
    else:
        total_hours = Decimal("0")

    if all_with_hours and total_hours > 0:
        weighted = sum(
            Decimal(t.progress_percent or 0) * Decimal(t.estimated_hours)
            for t in subtasks
            if Decimal(t.estimated_hours) > 0
        )
        progress = int(round(float(weighted / total_hours)))
    else:
        progress = int(round(sum((t.progress_percent or 0) for t in subtasks) / len(subtasks)))

    return {
        "start_date": start_date,
        "due_date": due_date,
        "progress_percent": max(0, min(progress, 100)),
    }


def _insert_auto_recalc_audit(parent_task: Task, old_values: dict, new_values: dict, reason: str, trigger_task_id: int | None):
    db.session.add(
        AuditTrailLog(
            table_name=Task.__tablename__,
            record_id=str(parent_task.id),
            action="auto_recalc",
            user_id=_actor_user_id(),
            old_values={
                **old_values,
                "reason": reason,
                "trigger_task_id": trigger_task_id,
            },
            new_values={
                **new_values,
                "reason": reason,
                "trigger_task_id": trigger_task_id,
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )


def recalculate_parent_task(parent_task_id: int | None, *, reason: str, trigger_task_id: int | None = None) -> bool:
    if not parent_task_id:
        return False
    parent = db.session.get(Task, parent_task_id)
    if not parent:
        return False

    subtasks = db.session.execute(select(Task).where(Task.parent_task_id == parent.id)).scalars().all()
    rollup = calculate_parent_rollup(subtasks)
    old_values = {
        "start_date": parent.start_date.isoformat() if parent.start_date else None,
        "due_date": parent.due_date.isoformat() if parent.due_date else None,
        "progress_percent": parent.progress_percent,
    }
    new_values = {
        "start_date": rollup["start_date"].isoformat() if rollup["start_date"] else None,
        "due_date": rollup["due_date"].isoformat() if rollup["due_date"] else None,
        "progress_percent": rollup["progress_percent"],
    }
    # Auditar todo intento de recálculo para trazabilidad completa (incluyendo no-op).
    if old_values == new_values:
        _insert_auto_recalc_audit(parent, old_values, new_values, f"{reason}_noop", trigger_task_id)
        return False

    parent.start_date = rollup["start_date"]
    parent.due_date = rollup["due_date"]
    parent.progress_percent = rollup["progress_percent"]
    parent.rollup_updated_at = datetime.utcnow()

    _insert_auto_recalc_audit(parent, old_values, new_values, reason, trigger_task_id)
    return True
