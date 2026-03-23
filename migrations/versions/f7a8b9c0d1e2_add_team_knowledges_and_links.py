"""add team knowledges and links

Revision ID: f7a8b9c0d1e2
Revises: e3f4a5b6c7d8
Create Date: 2026-03-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f7a8b9c0d1e2'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'team_knowledges',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_team_knowledges_name'), 'team_knowledges', ['name'], unique=True)

    op.create_table(
        'resource_knowledge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_id'], ['team_knowledges.id']),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('resource_id', 'knowledge_id', name='uq_resource_knowledge_resource_knowledge')
    )
    op.create_index(op.f('ix_resource_knowledge_resource_id'), 'resource_knowledge', ['resource_id'], unique=False)
    op.create_index(op.f('ix_resource_knowledge_knowledge_id'), 'resource_knowledge', ['knowledge_id'], unique=False)

    op.create_table(
        'task_knowledge',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('knowledge_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_id'], ['team_knowledges.id']),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_id', 'knowledge_id', name='uq_task_knowledge_task_knowledge')
    )
    op.create_index(op.f('ix_task_knowledge_task_id'), 'task_knowledge', ['task_id'], unique=False)
    op.create_index(op.f('ix_task_knowledge_knowledge_id'), 'task_knowledge', ['knowledge_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_task_knowledge_knowledge_id'), table_name='task_knowledge')
    op.drop_index(op.f('ix_task_knowledge_task_id'), table_name='task_knowledge')
    op.drop_table('task_knowledge')

    op.drop_index(op.f('ix_resource_knowledge_knowledge_id'), table_name='resource_knowledge')
    op.drop_index(op.f('ix_resource_knowledge_resource_id'), table_name='resource_knowledge')
    op.drop_table('resource_knowledge')

    op.drop_index(op.f('ix_team_knowledges_name'), table_name='team_knowledges')
    op.drop_table('team_knowledges')
