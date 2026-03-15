"""add settings catalogs per user

Revision ID: a11f0e4d2b8c
Revises: 9f2c4b7e1a21
Create Date: 2026-03-14 20:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a11f0e4d2b8c'
down_revision = '9f2c4b7e1a21'
branch_labels = None
depends_on = None


DEFAULT_COMPANY_TYPES = ["Empresa", "Gobierno", "ONG", "Startup", "Otro"]
DEFAULT_PAYMENT_TYPES = ["Contado", "15 días", "30 días", "45 días", "60 días"]


def upgrade():
    op.create_table(
        'company_type_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_user_id', 'name', name='uq_company_type_configs_owner_name'),
    )
    op.create_index('ix_company_type_configs_owner_user_id', 'company_type_configs', ['owner_user_id'], unique=False)

    op.create_table(
        'payment_type_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_user_id', 'name', name='uq_payment_type_configs_owner_name'),
    )
    op.create_index('ix_payment_type_configs_owner_user_id', 'payment_type_configs', ['owner_user_id'], unique=False)

    connection = op.get_bind()
    user_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM users"))]

    for user_id in user_ids:
        for item in DEFAULT_COMPANY_TYPES:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO company_type_configs (owner_user_id, name, is_active)
                    VALUES (:owner_user_id, :name, 1)
                    """
                ),
                {"owner_user_id": user_id, "name": item},
            )
        for item in DEFAULT_PAYMENT_TYPES:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO payment_type_configs (owner_user_id, name, is_active)
                    VALUES (:owner_user_id, :name, 1)
                    """
                ),
                {"owner_user_id": user_id, "name": item},
            )


def downgrade():
    op.drop_index('ix_payment_type_configs_owner_user_id', table_name='payment_type_configs')
    op.drop_table('payment_type_configs')
    op.drop_index('ix_company_type_configs_owner_user_id', table_name='company_type_configs')
    op.drop_table('company_type_configs')
