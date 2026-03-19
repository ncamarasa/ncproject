"""add role sale prices for project margin

Revision ID: b1c2d3e4f5a6
Revises: a7b3c1d9e2f4
Create Date: 2026-03-19 14:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b1c2d3e4f5a6"
down_revision = "a7b3c1d9e2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role_sale_price",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("hourly_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("monthly_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "((hourly_price IS NOT NULL AND hourly_price > 0 AND monthly_price IS NULL) OR "
            "(monthly_price IS NOT NULL AND monthly_price > 0 AND hourly_price IS NULL))",
            name="ck_role_sale_price_amount_xor_positive",
        ),
    )
    op.create_index(op.f("ix_role_sale_price_role_id"), "role_sale_price", ["role_id"], unique=False)
    op.create_index(op.f("ix_role_sale_price_valid_from"), "role_sale_price", ["valid_from"], unique=False)
    op.create_index(op.f("ix_role_sale_price_valid_to"), "role_sale_price", ["valid_to"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_role_sale_price_valid_to"), table_name="role_sale_price")
    op.drop_index(op.f("ix_role_sale_price_valid_from"), table_name="role_sale_price")
    op.drop_index(op.f("ix_role_sale_price_role_id"), table_name="role_sale_price")
    op.drop_table("role_sale_price")

