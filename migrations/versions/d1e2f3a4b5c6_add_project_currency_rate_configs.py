"""add project currency rate configs

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1e2f3a4b5c6"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_currency_rate_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("from_currency", sa.String(length=10), nullable=False),
        sa.Column("to_currency", sa.String(length=10), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("rate", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "from_currency",
            "to_currency",
            "valid_from",
            name="uq_project_currency_rate_owner_pair_from",
        ),
    )
    op.create_index("ix_project_currency_rate_configs_owner_user_id", "project_currency_rate_configs", ["owner_user_id"], unique=False)
    op.create_index("ix_project_currency_rate_configs_from_currency", "project_currency_rate_configs", ["from_currency"], unique=False)
    op.create_index("ix_project_currency_rate_configs_to_currency", "project_currency_rate_configs", ["to_currency"], unique=False)
    op.create_index("ix_project_currency_rate_configs_valid_from", "project_currency_rate_configs", ["valid_from"], unique=False)
    op.create_index("ix_project_currency_rate_configs_valid_to", "project_currency_rate_configs", ["valid_to"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_project_currency_rate_configs_valid_to", table_name="project_currency_rate_configs")
    op.drop_index("ix_project_currency_rate_configs_valid_from", table_name="project_currency_rate_configs")
    op.drop_index("ix_project_currency_rate_configs_to_currency", table_name="project_currency_rate_configs")
    op.drop_index("ix_project_currency_rate_configs_from_currency", table_name="project_currency_rate_configs")
    op.drop_index("ix_project_currency_rate_configs_owner_user_id", table_name="project_currency_rate_configs")
    op.drop_table("project_currency_rate_configs")
