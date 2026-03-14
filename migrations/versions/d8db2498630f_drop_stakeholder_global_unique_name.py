"""drop stakeholder global unique name

Revision ID: d8db2498630f
Revises: 5e53ed019b40
Create Date: 2026-03-13 23:10:38.490149

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd8db2498630f'
down_revision = '5e53ed019b40'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stakeholders_new',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('role', sa.String(length=120), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='fk_stakeholders_project_id_projects'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO stakeholders_new (
                id, project_id, name, role, email, phone, notes, is_active, created_at, updated_at
            )
            SELECT
                id, project_id, name, role, email, phone, notes, is_active, created_at, updated_at
            FROM stakeholders
            """
        )
    )

    op.drop_table('stakeholders')
    op.rename_table('stakeholders_new', 'stakeholders')


def downgrade():
    op.create_table(
        'stakeholders_old',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('role', sa.String(length=120), nullable=True),
        sa.Column('email', sa.String(length=120), nullable=True),
        sa.Column('phone', sa.String(length=40), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='fk_stakeholders_project_id_projects'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO stakeholders_old (
                id, project_id, name, role, email, phone, notes, is_active, created_at, updated_at
            )
            SELECT
                id, project_id, name, role, email, phone, notes, is_active, created_at, updated_at
            FROM stakeholders
            """
        )
    )

    op.drop_table('stakeholders')
    op.rename_table('stakeholders_old', 'stakeholders')
