"""add contract service type default rate and contracted hours

Revision ID: c4d7e8f9a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-03-19 21:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d7e8f9a1b2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_contracts", sa.Column("service_type", sa.String(length=80), nullable=True))
    op.add_column("client_contracts", sa.Column("default_rate", sa.Numeric(10, 2), nullable=True))
    op.add_column("client_contracts", sa.Column("contracted_hours", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("client_contracts", "contracted_hours")
    op.drop_column("client_contracts", "default_rate")
    op.drop_column("client_contracts", "service_type")

