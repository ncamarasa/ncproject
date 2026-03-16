"""add client_code auto pattern

Revision ID: 91b7d2c4e6f1
Revises: 7c3e1f4a9b2d
Create Date: 2026-03-16 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "91b7d2c4e6f1"
down_revision = "7c3e1f4a9b2d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("client_code", sa.String(length=40), nullable=True))
        batch_op.create_index(batch_op.f("ix_clients_client_code"), ["client_code"], unique=True)


def downgrade():
    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clients_client_code"))
        batch_op.drop_column("client_code")

