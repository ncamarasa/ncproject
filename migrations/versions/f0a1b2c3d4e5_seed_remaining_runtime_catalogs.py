"""seed remaining runtime catalogs

Revision ID: f0a1b2c3d4e5
Revises: e6f7a8b9c0d1
Create Date: 2026-03-16 05:45:00.000000
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


DEFAULT_EXTRA_CLIENT_CATALOGS = {
    "commercial_priority": ["Baja", "Media", "Alta", "Critica"],
    "commercial_status": ["Descubierto", "Calificado", "Propuesta", "Negociacion", "Ganado", "Perdido"],
    "risk_level": ["Bajo", "Medio", "Alto", "Critico"],
    "influence_level": ["Baja", "Media", "Alta"],
    "interest_level": ["Bajo", "Medio", "Alto"],
    "contract_status": ["Borrador", "Vigente", "Vencido", "Rescindido"],
    "interaction_type": ["Nota", "Llamada", "Email", "Reunion", "Soporte", "Riesgo"],
}


def upgrade():
    bind = op.get_bind()
    now = datetime.utcnow()

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

    user_ids = [row[0] for row in bind.execute(sa.select(users.c.id)).fetchall()]

    for user_id in user_ids:
        for field_key, values in DEFAULT_EXTRA_CLIENT_CATALOGS.items():
            for name in values:
                exists = bind.execute(
                    sa.select(client_catalogs.c.owner_user_id).where(
                        client_catalogs.c.owner_user_id == user_id,
                        client_catalogs.c.field_key == field_key,
                        sa.func.lower(client_catalogs.c.name) == name.lower(),
                    )
                ).first()
                if exists:
                    bind.execute(
                        client_catalogs.update()
                        .where(
                            client_catalogs.c.owner_user_id == user_id,
                            client_catalogs.c.field_key == field_key,
                            sa.func.lower(client_catalogs.c.name) == name.lower(),
                        )
                        .values(is_active=True, updated_at=now)
                    )
                else:
                    bind.execute(
                        client_catalogs.insert().values(
                            owner_user_id=user_id,
                            field_key=field_key,
                            name=name,
                            is_active=True,
                            is_system=False,
                            is_editable=True,
                            is_deletable=True,
                            exclude_from_default_list=False,
                            created_at=now,
                            updated_at=now,
                        )
                    )


def downgrade():
    # data migration only
    pass
