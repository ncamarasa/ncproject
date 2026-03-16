"""catalog system flags and default exclusions

Revision ID: c9d8e7f6a5b4
Revises: b3a1f9d4c2e7
Create Date: 2026-03-16 01:20:00.000000
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9d8e7f6a5b4"
down_revision = "b3a1f9d4c2e7"
branch_labels = None
depends_on = None


DEFAULT_CLIENT_STATUSES = ["Prospecto", "Activo", "En pausa", "Inactivo", "Eliminado"]
DEFAULT_PROJECT_STATUSES = ["Planificado", "En progreso", "En pausa", "Completado", "Cancelado"]


def upgrade():
    now = datetime.utcnow()

    with op.batch_alter_table("client_catalog_option_configs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_editable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("is_deletable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(
            sa.Column("exclude_from_default_list", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table("system_catalog_option_configs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_editable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("is_deletable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(
            sa.Column("exclude_from_default_list", sa.Boolean(), nullable=False, server_default=sa.false())
        )

    bind = op.get_bind()
    users = sa.table("users", sa.column("id", sa.Integer))
    client_catalogs = sa.table(
        "client_catalog_option_configs",
        sa.column("owner_user_id", sa.Integer),
        sa.column("field_key", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_system", sa.Boolean),
        sa.column("is_editable", sa.Boolean),
        sa.column("is_deletable", sa.Boolean),
        sa.column("exclude_from_default_list", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    system_catalogs = sa.table(
        "system_catalog_option_configs",
        sa.column("owner_user_id", sa.Integer),
        sa.column("module_key", sa.String),
        sa.column("catalog_key", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_system", sa.Boolean),
        sa.column("is_editable", sa.Boolean),
        sa.column("is_deletable", sa.Boolean),
        sa.column("exclude_from_default_list", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    user_ids = [row[0] for row in bind.execute(sa.select(users.c.id)).fetchall()]
    for user_id in user_ids:
        for status_name in DEFAULT_CLIENT_STATUSES:
            exists = bind.execute(
                sa.select(client_catalogs.c.owner_user_id).where(
                    client_catalogs.c.owner_user_id == user_id,
                    client_catalogs.c.field_key == "client_status",
                    sa.func.lower(client_catalogs.c.name) == status_name.lower(),
                )
            ).first()
            is_deleted = status_name.lower() == "eliminado"
            if exists:
                bind.execute(
                    client_catalogs.update()
                    .where(
                        client_catalogs.c.owner_user_id == user_id,
                        client_catalogs.c.field_key == "client_status",
                        sa.func.lower(client_catalogs.c.name) == status_name.lower(),
                    )
                    .values(
                        is_active=True,
                        is_system=is_deleted,
                        is_editable=not is_deleted,
                        is_deletable=not is_deleted,
                        exclude_from_default_list=is_deleted,
                        updated_at=now,
                    )
                )
            else:
                bind.execute(
                    client_catalogs.insert().values(
                        owner_user_id=user_id,
                        field_key="client_status",
                        name=status_name,
                        is_active=True,
                        is_system=is_deleted,
                        is_editable=not is_deleted,
                        is_deletable=not is_deleted,
                        exclude_from_default_list=is_deleted,
                        created_at=now,
                        updated_at=now,
                    )
                )

        for status_name in DEFAULT_PROJECT_STATUSES:
            exists = bind.execute(
                sa.select(system_catalogs.c.owner_user_id).where(
                    system_catalogs.c.owner_user_id == user_id,
                    system_catalogs.c.module_key == "projects",
                    system_catalogs.c.catalog_key == "project_statuses",
                    sa.func.lower(system_catalogs.c.name) == status_name.lower(),
                )
            ).first()
            is_cancelled = status_name.lower() == "cancelado"
            if exists:
                bind.execute(
                    system_catalogs.update()
                    .where(
                        system_catalogs.c.owner_user_id == user_id,
                        system_catalogs.c.module_key == "projects",
                        system_catalogs.c.catalog_key == "project_statuses",
                        sa.func.lower(system_catalogs.c.name) == status_name.lower(),
                    )
                    .values(
                        is_active=True,
                        is_system=is_cancelled,
                        is_editable=not is_cancelled,
                        is_deletable=not is_cancelled,
                        exclude_from_default_list=is_cancelled,
                        updated_at=now,
                    )
                )
            else:
                bind.execute(
                    system_catalogs.insert().values(
                        owner_user_id=user_id,
                        module_key="projects",
                        catalog_key="project_statuses",
                        name=status_name,
                        is_active=True,
                        is_system=is_cancelled,
                        is_editable=not is_cancelled,
                        is_deletable=not is_cancelled,
                        exclude_from_default_list=is_cancelled,
                        created_at=now,
                        updated_at=now,
                    )
                )


def downgrade():
    with op.batch_alter_table("system_catalog_option_configs", schema=None) as batch_op:
        batch_op.drop_column("exclude_from_default_list")
        batch_op.drop_column("is_deletable")
        batch_op.drop_column("is_editable")
        batch_op.drop_column("is_system")

    with op.batch_alter_table("client_catalog_option_configs", schema=None) as batch_op:
        batch_op.drop_column("exclude_from_default_list")
        batch_op.drop_column("is_deletable")
        batch_op.drop_column("is_editable")
        batch_op.drop_column("is_system")
