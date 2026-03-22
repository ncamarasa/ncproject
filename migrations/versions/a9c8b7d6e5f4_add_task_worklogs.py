"""add task worklogs

Revision ID: a9c8b7d6e5f4
Revises: f2b3c4d5e6f7
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a9c8b7d6e5f4"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_worklogs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("progress_percent_after", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_worklogs_task_id", "task_worklogs", ["task_id"], unique=False)
    op.create_index("ix_task_worklogs_resource_id", "task_worklogs", ["resource_id"], unique=False)
    op.create_index("ix_task_worklogs_user_id", "task_worklogs", ["user_id"], unique=False)
    op.create_index("ix_task_worklogs_work_date", "task_worklogs", ["work_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_worklogs_work_date", table_name="task_worklogs")
    op.drop_index("ix_task_worklogs_user_id", table_name="task_worklogs")
    op.drop_index("ix_task_worklogs_resource_id", table_name="task_worklogs")
    op.drop_index("ix_task_worklogs_task_id", table_name="task_worklogs")
    op.drop_table("task_worklogs")
