"""add user timestamp columns

Revision ID: 0d9e6c7b1f23
Revises: f1c2d3e4a5b6
Create Date: 2026-03-15 00:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '0d9e6c7b1f23'
down_revision = 'f1c2d3e4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False)
        )
        batch_op.add_column(
            sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('updated_at')
        batch_op.drop_column('created_at')
