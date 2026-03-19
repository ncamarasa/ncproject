from __future__ import annotations

from sqlalchemy import select

from project_manager.extensions import db
from project_manager.models import (
    ClientCatalogOptionConfig,
    CompanyTypeConfig,
    PaymentTypeConfig,
    Resource,
    ResourceAvailability,
    ResourceAvailabilityException,
    SystemCatalogOptionConfig,
)

DEFAULT_COMPANY_TYPES = ["Empresa", "Gobierno", "ONG", "Startup", "Otro"]
DEFAULT_PAYMENT_TYPES = ["Contado", "15 días", "30 días", "45 días", "60 días"]
DEFAULT_CLIENT_CATALOGS: dict[str, list[str]] = {
    "industry": ["Software", "Finanzas", "Salud", "Educacion", "Retail", "Manufactura"],
    "company_size": ["Micro", "PyME", "Mediana", "Grande", "Enterprise"],
    "country": ["Argentina", "Chile", "Uruguay", "Mexico", "Colombia", "Espana"],
    "currency_code": ["ARS", "USD", "EUR", "CLP", "UYU", "COP"],
    "billing_mode": ["Abono mensual", "Bolsa de horas", "Tiempo y materiales", "Precio fijo", "Por hitos"],
    "document_category": ["Contrato", "Legal", "Facturación", "Técnico", "Comercial", "Otro"],
    "segment": ["Enterprise", "Mid-Market", "SMB", "Publico"],
    "tax_condition": ["Responsable Inscripto", "Monotributo", "Exento", "Consumidor Final"],
    "preferred_support_channel": ["Email", "WhatsApp", "Portal", "Telefono", "Slack", "Teams"],
    "methodology": ["Agil", "Hibrida", "Cascada", "Kanban", "Scrum"],
    "timezone": ["UTC-05:00", "UTC-04:00", "UTC-03:00", "UTC+00:00", "UTC+01:00"],
    "language": ["Espanol", "Ingles", "Portugues"],
    "client_status": ["Prospecto", "Activo", "En pausa", "Inactivo", "Eliminado"],
    "commercial_priority": ["Baja", "Media", "Alta", "Critica"],
    "commercial_status": ["Descubierto", "Calificado", "Propuesta", "Negociacion", "Ganado", "Perdido"],
    "risk_level": ["Bajo", "Medio", "Alto", "Critico"],
    "influence_level": ["Baja", "Media", "Alta"],
    "interest_level": ["Bajo", "Medio", "Alto"],
    "contract_status": ["Borrador", "Vigente", "Vencido", "Rescindido"],
    "interaction_type": ["Nota", "Llamada", "Email", "Reunion", "Soporte", "Riesgo"],
}
DEFAULT_PROJECT_CATALOGS: dict[str, list[str]] = {
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
DEFAULT_TEAM_CATALOGS: dict[str, list[str]] = {
    "resource_types": ["internal", "external"],
    "availability_types": ["full_time", "part_time", "custom"],
    "availability_exception_types": ["time_off", "vacation", "leave", "holiday", "blocked"],
    "calendars": ["Argentina", "Estados Unidos", "Chile", "Uruguay"],
    "positions": ["Project Manager", "Consultor", "Analista Funcional", "Desarrollador", "QA"],
    "areas": ["Delivery", "Comercial", "Operaciones", "Tecnologia", "Soporte"],
    "vendors": ["Interno", "Partner A", "Partner B", "Freelance", "Consultora Externa"],
}

RESOURCE_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "internal": ("internal", "interno"),
    "external": ("external", "externo"),
}
AVAILABILITY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "full_time": ("full_time", "tiempo_completo", "completo"),
    "part_time": ("part_time", "medio_tiempo", "parcial"),
    "custom": ("custom", "personalizado"),
}
AVAILABILITY_EXCEPTION_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "time_off": ("time_off", "ausencia", "tiempo_fuera"),
    "vacation": ("vacation", "vacaciones"),
    "leave": ("leave", "licencia"),
    "holiday": ("holiday", "feriado"),
    "blocked": ("blocked", "bloqueado", "bloequeado"),
}


def _ensure_company_type(owner_user_id: int, name: str) -> None:
    existing = db.session.execute(
        select(CompanyTypeConfig).where(
            CompanyTypeConfig.owner_user_id == owner_user_id,
            CompanyTypeConfig.name.ilike(name),
        )
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        return
    db.session.add(CompanyTypeConfig(owner_user_id=owner_user_id, name=name, is_active=True))


def _ensure_payment_type(owner_user_id: int, name: str) -> None:
    existing = db.session.execute(
        select(PaymentTypeConfig).where(
            PaymentTypeConfig.owner_user_id == owner_user_id,
            PaymentTypeConfig.name.ilike(name),
        )
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        return
    db.session.add(PaymentTypeConfig(owner_user_id=owner_user_id, name=name, is_active=True))


def _ensure_client_catalog(
    owner_user_id: int,
    field_key: str,
    name: str,
    *,
    is_system: bool = False,
    is_editable: bool = True,
    is_deletable: bool = True,
    exclude_from_default_list: bool = False,
) -> None:
    existing = db.session.execute(
        select(ClientCatalogOptionConfig).where(
            ClientCatalogOptionConfig.owner_user_id == owner_user_id,
            ClientCatalogOptionConfig.field_key == field_key,
            ClientCatalogOptionConfig.name.ilike(name),
        )
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.is_system = bool(existing.is_system or is_system)
        existing.is_editable = bool(existing.is_editable and is_editable)
        existing.is_deletable = bool(existing.is_deletable and is_deletable)
        existing.exclude_from_default_list = bool(existing.exclude_from_default_list or exclude_from_default_list)
        return
    db.session.add(
        ClientCatalogOptionConfig(
            owner_user_id=owner_user_id,
            field_key=field_key,
            name=name,
            is_active=True,
            is_system=is_system,
            is_editable=is_editable,
            is_deletable=is_deletable,
            exclude_from_default_list=exclude_from_default_list,
        )
    )


def _ensure_project_catalog(
    owner_user_id: int,
    catalog_key: str,
    name: str,
    *,
    is_system: bool = False,
    is_editable: bool = True,
    is_deletable: bool = True,
    exclude_from_default_list: bool = False,
) -> None:
    existing = db.session.execute(
        select(SystemCatalogOptionConfig).where(
            SystemCatalogOptionConfig.owner_user_id == owner_user_id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == catalog_key,
            SystemCatalogOptionConfig.name.ilike(name),
        )
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.is_system = bool(existing.is_system or is_system)
        existing.is_editable = bool(existing.is_editable and is_editable)
        existing.is_deletable = bool(existing.is_deletable and is_deletable)
        existing.exclude_from_default_list = bool(existing.exclude_from_default_list or exclude_from_default_list)
        return
    db.session.add(
        SystemCatalogOptionConfig(
            owner_user_id=owner_user_id,
            module_key="projects",
            catalog_key=catalog_key,
            name=name,
            is_active=True,
            is_system=is_system,
            is_editable=is_editable,
            is_deletable=is_deletable,
            exclude_from_default_list=exclude_from_default_list,
        )
    )


def _ensure_team_catalog(
    owner_user_id: int,
    catalog_key: str,
    name: str,
    *,
    is_system: bool = False,
    is_editable: bool = True,
    is_deletable: bool = True,
    exclude_from_default_list: bool = False,
) -> None:
    existing = db.session.execute(
        select(SystemCatalogOptionConfig).where(
            SystemCatalogOptionConfig.owner_user_id == owner_user_id,
            SystemCatalogOptionConfig.module_key == "team",
            SystemCatalogOptionConfig.catalog_key == catalog_key,
            SystemCatalogOptionConfig.name.ilike(name),
        )
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        existing.is_system = bool(existing.is_system or is_system)
        existing.is_editable = bool(existing.is_editable and is_editable)
        existing.is_deletable = bool(existing.is_deletable and is_deletable)
        existing.exclude_from_default_list = bool(existing.exclude_from_default_list or exclude_from_default_list)
        return
    db.session.add(
        SystemCatalogOptionConfig(
            owner_user_id=owner_user_id,
            module_key="team",
            catalog_key=catalog_key,
            name=name,
            is_active=True,
            is_system=is_system,
            is_editable=is_editable,
            is_deletable=is_deletable,
            exclude_from_default_list=exclude_from_default_list,
        )
    )


def seed_default_catalogs_for_user(owner_user_id: int) -> None:
    for name in DEFAULT_COMPANY_TYPES:
        _ensure_company_type(owner_user_id, name)
    for name in DEFAULT_PAYMENT_TYPES:
        _ensure_payment_type(owner_user_id, name)
    for field_key, values in DEFAULT_CLIENT_CATALOGS.items():
        for name in values:
            is_deleted_status = field_key == "client_status" and name.strip().lower() == "eliminado"
            _ensure_client_catalog(
                owner_user_id,
                field_key,
                name,
                is_system=is_deleted_status,
                is_editable=not is_deleted_status,
                is_deletable=not is_deleted_status,
                exclude_from_default_list=is_deleted_status,
            )
    for catalog_key, values in DEFAULT_PROJECT_CATALOGS.items():
        for name in values:
            is_cancelled_status = catalog_key == "project_statuses" and name.strip().lower() == "cancelado"
            _ensure_project_catalog(
                owner_user_id,
                catalog_key,
                name,
                is_system=is_cancelled_status,
                is_editable=not is_cancelled_status,
                is_deletable=not is_cancelled_status,
                exclude_from_default_list=is_cancelled_status,
            )
    for catalog_key, values in DEFAULT_TEAM_CATALOGS.items():
        for name in values:
            is_system = catalog_key in {"resource_types", "availability_types", "availability_exception_types"}
            is_editable = not is_system
            _ensure_team_catalog(
                owner_user_id,
                catalog_key,
                name,
                is_system=is_system,
                is_editable=is_editable,
                is_deletable=not is_system,
            )
    _normalize_resource_types(owner_user_id)
    _normalize_availability_types(owner_user_id)
    _normalize_availability_exception_types(owner_user_id)


def _normalize_resource_types(owner_user_id: int) -> None:
    for canonical, aliases in RESOURCE_TYPE_ALIASES.items():
        normalized_aliases = {alias.strip().lower() for alias in aliases}
        rows = db.session.execute(
            select(SystemCatalogOptionConfig).where(
                SystemCatalogOptionConfig.owner_user_id == owner_user_id,
                SystemCatalogOptionConfig.module_key == "team",
                SystemCatalogOptionConfig.catalog_key == "resource_types",
                db.func.lower(SystemCatalogOptionConfig.name).in_(normalized_aliases),
            )
        ).scalars().all()

        target = next((row for row in rows if row.name.strip().lower() == canonical), rows[0] if rows else None)
        if not target:
            target = SystemCatalogOptionConfig(
                owner_user_id=owner_user_id,
                module_key="team",
                catalog_key="resource_types",
                name=canonical,
                is_active=True,
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
            db.session.add(target)
        else:
            target.name = canonical
            target.is_active = True
            target.is_system = True
            target.is_editable = False
            target.is_deletable = False

        for row in rows:
            if row.id == target.id:
                continue
            row.is_active = False

        db.session.execute(
            Resource.__table__.update()
            .where(db.func.lower(Resource.resource_type).in_(normalized_aliases))
            .values(resource_type=canonical)
        )


def _normalize_availability_types(owner_user_id: int) -> None:
    for canonical, aliases in AVAILABILITY_TYPE_ALIASES.items():
        normalized_aliases = {alias.strip().lower() for alias in aliases}
        rows = db.session.execute(
            select(SystemCatalogOptionConfig).where(
                SystemCatalogOptionConfig.owner_user_id == owner_user_id,
                SystemCatalogOptionConfig.module_key == "team",
                SystemCatalogOptionConfig.catalog_key == "availability_types",
                db.func.lower(SystemCatalogOptionConfig.name).in_(normalized_aliases),
            )
        ).scalars().all()

        target = next((row for row in rows if row.name.strip().lower() == canonical), rows[0] if rows else None)
        if not target:
            target = SystemCatalogOptionConfig(
                owner_user_id=owner_user_id,
                module_key="team",
                catalog_key="availability_types",
                name=canonical,
                is_active=True,
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
            db.session.add(target)
        else:
            target.name = canonical
            target.is_active = True
            target.is_system = True
            target.is_editable = False
            target.is_deletable = False

        for row in rows:
            if row.id == target.id:
                continue
            row.is_active = False

        db.session.execute(
            ResourceAvailability.__table__.update()
            .where(db.func.lower(ResourceAvailability.availability_type).in_(normalized_aliases))
            .values(availability_type=canonical)
        )


def _normalize_availability_exception_types(owner_user_id: int) -> None:
    for canonical, aliases in AVAILABILITY_EXCEPTION_TYPE_ALIASES.items():
        normalized_aliases = {alias.strip().lower() for alias in aliases}
        rows = db.session.execute(
            select(SystemCatalogOptionConfig).where(
                SystemCatalogOptionConfig.owner_user_id == owner_user_id,
                SystemCatalogOptionConfig.module_key == "team",
                SystemCatalogOptionConfig.catalog_key == "availability_exception_types",
                db.func.lower(SystemCatalogOptionConfig.name).in_(normalized_aliases),
            )
        ).scalars().all()

        target = next((row for row in rows if row.name.strip().lower() == canonical), rows[0] if rows else None)
        if not target:
            target = SystemCatalogOptionConfig(
                owner_user_id=owner_user_id,
                module_key="team",
                catalog_key="availability_exception_types",
                name=canonical,
                is_active=True,
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
            db.session.add(target)
        else:
            target.name = canonical
            target.is_active = True
            target.is_system = True
            target.is_editable = False
            target.is_deletable = False

        for row in rows:
            if row.id == target.id:
                continue
            row.is_active = False

        db.session.execute(
            ResourceAvailabilityException.__table__.update()
            .where(db.func.lower(ResourceAvailabilityException.exception_type).in_(normalized_aliases))
            .values(exception_type=canonical)
        )
