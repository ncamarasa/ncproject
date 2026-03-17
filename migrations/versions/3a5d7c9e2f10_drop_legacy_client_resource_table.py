"""drop legacy client_resource table

Revision ID: 3a5d7c9e2f10
Revises: 2d9f4b8c1a7e
Create Date: 2026-03-16 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3a5d7c9e2f10"
down_revision = "2d9f4b8c1a7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "client_resource" in inspector.get_table_names():
        op.drop_table("client_resource")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "client_resource" in inspector.get_table_names():
        return

    op.create_table(
        "client_resource",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allocation_percent", sa.Numeric(6, 2), nullable=True),
        sa.Column("planned_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "allocation_percent IS NULL OR (allocation_percent >= 0 AND allocation_percent <= 100)",
            name="ck_client_resource_allocation",
        ),
        sa.CheckConstraint("planned_hours IS NULL OR planned_hours >= 0", name="ck_client_resource_planned_hours"),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_client_resource_date_range",
        ),
    )
    op.create_index(op.f("ix_client_resource_client_id"), "client_resource", ["client_id"], unique=False)
    op.create_index(op.f("ix_client_resource_resource_id"), "client_resource", ["resource_id"], unique=False)
    op.create_index(op.f("ix_client_resource_role_id"), "client_resource", ["role_id"], unique=False)
