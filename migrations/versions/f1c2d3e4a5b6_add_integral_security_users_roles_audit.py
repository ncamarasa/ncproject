"""add integral security users roles audit

Revision ID: f1c2d3e4a5b6
Revises: e40255180d9f
Create Date: 2026-03-14 23:50:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1c2d3e4a5b6'
down_revision = 'e40255180d9f'
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("clients.view", "Ver clientes", "clients"),
    ("clients.edit", "Editar clientes", "clients"),
    ("contracts.view", "Ver contratos", "clients"),
    ("contracts.edit", "Editar contratos", "clients"),
    ("projects.view", "Ver proyectos", "projects"),
    ("projects.edit", "Editar proyectos", "projects"),
    ("tasks.view", "Ver tareas", "tasks"),
    ("tasks.edit", "Editar tareas", "tasks"),
    ("settings.view", "Ver configuración", "settings"),
    ("settings.edit", "Editar configuración", "settings"),
    ("users.manage", "Administrar usuarios", "users"),
    ("auth.reset_password", "Resetear contraseñas", "users"),
    ("audit.view", "Ver auditoría", "audit"),
]


def upgrade() -> None:
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    op.create_table(
        'permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=80), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('module', sa.String(length=40), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key')
    )

    op.create_table(
        'role_permissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('role_id', sa.Integer(), nullable=False),
        sa.Column('permission_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('role_id', 'permission_id', name='uq_role_permission')
    )
    op.create_index(op.f('ix_role_permissions_role_id'), 'role_permissions', ['role_id'], unique=False)
    op.create_index(op.f('ix_role_permissions_permission_id'), 'role_permissions', ['permission_id'], unique=False)

    op.create_table(
        'user_client_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'client_id', name='uq_user_client_assignment')
    )
    op.create_index(op.f('ix_user_client_assignments_user_id'), 'user_client_assignments', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_client_assignments_client_id'), 'user_client_assignments', ['client_id'], unique=False)

    op.create_table(
        'user_project_assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'project_id', name='uq_user_project_assignment')
    )
    op.create_index(op.f('ix_user_project_assignments_user_id'), 'user_project_assignments', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_project_assignments_project_id'), 'user_project_assignments', ['project_id'], unique=False)

    op.create_table(
        'access_audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=80), nullable=True),
        sa.Column('event', sa.String(length=20), nullable=False),
        sa.Column('outcome', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=120), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_access_audit_logs_user_id'), 'access_audit_logs', ['user_id'], unique=False)

    op.create_table(
        'audit_trail_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('table_name', sa.String(length=80), nullable=False),
        sa.Column('record_id', sa.String(length=80), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('old_values', sa.JSON(), nullable=True),
        sa.Column('new_values', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_trail_logs_table_name'), 'audit_trail_logs', ['table_name'], unique=False)
    op.create_index(op.f('ix_audit_trail_logs_record_id'), 'audit_trail_logs', ['record_id'], unique=False)
    op.create_index(op.f('ix_audit_trail_logs_user_id'), 'audit_trail_logs', ['user_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('first_name', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('last_name', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('read_only', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('full_access', sa.Boolean(), server_default=sa.text('1'), nullable=False))
        batch_op.add_column(sa.Column('last_login_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('onboarding_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('role_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_users_email'), ['email'], unique=True)
        batch_op.create_index(op.f('ix_users_role_id'), ['role_id'], unique=False)
        batch_op.create_foreign_key('fk_users_role_id_roles', 'roles', ['role_id'], ['id'])

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO roles (name, description, is_active, created_at, updated_at) "
            "VALUES ('Administrador', 'Acceso completo al sistema', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    role_id = conn.execute(sa.text("SELECT id FROM roles WHERE name = 'Administrador'")).scalar()

    perm_ids = []
    for key, label, module in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permissions (key, label, module, is_active, created_at, updated_at) "
                "VALUES (:key, :label, :module, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"key": key, "label": label, "module": module},
        )
        perm_id = conn.execute(sa.text("SELECT id FROM permissions WHERE key = :key"), {"key": key}).scalar()
        perm_ids.append(perm_id)

    for perm_id in perm_ids:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id, created_at, updated_at) VALUES (:role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"role_id": role_id, "permission_id": perm_id},
        )

    conn.execute(sa.text("UPDATE users SET role_id = :role_id, full_access = 1, read_only = 0 WHERE role_id IS NULL"), {"role_id": role_id})


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('fk_users_role_id_roles', type_='foreignkey')
        batch_op.drop_index(op.f('ix_users_role_id'))
        batch_op.drop_index(op.f('ix_users_email'))
        batch_op.drop_column('role_id')
        batch_op.drop_column('onboarding_date')
        batch_op.drop_column('last_login_at')
        batch_op.drop_column('full_access')
        batch_op.drop_column('read_only')
        batch_op.drop_column('last_name')
        batch_op.drop_column('first_name')
        batch_op.drop_column('email')

    op.drop_index(op.f('ix_audit_trail_logs_user_id'), table_name='audit_trail_logs')
    op.drop_index(op.f('ix_audit_trail_logs_record_id'), table_name='audit_trail_logs')
    op.drop_index(op.f('ix_audit_trail_logs_table_name'), table_name='audit_trail_logs')
    op.drop_table('audit_trail_logs')

    op.drop_index(op.f('ix_access_audit_logs_user_id'), table_name='access_audit_logs')
    op.drop_table('access_audit_logs')

    op.drop_index(op.f('ix_user_project_assignments_project_id'), table_name='user_project_assignments')
    op.drop_index(op.f('ix_user_project_assignments_user_id'), table_name='user_project_assignments')
    op.drop_table('user_project_assignments')

    op.drop_index(op.f('ix_user_client_assignments_client_id'), table_name='user_client_assignments')
    op.drop_index(op.f('ix_user_client_assignments_user_id'), table_name='user_client_assignments')
    op.drop_table('user_client_assignments')

    op.drop_index(op.f('ix_role_permissions_permission_id'), table_name='role_permissions')
    op.drop_index(op.f('ix_role_permissions_role_id'), table_name='role_permissions')
    op.drop_table('role_permissions')

    op.drop_table('permissions')
    op.drop_table('roles')
