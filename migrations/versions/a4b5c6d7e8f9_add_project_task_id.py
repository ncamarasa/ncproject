"""add project task id

Revision ID: a4b5c6d7e8f9
Revises: f2b3c4d5e6f7
Create Date: 2026-03-19 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_task_id", sa.Integer(), nullable=True))

    tasks = sa.table(
        "tasks",
        sa.column("id", sa.Integer()),
        sa.column("project_id", sa.Integer()),
        sa.column("project_task_id", sa.Integer()),
    )

    rows = bind.execute(
        sa.select(tasks.c.id, tasks.c.project_id).order_by(tasks.c.project_id.asc(), tasks.c.id.asc())
    ).fetchall()

    counters: dict[int, int] = {}
    for task_id, project_id in rows:
        counters[project_id] = counters.get(project_id, 0) + 1
        bind.execute(
            tasks.update().where(tasks.c.id == task_id).values(project_task_id=counters[project_id])
        )

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.alter_column("project_task_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_unique_constraint("uq_tasks_project_task_id", ["project_id", "project_task_id"])


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint("uq_tasks_project_task_id", type_="unique")
        batch_op.drop_column("project_task_id")
