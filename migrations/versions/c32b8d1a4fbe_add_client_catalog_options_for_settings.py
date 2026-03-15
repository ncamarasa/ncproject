"""add client catalog options for settings

Revision ID: c32b8d1a4fbe
Revises: a11f0e4d2b8c
Create Date: 2026-03-14 21:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c32b8d1a4fbe'
down_revision = 'a11f0e4d2b8c'
branch_labels = None
depends_on = None


DEFAULT_OPTIONS = {
    "industry": ["Software", "Finanzas", "Salud", "Educacion", "Retail", "Manufactura"],
    "company_size": ["Micro", "PyME", "Mediana", "Grande", "Enterprise"],
    "country": ["Argentina", "Chile", "Uruguay", "Mexico", "Colombia", "Espana"],
    "currency_code": ["ARS", "USD", "EUR", "CLP", "UYU", "COP"],
    "segment": ["Enterprise", "Mid-Market", "SMB", "Publico"],
    "tax_condition": ["Responsable Inscripto", "Monotributo", "Exento", "Consumidor Final"],
    "preferred_support_channel": ["Email", "WhatsApp", "Portal", "Telefono", "Slack", "Teams"],
    "language": ["Espanol", "Ingles", "Portugues"],
}


def upgrade():
    op.create_table(
        'client_catalog_option_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_user_id', sa.Integer(), nullable=False),
        sa.Column('field_key', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'owner_user_id',
            'field_key',
            'name',
            name='uq_client_catalog_option_configs_owner_field_name',
        ),
    )
    op.create_index(
        'ix_client_catalog_option_configs_owner_user_id',
        'client_catalog_option_configs',
        ['owner_user_id'],
        unique=False,
    )
    op.create_index(
        'ix_client_catalog_option_configs_field_key',
        'client_catalog_option_configs',
        ['field_key'],
        unique=False,
    )

    connection = op.get_bind()
    user_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM users"))]

    for user_id in user_ids:
        for field_key, values in DEFAULT_OPTIONS.items():
            for value in values:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO client_catalog_option_configs (owner_user_id, field_key, name, is_active)
                        VALUES (:owner_user_id, :field_key, :name, 1)
                        """
                    ),
                    {
                        "owner_user_id": user_id,
                        "field_key": field_key,
                        "name": value,
                    },
                )


def downgrade():
    op.drop_index('ix_client_catalog_option_configs_field_key', table_name='client_catalog_option_configs')
    op.drop_index('ix_client_catalog_option_configs_owner_user_id', table_name='client_catalog_option_configs')
    op.drop_table('client_catalog_option_configs')
