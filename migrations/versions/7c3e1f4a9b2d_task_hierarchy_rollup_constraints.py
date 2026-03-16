"""task hierarchy rollup constraints

Revision ID: 7c3e1f4a9b2d
Revises: 0d9e6c7b1f23
Create Date: 2026-03-15 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7c3e1f4a9b2d"
down_revision = "0d9e6c7b1f23"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rollup_updated_at", sa.DateTime(), nullable=True))
        batch_op.create_check_constraint(
            "ck_tasks_progress_percent_range",
            "(progress_percent IS NULL) OR (progress_percent >= 0 AND progress_percent <= 100)",
        )
        batch_op.create_check_constraint(
            "ck_tasks_estimated_hours_non_negative",
            "(estimated_hours IS NULL) OR (estimated_hours >= 0)",
        )
        batch_op.create_check_constraint(
            "ck_tasks_logged_hours_non_negative",
            "(logged_hours IS NULL) OR (logged_hours >= 0)",
        )
        batch_op.create_check_constraint(
            "ck_tasks_estimated_duration_positive",
            "(estimated_duration_days IS NULL) OR (estimated_duration_days > 0)",
        )


def downgrade():
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint("ck_tasks_estimated_duration_positive", type_="check")
        batch_op.drop_constraint("ck_tasks_logged_hours_non_negative", type_="check")
        batch_op.drop_constraint("ck_tasks_estimated_hours_non_negative", type_="check")
        batch_op.drop_constraint("ck_tasks_progress_percent_range", type_="check")
        batch_op.drop_column("rollup_updated_at")

