"""resource cost hourly or monthly xor

Revision ID: 4f6a8c1d2e3b
Revises: 3a5d7c9e2f10
Create Date: 2026-03-18 22:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4f6a8c1d2e3b"
down_revision = "3a5d7c9e2f10"
branch_labels = None
depends_on = None


def _check_constraint_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {item.get("name") for item in inspector.get_check_constraints(table_name) if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    check_names = _check_constraint_names(bind, "resource_cost")

    with op.batch_alter_table("resource_cost", schema=None) as batch_op:
        batch_op.alter_column("hourly_cost", existing_type=sa.Numeric(12, 2), nullable=True)
        if "ck_resource_cost_hourly_positive" in check_names:
            batch_op.drop_constraint("ck_resource_cost_hourly_positive", type_="check")
        if "ck_resource_cost_monthly_non_negative" in check_names:
            batch_op.drop_constraint("ck_resource_cost_monthly_non_negative", type_="check")
        batch_op.create_check_constraint(
            "ck_resource_cost_amount_xor_positive",
            "((hourly_cost IS NOT NULL AND hourly_cost > 0 AND monthly_cost IS NULL) OR "
            "(monthly_cost IS NOT NULL AND monthly_cost > 0 AND hourly_cost IS NULL))",
        )


def downgrade() -> None:
    bind = op.get_bind()
    check_names = _check_constraint_names(bind, "resource_cost")

    bind.execute(
        sa.text(
            "UPDATE resource_cost "
            "SET hourly_cost = COALESCE(hourly_cost, monthly_cost) "
            "WHERE hourly_cost IS NULL"
        )
    )

    with op.batch_alter_table("resource_cost", schema=None) as batch_op:
        if "ck_resource_cost_amount_xor_positive" in check_names:
            batch_op.drop_constraint("ck_resource_cost_amount_xor_positive", type_="check")
        batch_op.create_check_constraint("ck_resource_cost_hourly_positive", "hourly_cost > 0")
        batch_op.create_check_constraint(
            "ck_resource_cost_monthly_non_negative",
            "monthly_cost IS NULL OR monthly_cost >= 0",
        )
        batch_op.alter_column("hourly_cost", existing_type=sa.Numeric(12, 2), nullable=False)
