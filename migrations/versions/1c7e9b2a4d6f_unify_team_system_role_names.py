"""unify team system role names

Revision ID: 1c7e9b2a4d6f
Revises: f0a1b2c3d4e5
Create Date: 2026-03-17 00:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c7e9b2a4d6f"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


CANONICAL_TEAM_ROLES: dict[str, list[str]] = {
    "Ejecutivo comercial": ["ejecutivo de cuenta", "ejecutivo comercial"],
    "Account manager": ["gerente de cuenta", "account manager"],
    "Responsable delivery": [
        "responsable delivery",
        "delivery manager",
        "responsable tecnico",
        "responsable técnico",
    ],
}


def _merge_role_into(bind, team_roles, resource_role, client_resource, project_resource, task_resource, old_id: int, target_id: int) -> None:
    if old_id == target_id:
        return

    # Evita violar la unique(resource_id, role_id) al consolidar roles en resource_role.
    bind.execute(
        sa.text(
            """
            DELETE FROM resource_role AS rr_old
            WHERE rr_old.role_id = :old_id
              AND EXISTS (
                SELECT 1
                FROM resource_role AS rr_new
                WHERE rr_new.resource_id = rr_old.resource_id
                  AND rr_new.role_id = :target_id
              )
            """
        ),
        {"old_id": old_id, "target_id": target_id},
    )

    bind.execute(resource_role.update().where(resource_role.c.role_id == old_id).values(role_id=target_id))
    bind.execute(client_resource.update().where(client_resource.c.role_id == old_id).values(role_id=target_id))
    bind.execute(project_resource.update().where(project_resource.c.role_id == old_id).values(role_id=target_id))
    bind.execute(task_resource.update().where(task_resource.c.role_id == old_id).values(role_id=target_id))
    bind.execute(team_roles.delete().where(team_roles.c.id == old_id))


def upgrade():
    bind = op.get_bind()

    team_roles = sa.table(
        "team_roles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("is_system", sa.Boolean),
        sa.column("is_editable", sa.Boolean),
        sa.column("is_deletable", sa.Boolean),
    )
    resource_role = sa.table("resource_role", sa.column("resource_id", sa.Integer), sa.column("role_id", sa.Integer))
    client_resource = sa.table("client_resource", sa.column("id", sa.Integer), sa.column("role_id", sa.Integer))
    project_resource = sa.table("project_resource", sa.column("id", sa.Integer), sa.column("role_id", sa.Integer))
    task_resource = sa.table("task_resource", sa.column("id", sa.Integer), sa.column("role_id", sa.Integer))

    for canonical_name, aliases in CANONICAL_TEAM_ROLES.items():
        canonical_row = bind.execute(
            sa.select(team_roles.c.id).where(sa.func.lower(team_roles.c.name) == canonical_name.lower())
        ).first()
        canonical_id = canonical_row.id if canonical_row else None

        alias_rows = bind.execute(
            sa.select(team_roles.c.id, team_roles.c.name)
            .where(sa.func.lower(team_roles.c.name).in_(aliases))
            .order_by(team_roles.c.id.asc())
        ).all()
        alias_ids = [row.id for row in alias_rows]

        if canonical_id is None and alias_ids:
            canonical_id = alias_ids[0]
            bind.execute(
                team_roles.update().where(team_roles.c.id == canonical_id).values(name=canonical_name)
            )
            alias_ids = alias_ids[1:]
        elif canonical_id is not None:
            alias_ids = [role_id for role_id in alias_ids if role_id != canonical_id]

        if canonical_id is None:
            bind.execute(
                team_roles.insert().values(
                    name=canonical_name,
                    is_active=True,
                    is_system=True,
                    is_editable=False,
                    is_deletable=False,
                )
            )
            canonical_id = bind.execute(
                sa.select(team_roles.c.id).where(sa.func.lower(team_roles.c.name) == canonical_name.lower())
            ).scalar_one()

        for old_id in alias_ids:
            _merge_role_into(
                bind,
                team_roles,
                resource_role,
                client_resource,
                project_resource,
                task_resource,
                old_id,
                canonical_id,
            )

        bind.execute(
            team_roles.update()
            .where(team_roles.c.id == canonical_id)
            .values(
                name=canonical_name,
                is_active=True,
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
        )


def downgrade():
    # No se revierte automáticamente para no deshacer consolidaciones de asignaciones.
    pass
