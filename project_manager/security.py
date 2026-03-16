from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from flask import g, has_request_context
from sqlalchemy import event, inspect

from project_manager.extensions import db
from project_manager.models import (
    AuditTrailLog,
    Client,
    ClientCatalogOptionConfig,
    ClientContract,
    CompanyTypeConfig,
    PaymentTypeConfig,
    Resource,
    ResourceAvailability,
    ResourceCost,
    ResourceRole,
    Project,
    Role,
    SystemCatalogOptionConfig,
    Task,
    TeamRole,
    ClientResource,
    ProjectResource,
    TaskResource,
    User,
)

REDACTED_FIELDS = {"password_hash"}
AUDITED_MODELS = [
    User,
    Role,
    Client,
    ClientContract,
    Project,
    Task,
    CompanyTypeConfig,
    PaymentTypeConfig,
    ClientCatalogOptionConfig,
    SystemCatalogOptionConfig,
    Resource,
    TeamRole,
    ResourceRole,
    ResourceAvailability,
    ResourceCost,
    ClientResource,
    ProjectResource,
    TaskResource,
]


_LISTENERS_REGISTERED = False


def _actor_user_id() -> int | None:
    if has_request_context() and getattr(g, "user", None):
        return g.user.id
    return None


def _serialize_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _full_values(target) -> dict:
    values = {}
    for col in target.__table__.columns:
        key = col.key
        if key in REDACTED_FIELDS:
            values[key] = "***"
        else:
            values[key] = _serialize_value(getattr(target, key, None))
    return values


def _changed_values(target) -> tuple[dict, dict]:
    state = inspect(target)
    old_values = {}
    new_values = {}
    for attr in state.attrs:
        key = attr.key
        if key in REDACTED_FIELDS:
            if attr.history.has_changes():
                old_values[key] = "***"
                new_values[key] = "***"
            continue
        if not attr.history.has_changes():
            continue
        if attr.history.deleted:
            old_values[key] = _serialize_value(attr.history.deleted[0])
        else:
            old_values[key] = None
        if attr.history.added:
            new_values[key] = _serialize_value(attr.history.added[0])
        else:
            new_values[key] = _serialize_value(getattr(target, key, None))
    return old_values, new_values


def _insert_audit(connection, target, action: str, old_values=None, new_values=None):
    pk = getattr(target, "id", None)
    connection.execute(
        AuditTrailLog.__table__.insert().values(
            table_name=target.__tablename__,
            record_id=str(pk) if pk is not None else "-",
            action=action,
            user_id=_actor_user_id(),
            old_values=old_values,
            new_values=new_values,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )


def _after_insert(mapper, connection, target):
    _insert_audit(connection, target, "insert", old_values=None, new_values=_full_values(target))


def _after_update(mapper, connection, target):
    old_values, new_values = _changed_values(target)
    if old_values or new_values:
        _insert_audit(connection, target, "update", old_values=old_values, new_values=new_values)


def _after_delete(mapper, connection, target):
    _insert_audit(connection, target, "delete", old_values=_full_values(target), new_values=None)


def register_audit_listeners() -> None:
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return

    for model in AUDITED_MODELS:
        event.listen(model, "after_insert", _after_insert)
        event.listen(model, "after_update", _after_update)
        event.listen(model, "after_delete", _after_delete)

    _LISTENERS_REGISTERED = True
