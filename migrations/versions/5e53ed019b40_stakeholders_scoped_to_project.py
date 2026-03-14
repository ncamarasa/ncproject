"""stakeholders scoped to project

Revision ID: 5e53ed019b40
Revises: 16c3a13dfd37
Create Date: 2026-03-13 22:57:56.782402

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e53ed019b40'
down_revision = '16c3a13dfd37'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'project_stakeholders' in inspector.get_table_names():
        op.drop_table('project_stakeholders')

    with op.batch_alter_table('stakeholders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_stakeholders_project_id_projects',
            'projects',
            ['project_id'],
            ['id'],
        )

    fallback_project_id = connection.execute(sa.text("SELECT id FROM projects ORDER BY id LIMIT 1")).scalar()

    if fallback_project_id is None:
        fallback_client_id = connection.execute(sa.text("SELECT id FROM clients ORDER BY id LIMIT 1")).scalar()
        if fallback_client_id is None:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO clients (name, contact_name, email, phone, notes, is_active)
                    VALUES ('Cliente legado', '', '', '', 'Creado por migracion de stakeholders', 1)
                    """
                )
            )
            fallback_client_id = connection.execute(
                sa.text("SELECT id FROM clients ORDER BY id DESC LIMIT 1")
            ).scalar()

        connection.execute(
            sa.text(
                """
                INSERT INTO projects (
                    name, client_id, description, project_type, status, priority,
                    estimated_start_date, estimated_end_date, owner, observations,
                    contract_file_name, contract_original_name, is_active
                ) VALUES (
                    'Proyecto legado stakeholders',
                    :client_id,
                    'Proyecto creado automaticamente para migrar stakeholders existentes.',
                    'Interno',
                    'En pausa',
                    'Media',
                    NULL, NULL,
                    'Sistema',
                    '',
                    NULL, NULL,
                    0
                )
                """
            ),
            {"client_id": fallback_client_id},
        )
        fallback_project_id = connection.execute(
            sa.text("SELECT id FROM projects ORDER BY id DESC LIMIT 1")
        ).scalar()

    connection.execute(
        sa.text("UPDATE stakeholders SET project_id = :project_id WHERE project_id IS NULL"),
        {"project_id": fallback_project_id},
    )

    with op.batch_alter_table('stakeholders', schema=None) as batch_op:
        batch_op.alter_column('project_id', nullable=False)


def downgrade():
    with op.batch_alter_table('stakeholders', schema=None) as batch_op:
        batch_op.drop_constraint('fk_stakeholders_project_id_projects', type_='foreignkey')
        batch_op.drop_column('project_id')

    op.create_table('project_stakeholders',
    sa.Column('project_id', sa.INTEGER(), nullable=False),
    sa.Column('stakeholder_id', sa.INTEGER(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['stakeholder_id'], ['stakeholders.id'], ),
    sa.PrimaryKeyConstraint('project_id', 'stakeholder_id')
    )
