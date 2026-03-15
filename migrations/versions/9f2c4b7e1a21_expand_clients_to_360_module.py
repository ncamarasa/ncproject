"""expand clients to 360 module

Revision ID: 9f2c4b7e1a21
Revises: d8db2498630f
Create Date: 2026-03-14 11:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f2c4b7e1a21'
down_revision = 'd8db2498630f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.add_column(sa.Column('legal_name', sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column('trade_name', sa.String(length=180), nullable=True))
        batch_op.add_column(sa.Column('tax_id', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('client_type', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('industry', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('company_size', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('country', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('region', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('city', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('address', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('website', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('currency_code', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('onboarding_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('observations', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('lead_source', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('segment', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('commercial_priority', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('sales_executive', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('account_manager', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('commercial_status', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('billing_potential', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('health_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('risk_level', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('last_interaction_at', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('next_action_at', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('tax_condition', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('fiscal_address', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('billing_email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('payment_terms', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('purchase_order_required', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('rate_card', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('credit_limit', sa.Numeric(precision=12, scale=2), nullable=True))
        batch_op.add_column(sa.Column('methodology', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('preferred_support_channel', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('support_hours', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('timezone', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('language', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('delivery_manager', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('criticality_level', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('service_type', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('billing_mode', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('default_rate', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('contracted_hours', sa.Numeric(precision=10, scale=2), nullable=True))
        batch_op.add_column(sa.Column('approval_flow', sa.Text(), nullable=True))

    op.execute(sa.text("UPDATE clients SET observations = notes WHERE observations IS NULL AND notes IS NOT NULL"))

    op.create_index('ix_clients_tax_id', 'clients', ['tax_id'], unique=True)
    op.create_index('ix_clients_status', 'clients', ['status'], unique=False)
    op.create_index('ix_clients_segment', 'clients', ['segment'], unique=False)
    op.create_index('ix_clients_risk_level', 'clients', ['risk_level'], unique=False)

    op.create_table(
        'client_contacts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=120), nullable=False),
        sa.Column('job_title', sa.String(length=120), nullable=True),
        sa.Column('area', sa.String(length=80), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('whatsapp', sa.String(length=40), nullable=True),
        sa.Column('relationship_role', sa.String(length=80), nullable=True),
        sa.Column('influence_level', sa.String(length=20), nullable=True),
        sa.Column('interest_level', sa.String(length=20), nullable=True),
        sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_technical', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_administrative', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_billing', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_contacts_client_id', 'client_contacts', ['client_id'], unique=False)

    op.create_table(
        'client_contracts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('contract_type', sa.String(length=80), nullable=False),
        sa.Column('contract_code', sa.String(length=80), nullable=True),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('renewal_date', sa.Date(), nullable=True),
        sa.Column('sla_level', sa.String(length=80), nullable=True),
        sa.Column('nda_signed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('data_processing_agreement', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=40), nullable=True),
        sa.Column('attachment_file_name', sa.String(length=255), nullable=True),
        sa.Column('attachment_original_name', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_contracts_client_id', 'client_contracts', ['client_id'], unique=False)

    op.create_table(
        'client_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=180), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('expires_on', sa.Date(), nullable=True),
        sa.Column('uploaded_by', sa.String(length=120), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_documents_client_id', 'client_documents', ['client_id'], unique=False)

    op.create_table(
        'client_interactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('interaction_type', sa.String(length=40), nullable=False),
        sa.Column('subject', sa.String(length=180), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('interaction_date', sa.Date(), nullable=False),
        sa.Column('next_action_date', sa.Date(), nullable=True),
        sa.Column('owner', sa.String(length=120), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_client_interactions_client_id', 'client_interactions', ['client_id'], unique=False)


def downgrade():
    op.drop_index('ix_client_interactions_client_id', table_name='client_interactions')
    op.drop_table('client_interactions')
    op.drop_index('ix_client_documents_client_id', table_name='client_documents')
    op.drop_table('client_documents')
    op.drop_index('ix_client_contracts_client_id', table_name='client_contracts')
    op.drop_table('client_contracts')
    op.drop_index('ix_client_contacts_client_id', table_name='client_contacts')
    op.drop_table('client_contacts')

    op.drop_index('ix_clients_risk_level', table_name='clients')
    op.drop_index('ix_clients_segment', table_name='clients')
    op.drop_index('ix_clients_status', table_name='clients')
    op.drop_index('ix_clients_tax_id', table_name='clients')

    with op.batch_alter_table('clients', schema=None) as batch_op:
        batch_op.drop_column('approval_flow')
        batch_op.drop_column('contracted_hours')
        batch_op.drop_column('default_rate')
        batch_op.drop_column('billing_mode')
        batch_op.drop_column('service_type')
        batch_op.drop_column('criticality_level')
        batch_op.drop_column('delivery_manager')
        batch_op.drop_column('language')
        batch_op.drop_column('timezone')
        batch_op.drop_column('support_hours')
        batch_op.drop_column('preferred_support_channel')
        batch_op.drop_column('methodology')
        batch_op.drop_column('credit_limit')
        batch_op.drop_column('rate_card')
        batch_op.drop_column('purchase_order_required')
        batch_op.drop_column('payment_terms')
        batch_op.drop_column('billing_email')
        batch_op.drop_column('fiscal_address')
        batch_op.drop_column('tax_condition')
        batch_op.drop_column('next_action_at')
        batch_op.drop_column('last_interaction_at')
        batch_op.drop_column('risk_level')
        batch_op.drop_column('health_score')
        batch_op.drop_column('billing_potential')
        batch_op.drop_column('commercial_status')
        batch_op.drop_column('account_manager')
        batch_op.drop_column('sales_executive')
        batch_op.drop_column('commercial_priority')
        batch_op.drop_column('segment')
        batch_op.drop_column('lead_source')
        batch_op.drop_column('observations')
        batch_op.drop_column('onboarding_date')
        batch_op.drop_column('currency_code')
        batch_op.drop_column('website')
        batch_op.drop_column('address')
        batch_op.drop_column('city')
        batch_op.drop_column('region')
        batch_op.drop_column('country')
        batch_op.drop_column('company_size')
        batch_op.drop_column('industry')
        batch_op.drop_column('status')
        batch_op.drop_column('client_type')
        batch_op.drop_column('tax_id')
        batch_op.drop_column('trade_name')
        batch_op.drop_column('legal_name')
