"""add cost reference to resource assignments

Revision ID: 6b9d2f4a1c8e
Revises: 4f6a8c1d2e3b
Create Date: 2026-03-18 23:05:00.000000
"""

from __future__ import annotations

from datetime import date

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b9d2f4a1c8e"
down_revision = "4f6a8c1d2e3b"
branch_labels = None
depends_on = None


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    # SQLite puede devolver DATE/DATETIME como texto en consultas raw.
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def _best_cost_id(bind, resource_id: int, reference_date: date) -> int | None:
    return bind.execute(
        sa.text(
            """
            SELECT id
            FROM resource_cost
            WHERE resource_id = :resource_id
              AND valid_from <= :reference_date
              AND (valid_to IS NULL OR valid_to >= :reference_date)
            ORDER BY valid_from DESC, id DESC
            LIMIT 1
            """
        ),
        {"resource_id": resource_id, "reference_date": reference_date},
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    # Limpieza defensiva por corridas fallidas previas de batch_alter_table en SQLite.
    bind.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_project_resource"))
    bind.execute(sa.text("DROP TABLE IF EXISTS _alembic_tmp_task_resource"))

    with op.batch_alter_table("project_resource", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resource_cost_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_project_resource_resource_cost_id"), ["resource_cost_id"], unique=False)
        batch_op.create_foreign_key("fk_project_resource_resource_cost", "resource_cost", ["resource_cost_id"], ["id"])

    with op.batch_alter_table("task_resource", schema=None) as batch_op:
        batch_op.add_column(sa.Column("resource_cost_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_task_resource_resource_cost_id"), ["resource_cost_id"], unique=False)
        batch_op.create_foreign_key("fk_task_resource_resource_cost", "resource_cost", ["resource_cost_id"], ["id"])

    project_rows = bind.execute(
        sa.text(
            """
            SELECT id, resource_id, start_date, created_at
            FROM project_resource
            WHERE resource_cost_id IS NULL
            """
        )
    ).fetchall()
    for row in project_rows:
        reference_date = _as_date(row.start_date) or _as_date(row.created_at) or date.today()
        cost_id = _best_cost_id(bind, row.resource_id, reference_date)
        if cost_id:
            bind.execute(
                sa.text("UPDATE project_resource SET resource_cost_id = :cost_id WHERE id = :id"),
                {"cost_id": cost_id, "id": row.id},
            )

    task_rows = bind.execute(
        sa.text(
            """
            SELECT tr.id, tr.resource_id, tr.start_date, tr.created_at, t.start_date AS task_start_date
            FROM task_resource tr
            LEFT JOIN tasks t ON t.id = tr.task_id
            WHERE tr.resource_cost_id IS NULL
            """
        )
    ).fetchall()
    for row in task_rows:
        reference_date = _as_date(row.start_date) or _as_date(row.task_start_date) or _as_date(row.created_at) or date.today()
        cost_id = _best_cost_id(bind, row.resource_id, reference_date)
        if cost_id:
            bind.execute(
                sa.text("UPDATE task_resource SET resource_cost_id = :cost_id WHERE id = :id"),
                {"cost_id": cost_id, "id": row.id},
            )


def downgrade() -> None:
    with op.batch_alter_table("task_resource", schema=None) as batch_op:
        batch_op.drop_constraint("fk_task_resource_resource_cost", type_="foreignkey")
        batch_op.drop_index(op.f("ix_task_resource_resource_cost_id"))
        batch_op.drop_column("resource_cost_id")

    with op.batch_alter_table("project_resource", schema=None) as batch_op:
        batch_op.drop_constraint("fk_project_resource_resource_cost", type_="foreignkey")
        batch_op.drop_index(op.f("ix_project_resource_resource_cost_id"))
        batch_op.drop_column("resource_cost_id")
