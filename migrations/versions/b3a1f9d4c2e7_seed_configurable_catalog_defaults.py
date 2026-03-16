"""seed configurable catalog defaults

Revision ID: b3a1f9d4c2e7
Revises: 91b7d2c4e6f1
Create Date: 2026-03-15 23:35:00.000000
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3a1f9d4c2e7"
down_revision = "91b7d2c4e6f1"
branch_labels = None
depends_on = None


DEFAULT_COMPANY_TYPES = ["Empresa", "Gobierno", "ONG", "Startup", "Otro"]
DEFAULT_PAYMENT_TYPES = ["Contado", "15 días", "30 días", "45 días", "60 días"]
DEFAULT_CLIENT_CATALOGS = {
    "industry": ["Software", "Finanzas", "Salud", "Educacion", "Retail", "Manufactura"],
    "company_size": ["Micro", "PyME", "Mediana", "Grande", "Enterprise"],
    "country": ["Argentina", "Chile", "Uruguay", "Mexico", "Colombia", "Espana"],
    "currency_code": ["ARS", "USD", "EUR", "CLP", "UYU", "COP"],
    "billing_mode": ["Abono mensual", "Bolsa de horas", "Tiempo y materiales", "Precio fijo", "Por hitos"],
    "document_category": ["Contrato", "Legal", "Facturación", "Técnico", "Comercial", "Otro"],
    "segment": ["Enterprise", "Mid-Market", "SMB", "Publico"],
    "tax_condition": ["Responsable Inscripto", "Monotributo", "Exento", "Consumidor Final"],
    "preferred_support_channel": ["Email", "WhatsApp", "Portal", "Telefono", "Slack", "Teams"],
    "language": ["Espanol", "Ingles", "Portugues"],
}
DEFAULT_PROJECT_CATALOGS = {
    "project_types": ["Implementacion", "Desarrollo", "Soporte evolutivo", "AMS", "Bolsa de horas", "Consultoria"],
    "project_statuses": ["Planificado", "En progreso", "En pausa", "Completado", "Cancelado"],
    "project_priorities": ["Baja", "Media", "Alta", "Critica"],
    "project_complexities": ["Baja", "Media", "Alta"],
    "project_criticalities": ["Baja", "Media", "Alta", "Critica"],
    "project_methodologies": ["Agil", "Hibrida", "Cascada", "Kanban", "Scrum"],
    "project_close_reasons": ["Completado", "Cancelado por cliente", "Cancelado interno", "Reemplazado"],
    "project_close_results": ["Exitoso", "Parcial", "No logrado"],
    "project_origins": ["Comercial", "Cliente", "Interno", "Regulatorio", "Soporte"],
    "task_types": ["Análisis", "Desarrollo", "Testing", "Documentación", "Deploy", "Hito"],
    "task_statuses": ["Pendiente", "En progreso", "Bloqueada", "Completada"],
    "task_priorities": ["Baja", "Media", "Alta", "Crítica"],
    "task_dependency_types": ["FS", "SS", "FF", "SF"],
    "risk_categories": ["Tecnológico", "Operativo", "Comercial", "Financiero", "Legal"],
}


def upgrade():
    bind = op.get_bind()
    now = datetime.utcnow()

    users = sa.table("users", sa.column("id", sa.Integer))
    company_types = sa.table(
        "company_type_configs",
        sa.column("owner_user_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    payment_types = sa.table(
        "payment_type_configs",
        sa.column("owner_user_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    client_catalogs = sa.table(
        "client_catalog_option_configs",
        sa.column("owner_user_id", sa.Integer),
        sa.column("field_key", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
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
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )

    user_ids = [row[0] for row in bind.execute(sa.select(users.c.id)).fetchall()]
    for user_id in user_ids:
        for name in DEFAULT_COMPANY_TYPES:
            exists = bind.execute(
                sa.select(company_types.c.owner_user_id).where(
                    company_types.c.owner_user_id == user_id,
                    sa.func.lower(company_types.c.name) == name.lower(),
                )
            ).first()
            if exists:
                bind.execute(
                    company_types.update()
                    .where(
                        company_types.c.owner_user_id == user_id,
                        sa.func.lower(company_types.c.name) == name.lower(),
                    )
                    .values(is_active=True, updated_at=now)
                )
            else:
                bind.execute(
                    company_types.insert().values(
                        owner_user_id=user_id,
                        name=name,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

        for name in DEFAULT_PAYMENT_TYPES:
            exists = bind.execute(
                sa.select(payment_types.c.owner_user_id).where(
                    payment_types.c.owner_user_id == user_id,
                    sa.func.lower(payment_types.c.name) == name.lower(),
                )
            ).first()
            if exists:
                bind.execute(
                    payment_types.update()
                    .where(
                        payment_types.c.owner_user_id == user_id,
                        sa.func.lower(payment_types.c.name) == name.lower(),
                    )
                    .values(is_active=True, updated_at=now)
                )
            else:
                bind.execute(
                    payment_types.insert().values(
                        owner_user_id=user_id,
                        name=name,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )

        for field_key, values in DEFAULT_CLIENT_CATALOGS.items():
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
                            created_at=now,
                            updated_at=now,
                        )
                    )

        for catalog_key, values in DEFAULT_PROJECT_CATALOGS.items():
            for name in values:
                exists = bind.execute(
                    sa.select(system_catalogs.c.owner_user_id).where(
                        system_catalogs.c.owner_user_id == user_id,
                        system_catalogs.c.module_key == "projects",
                        system_catalogs.c.catalog_key == catalog_key,
                        sa.func.lower(system_catalogs.c.name) == name.lower(),
                    )
                ).first()
                if exists:
                    bind.execute(
                        system_catalogs.update()
                        .where(
                            system_catalogs.c.owner_user_id == user_id,
                            system_catalogs.c.module_key == "projects",
                            system_catalogs.c.catalog_key == catalog_key,
                            sa.func.lower(system_catalogs.c.name) == name.lower(),
                        )
                        .values(is_active=True, updated_at=now)
                    )
                else:
                    bind.execute(
                        system_catalogs.insert().values(
                            owner_user_id=user_id,
                            module_key="projects",
                            catalog_key=catalog_key,
                            name=name,
                            is_active=True,
                            created_at=now,
                            updated_at=now,
                        )
                    )


def downgrade():
    # Data migration only.
    pass
