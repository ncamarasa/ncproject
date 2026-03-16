from datetime import UTC, datetime

from project_manager.extensions import db


def _utcnow_naive() -> datetime:
    # Guardamos UTC naive para mantener compatibilidad con columnas DateTime actuales.
    return datetime.now(UTC).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(
        db.DateTime,
        default=_utcnow_naive,
        server_default=db.func.now(),
        nullable=False,
    )
    updated_at = db.Column(
        db.DateTime,
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
        server_default=db.func.now(),
        nullable=False,
    )
