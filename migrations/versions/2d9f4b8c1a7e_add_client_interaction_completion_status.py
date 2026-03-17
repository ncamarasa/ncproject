"""add client interaction completion status

Revision ID: 2d9f4b8c1a7e
Revises: 1c7e9b2a4d6f
Create Date: 2026-03-17 11:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d9f4b8c1a7e"
down_revision = "1c7e9b2a4d6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("client_interactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("client_interactions", schema=None) as batch_op:
        batch_op.alter_column("is_completed", server_default=None)


def downgrade():
    with op.batch_alter_table("client_interactions", schema=None) as batch_op:
        batch_op.drop_column("is_completed")
