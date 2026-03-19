"""expand availability for auto scheduling

Revision ID: 8a4c2e1f9b7d
Revises: 6b9d2f4a1c8e
Create Date: 2026-03-18 23:55:00.000000
"""

from __future__ import annotations

from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8a4c2e1f9b7d"
down_revision = "6b9d2f4a1c8e"
branch_labels = None
depends_on = None


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def _estimate_daily(planned_hours, start_date: date | None, end_date: date | None):
    if planned_hours is None or start_date is None or end_date is None or end_date < start_date:
        return None
    business_days = 0
    cursor = start_date
    while cursor <= end_date:
        if cursor.weekday() < 5:
            business_days += 1
        cursor += timedelta(days=1)
    if business_days <= 0:
        return None
    return float(planned_hours) / float(business_days)


def upgrade() -> None:
    with op.batch_alter_table("resource_availability", schema=None) as batch_op:
        batch_op.add_column(sa.Column("working_days", sa.String(length=40), nullable=False, server_default="mon,tue,wed,thu,fri"))
        batch_op.add_column(sa.Column("timezone", sa.String(length=60), nullable=True))

    op.create_table(
        "resource_availability_exception",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("exception_type", sa.String(length=30), nullable=False, server_default="time_off"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("hours_lost", sa.Numeric(8, 2), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_resource_availability_exception_date_range"),
        sa.CheckConstraint("hours_lost IS NULL OR hours_lost > 0", name="ck_resource_availability_exception_hours"),
    )
    op.create_index(op.f("ix_resource_availability_exception_resource_id"), "resource_availability_exception", ["resource_id"], unique=False)
    op.create_index(op.f("ix_resource_availability_exception_start_date"), "resource_availability_exception", ["start_date"], unique=False)
    op.create_index(op.f("ix_resource_availability_exception_end_date"), "resource_availability_exception", ["end_date"], unique=False)

    with op.batch_alter_table("project_resource", schema=None) as batch_op:
        batch_op.add_column(sa.Column("planned_daily_hours", sa.Numeric(8, 2), nullable=True))

    with op.batch_alter_table("task_resource", schema=None) as batch_op:
        batch_op.add_column(sa.Column("planned_daily_hours", sa.Numeric(8, 2), nullable=True))

    bind = op.get_bind()

    project_rows = bind.execute(
        sa.text(
            """
            SELECT id, planned_hours, start_date, end_date
            FROM project_resource
            WHERE planned_daily_hours IS NULL
            """
        )
    ).fetchall()
    for row in project_rows:
        daily = _estimate_daily(row.planned_hours, _as_date(row.start_date), _as_date(row.end_date))
        if daily is not None:
            bind.execute(
                sa.text("UPDATE project_resource SET planned_daily_hours = :daily WHERE id = :id"),
                {"daily": daily, "id": row.id},
            )

    task_rows = bind.execute(
        sa.text(
            """
            SELECT tr.id, tr.planned_hours, tr.start_date, tr.end_date, t.start_date AS task_start_date, t.due_date AS task_due_date
            FROM task_resource tr
            LEFT JOIN tasks t ON t.id = tr.task_id
            WHERE tr.planned_daily_hours IS NULL
            """
        )
    ).fetchall()
    for row in task_rows:
        start_date = _as_date(row.start_date) or _as_date(row.task_start_date)
        end_date = _as_date(row.end_date) or _as_date(row.task_due_date)
        daily = _estimate_daily(row.planned_hours, start_date, end_date)
        if daily is not None:
            bind.execute(
                sa.text("UPDATE task_resource SET planned_daily_hours = :daily WHERE id = :id"),
                {"daily": daily, "id": row.id},
            )


def downgrade() -> None:
    with op.batch_alter_table("task_resource", schema=None) as batch_op:
        batch_op.drop_column("planned_daily_hours")

    with op.batch_alter_table("project_resource", schema=None) as batch_op:
        batch_op.drop_column("planned_daily_hours")

    op.drop_index(op.f("ix_resource_availability_exception_end_date"), table_name="resource_availability_exception")
    op.drop_index(op.f("ix_resource_availability_exception_start_date"), table_name="resource_availability_exception")
    op.drop_index(op.f("ix_resource_availability_exception_resource_id"), table_name="resource_availability_exception")
    op.drop_table("resource_availability_exception")

    with op.batch_alter_table("resource_availability", schema=None) as batch_op:
        batch_op.drop_column("timezone")
        batch_op.drop_column("working_days")
