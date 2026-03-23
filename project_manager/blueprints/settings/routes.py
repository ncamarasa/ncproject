from datetime import date

from flask import abort, g, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from project_manager.auth_utils import has_permission, login_required
from project_manager.blueprints.settings import bp
from project_manager.extensions import db
from project_manager.models import (
    Client,
    ClientCatalogOptionConfig,
    ClientContact,
    ClientContract,
    ClientDocument,
    ClientInteraction,
    CompanyTypeConfig,
    PaymentTypeConfig,
    Project,
    ProjectCurrencyRateConfig,
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceAvailabilityException,
    ResourceKnowledge,
    ResourceRole,
    Stakeholder,
    SystemCatalogOptionConfig,
    TeamCalendarHolidayConfig,
    TeamKnowledge,
    Task,
    TaskKnowledge,
    TaskResource,
    TeamRole,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import ensure_system_team_roles
from project_manager.utils.dates import parse_date_input
from project_manager.utils.numbers import parse_decimal_input


CLIENT_CATALOG_FIELDS = {
    "industry": "Rubro",
    "company_size": "Tamaño",
    "country": "País",
    "currency_code": "Moneda",
    "billing_mode": "Modalidad de facturación",
    "document_category": "Categoría de documento",
    "client_status": "Estado de cliente",
    "lead_source": "Origen de gestión comercial",
    "commercial_priority": "Prioridad comercial",
    "commercial_status": "Estado comercial",
    "risk_level": "Riesgo",
    "influence_level": "Nivel de influencia",
    "interest_level": "Nivel de interés",
    "contract_status": "Estado de contrato",
    "interaction_type": "Tipo de interacción",
    "tax_condition": "Condición impositiva",
    "preferred_support_channel": "Canal de soporte preferido",
    "methodology": "Metodología",
    "language": "Idioma",
}

PROJECT_CATALOG_FIELDS = {
    "project_types": "Tipos de proyecto",
    "project_statuses": "Estados de proyecto",
    "project_priorities": "Prioridades de proyecto",
    "project_complexities": "Niveles de complejidad",
    "project_criticalities": "Criticidad",
    "project_methodologies": "Metodologías",
    "task_types": "Tipos de tarea",
    "task_statuses": "Estados de tarea",
    "task_priorities": "Prioridades de tarea",
    "risk_categories": "Categorías de riesgo",
    "stakeholder_roles": "Roles de stakeholder",
    "project_close_reasons": "Motivos de cierre",
    "project_close_results": "Resultados de cierre",
    "internal_task_categories": "Categorías internas",
}

PROJECT_CATALOG_DESCRIPTIONS = {
    "project_types": 'Define los tipos de proyecto (implementación, desarrollo, AMS, BI, etc.).',
    "project_statuses": "Administra el ciclo de vida del proyecto (planificado, en progreso, en pausa, cerrado).",
    "project_priorities": "Configura la prioridad operativa/comercial para ordenar la atención de proyectos.",
    "project_complexities": "Establece niveles de complejidad para estimación, asignación y seguimiento.",
    "project_criticalities": "Clasifica criticidad para gestión de riesgos y escalamiento.",
    "project_methodologies": "Define metodologías de ejecución disponibles (Scrum, Kanban, Cascada, Híbrida).",
    "task_types": "Administra tipos de tarea para planificación y reporting de trabajo.",
    "task_statuses": "Configura estados de tareas para tableros y seguimiento operativo.",
    "task_priorities": "Define prioridades de tareas para secuenciar ejecución.",
    "risk_categories": "Configura categorías de riesgo para análisis y mitigación.",
    "stakeholder_roles": "Define roles de stakeholders del proyecto (ej: Sponsor Cliente, Key User).",
    "project_close_reasons": "Define motivos de cierre del proyecto para trazabilidad de gestión.",
    "project_close_results": "Configura resultados de cierre para análisis de performance.",
    "internal_task_categories": "Define categorías imputables para el Proyecto Interno (soporte, capacitación, licencia, etc.).",
    "currency_rates": "Administra cotizaciones de monedas para convertir costos/precios entre divisas.",
}
INTERNAL_PROJECT_CODE = "SYS-INTERNAL"
INTERNAL_PROJECT_NAME = "Proyecto Interno"

SHARED_CLIENT_CATALOG_FIELDS_BY_MODULE = {
    "projects": {
        "currency_code": "Moneda",
        "billing_mode": "Modalidad de facturación",
    },
    "team": {
        "currency_code": "Moneda",
    },
}

TEAM_CATALOG_FIELDS = {
    "resource_types": "Tipos de recurso",
    "availability_types": "Tipos de disponibilidad",
    "availability_exception_types": "Tipos de excepción de disponibilidad",
    "calendars": "Calendarios",
    "positions": "Cargos",
    "areas": "Areas",
    "vendors": "Proveedores",
}

TEAM_CATALOG_DESCRIPTIONS = {
    "resource_types": "Define los tipos de recurso para la ficha de Equipo (interno, tercerizado, etc.).",
    "availability_types": "Configura los tipos de disponibilidad para capacidad operativa (full time, part time, custom).",
    "availability_exception_types": "Configura los tipos de excepción de disponibilidad (vacaciones, licencia, feriado, etc.).",
    "calendars": "Define calendarios laborales (Argentina, Estados Unidos, etc.) para aplicar feriados por recurso.",
    "positions": "Administra cargos de recursos: describen su puesto organizacional en la empresa.",
    "areas": "Administra el catalogo de areas organizativas para clasificar recursos.",
    "vendors": "Administra el catalogo de proveedores/partners para recursos tercerizados.",
}
TEAM_ROLE_CANONICAL_NAMES = {
    "ejecutivo de cuenta": "Ejecutivo comercial",
    "ejecutivo comercial": "Ejecutivo comercial",
    "gerente de cuenta": "Gerente de cuenta",
    "account manager": "Gerente de cuenta",
    "responsable cliente": "Gerente de cuenta",
    "delivery manager": "Responsable delivery",
    "responsable delivery": "Responsable delivery",
    "responsable tecnico": "Responsable delivery",
    "responsable técnico": "Responsable delivery",
}


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


_parse_date = parse_date_input


def _normalize_team_catalog_name(catalog_key: str, name: str) -> str:
    if catalog_key == "resource_types":
        normalized = "_".join(name.strip().lower().split())
        if normalized == "interno":
            return "internal"
        if normalized == "externo":
            return "external"
        return normalized
    if catalog_key == "availability_types":
        normalized = "_".join(name.strip().lower().split())
        aliases = {
            "tiempo_completo": "full_time",
            "completo": "full_time",
            "medio_tiempo": "part_time",
            "parcial": "part_time",
            "personalizado": "custom",
        }
        return aliases.get(normalized, normalized)
    if catalog_key == "availability_exception_types":
        normalized = "_".join(name.strip().lower().split())
        aliases = {
            "ausencia": "time_off",
            "tiempo_fuera": "time_off",
            "vacaciones": "vacation",
            "licencia": "leave",
            "feriado": "holiday",
            "bloqueado": "blocked",
            "bloequeado": "blocked",
        }
        return aliases.get(normalized, normalized)
    if catalog_key in {"resource_types", "availability_types", "availability_exception_types"}:
        return "_".join(name.strip().lower().split())
    return name


def _canonical_team_role_name(name: str) -> str:
    normalized = " ".join(name.strip().lower().split())
    return TEAM_ROLE_CANONICAL_NAMES.get(normalized, " ".join(name.strip().split()))


def _upsert_config_item(model, name: str):
    existing = db.session.execute(
        select(model).where(model.owner_user_id == g.user.id, model.name.ilike(name))
    ).scalar_one_or_none()
    if existing:
        existing.is_active = True
        return False

    db.session.add(model(owner_user_id=g.user.id, name=name, is_active=True))
    return True


def _get_active_items(model):
    return db.session.execute(
        select(model)
        .where(model.owner_user_id == g.user.id, model.is_active.is_(True))
        .order_by(model.name.asc())
    ).scalars()


def _validate_unique_name(model, owner_user_id: int, name: str, current_id: int | None = None):
    stmt = select(model).where(model.owner_user_id == owner_user_id, model.name.ilike(name))
    if current_id:
        stmt = stmt.where(model.id != current_id)
    return db.session.execute(stmt).scalar_one_or_none() is None


def _count_usage(model, column, value: str) -> int:
    if not value:
        return 0
    return db.session.execute(
        select(func.count()).select_from(model).where(func.lower(column) == value.lower())
    ).scalar_one()


def _team_role_usage_count(role_id: int) -> int:
    return int(
        (db.session.execute(select(func.count()).select_from(ResourceRole).where(ResourceRole.role_id == role_id)).scalar_one() or 0)
        + (db.session.execute(select(func.count()).select_from(ProjectResource).where(ProjectResource.role_id == role_id)).scalar_one() or 0)
        + (db.session.execute(select(func.count()).select_from(TaskResource).where(TaskResource.role_id == role_id)).scalar_one() or 0)
    )


def _team_knowledge_usage_count(knowledge_id: int) -> int:
    return int(
        (db.session.execute(
            select(func.count()).select_from(ResourceKnowledge).where(ResourceKnowledge.knowledge_id == knowledge_id)
        ).scalar_one() or 0)
        + (db.session.execute(
            select(func.count()).select_from(TaskKnowledge).where(TaskKnowledge.knowledge_id == knowledge_id)
        ).scalar_one() or 0)
    )


def _ensure_team_catalog_defaults() -> None:
    seed_default_catalogs_for_user(g.user.id)
    db.session.commit()


def _company_type_in_use(name: str) -> bool:
    return _count_usage(Client, Client.client_type, name) > 0


def _payment_type_in_use(name: str) -> bool:
    return _count_usage(Client, Client.payment_terms, name) > 0


def _client_catalog_in_use(field_key: str, name: str) -> bool:
    if field_key == "industry":
        return _count_usage(Client, Client.industry, name) > 0
    if field_key == "company_size":
        return _count_usage(Client, Client.company_size, name) > 0
    if field_key == "country":
        return _count_usage(Client, Client.country, name) > 0
    if field_key == "currency_code":
        return (
            _count_usage(Client, Client.currency_code, name) > 0
            or _count_usage(ClientContract, ClientContract.currency_code, name) > 0
            or _count_usage(Project, Project.currency_code, name) > 0
        )
    if field_key == "billing_mode":
        return (
            _count_usage(ClientContract, ClientContract.billing_mode, name) > 0
            or _count_usage(Project, Project.billing_mode, name) > 0
        )
    if field_key == "document_category":
        return _count_usage(ClientDocument, ClientDocument.category, name) > 0
    if field_key == "client_status":
        return _count_usage(Client, Client.status, name) > 0
    if field_key == "lead_source":
        return _count_usage(Client, Client.lead_source, name) > 0
    if field_key == "commercial_priority":
        return _count_usage(Client, Client.commercial_priority, name) > 0
    if field_key == "commercial_status":
        return _count_usage(Client, Client.commercial_status, name) > 0
    if field_key == "risk_level":
        return (
            _count_usage(Client, Client.risk_level, name) > 0
            or _count_usage(Client, Client.criticality_level, name) > 0
            or _count_usage(ClientInteraction, ClientInteraction.risk_level, name) > 0
        )
    if field_key == "influence_level":
        return _count_usage(ClientContact, ClientContact.influence_level, name) > 0
    if field_key == "interest_level":
        return _count_usage(ClientContact, ClientContact.interest_level, name) > 0
    if field_key == "contract_status":
        return _count_usage(ClientContract, ClientContract.status, name) > 0
    if field_key == "interaction_type":
        return _count_usage(ClientInteraction, ClientInteraction.interaction_type, name) > 0
    if field_key == "tax_condition":
        return _count_usage(Client, Client.tax_condition, name) > 0
    if field_key == "preferred_support_channel":
        return _count_usage(Client, Client.preferred_support_channel, name) > 0
    if field_key == "methodology":
        return _count_usage(Client, Client.methodology, name) > 0
    if field_key == "language":
        return _count_usage(Client, Client.language, name) > 0
    return False


def _project_catalog_in_use(catalog_key: str, name: str) -> bool:
    if catalog_key == "project_types":
        return _count_usage(Project, Project.project_type, name) > 0
    if catalog_key == "project_statuses":
        return _count_usage(Project, Project.status, name) > 0
    if catalog_key == "project_priorities":
        return _count_usage(Project, Project.priority, name) > 0
    if catalog_key == "project_complexities":
        return _count_usage(Project, Project.complexity_level, name) > 0
    if catalog_key == "project_criticalities":
        return _count_usage(Project, Project.criticality_level, name) > 0
    if catalog_key == "project_methodologies":
        return _count_usage(Project, Project.methodology, name) > 0
    if catalog_key == "project_origins":
        return _count_usage(Project, Project.project_origin, name) > 0
    if catalog_key == "task_types":
        return _count_usage(Task, Task.task_type, name) > 0
    if catalog_key == "task_statuses":
        return _count_usage(Task, Task.status, name) > 0
    if catalog_key == "task_priorities":
        return _count_usage(Task, Task.priority, name) > 0
    if catalog_key == "stakeholder_roles":
        return _count_usage(Stakeholder, Stakeholder.role, name) > 0
    if catalog_key == "internal_task_categories":
        return (
            db.session.execute(
                select(func.count())
                .select_from(Task)
                .join(Project, Project.id == Task.project_id)
                .where(
                    Task.is_active.is_(True),
                    (Project.project_code == INTERNAL_PROJECT_CODE) | (Project.name == INTERNAL_PROJECT_NAME),
                    func.lower(Task.title) == name.lower(),
                )
            ).scalar_one()
            > 0
        )
    return False


def _project_catalog_usage_count(catalog_key: str, name: str) -> int:
    if not name:
        return 0
    if catalog_key == "project_types":
        return _count_usage(Project, Project.project_type, name)
    if catalog_key == "project_statuses":
        return _count_usage(Project, Project.status, name)
    if catalog_key == "project_priorities":
        return _count_usage(Project, Project.priority, name)
    if catalog_key == "project_complexities":
        return _count_usage(Project, Project.complexity_level, name)
    if catalog_key == "project_criticalities":
        return _count_usage(Project, Project.criticality_level, name)
    if catalog_key == "project_methodologies":
        return _count_usage(Project, Project.methodology, name)
    if catalog_key == "project_origins":
        return _count_usage(Project, Project.project_origin, name)
    if catalog_key == "task_types":
        return _count_usage(Task, Task.task_type, name)
    if catalog_key == "task_statuses":
        return _count_usage(Task, Task.status, name)
    if catalog_key == "task_priorities":
        return _count_usage(Task, Task.priority, name)
    if catalog_key == "stakeholder_roles":
        return _count_usage(Stakeholder, Stakeholder.role, name)
    if catalog_key == "internal_task_categories":
        return db.session.execute(
            select(func.count())
            .select_from(Task)
            .join(Project, Project.id == Task.project_id)
            .where(
                Task.is_active.is_(True),
                (Project.project_code == INTERNAL_PROJECT_CODE) | (Project.name == INTERNAL_PROJECT_NAME),
                func.lower(Task.title) == name.lower(),
            )
        ).scalar_one()
    return 0


def _team_catalog_in_use(catalog_key: str, name: str) -> bool:
    if catalog_key == "resource_types":
        return _count_usage(Resource, Resource.resource_type, name) > 0
    if catalog_key == "availability_types":
        return _count_usage(ResourceAvailability, ResourceAvailability.availability_type, name) > 0
    if catalog_key == "availability_exception_types":
        return _count_usage(ResourceAvailabilityException, ResourceAvailabilityException.exception_type, name) > 0
    if catalog_key == "calendars":
        resource_in_use = _count_usage(Resource, Resource.calendar_name, name) > 0
        holiday_in_use = db.session.execute(
            select(func.count()).select_from(TeamCalendarHolidayConfig).where(
                TeamCalendarHolidayConfig.owner_user_id == g.user.id,
                TeamCalendarHolidayConfig.is_active.is_(True),
                func.lower(TeamCalendarHolidayConfig.calendar_name) == name.lower(),
            )
        ).scalar_one() > 0
        return resource_in_use or holiday_in_use
    if catalog_key == "positions":
        return _count_usage(Resource, Resource.position, name) > 0
    if catalog_key == "areas":
        return _count_usage(Resource, Resource.area, name) > 0
    if catalog_key == "vendors":
        return _count_usage(Resource, Resource.vendor_name, name) > 0
    if catalog_key == "knowledges":
        knowledge = db.session.execute(
            select(TeamKnowledge).where(func.lower(TeamKnowledge.name) == name.lower())
        ).scalar_one_or_none()
        if not knowledge:
            return False
        return _team_knowledge_usage_count(knowledge.id) > 0
    return False


@bp.before_request
def _authorize_settings_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    endpoint = request.endpoint or ""
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    write_permissions_by_endpoint = {
        "settings.team_calendars": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_team_calendar_holiday": ["settings.catalogs.manage", "settings.edit"],
        "settings.add_team_calendar_holiday_from_edit": ["settings.catalogs.manage", "settings.edit"],
        "settings.team_roles": ["settings.catalogs.manage", "settings.edit"],
        "settings.team_knowledges": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_team_knowledge": ["settings.catalogs.manage", "settings.edit"],
        "settings.toggle_team_knowledge": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_team_role": ["settings.catalogs.manage", "settings.edit"],
        "settings.toggle_team_role": ["settings.catalogs.manage", "settings.edit"],
        "settings.team_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_team_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_team_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.project_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_project_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_project_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.project_currency_rates": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_project_currency_rate": ["settings.catalogs.manage", "settings.edit"],
        "settings.company_types": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_company_type": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_company_type": ["settings.catalogs.manage", "settings.edit"],
        "settings.payment_types": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_payment_type": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_payment_type": ["settings.catalogs.manage", "settings.edit"],
        "settings.client_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.edit_client_catalog": ["settings.catalogs.manage", "settings.edit"],
        "settings.delete_client_catalog": ["settings.catalogs.manage", "settings.edit"],
    }
    required = write_permissions_by_endpoint.get(endpoint, ["settings.edit"] if is_write else ["settings.view"])
    if not any(has_permission(g.user, permission_key) for permission_key in required):
        flash("No tienes permisos para configuración.", "danger")
        return redirect(url_for("main.home"))


@bp.route("/")
@login_required
def index():
    return redirect(url_for("settings.projects_settings"))


@bp.route("/projects")
@login_required
def projects_settings():
    return render_template(
        "settings/projects.html",
        project_catalog_fields=PROJECT_CATALOG_FIELDS,
        project_catalog_descriptions=PROJECT_CATALOG_DESCRIPTIONS,
        shared_catalog_fields=SHARED_CLIENT_CATALOG_FIELDS_BY_MODULE.get("projects", {}),
    )


def _normalize_currency_code(value: str | None) -> str:
    return _safe_strip(value).upper()


def _ranges_overlap(start_a: date, end_a: date | None, start_b: date, end_b: date | None) -> bool:
    a_end = end_a or date.max
    b_end = end_b or date.max
    return start_a <= b_end and start_b <= a_end


@bp.route("/projects/currency-rates", methods=["GET", "POST"])
@login_required
def project_currency_rates():
    edit_id = request.args.get("edit_id")
    try:
        edit_id_int = int(edit_id) if edit_id else None
    except ValueError:
        edit_id_int = None
    edit_rate = db.session.get(ProjectCurrencyRateConfig, edit_id_int) if edit_id_int else None
    if edit_rate and edit_rate.owner_user_id != g.user.id:
        abort(404)

    if request.method == "POST":
        errors: list[str] = []
        rate_id = request.form.get("rate_id")
        target = db.session.get(ProjectCurrencyRateConfig, int(rate_id)) if rate_id else None
        if target and target.owner_user_id != g.user.id:
            abort(404)

        from_currency = _normalize_currency_code(request.form.get("from_currency"))
        to_currency = _normalize_currency_code(request.form.get("to_currency"))
        valid_from = _parse_date(request.form.get("valid_from"))
        valid_to = _parse_date(request.form.get("valid_to"))
        rate = request.form.get("rate")
        notes = _safe_strip(request.form.get("notes"))

        rate_value = parse_decimal_input(rate)

        if len(from_currency) < 3 or len(to_currency) < 3:
            errors.append("Debes informar monedas válidas (ej: USD, ARS).")
        if from_currency == to_currency and from_currency:
            errors.append("La moneda origen y destino deben ser diferentes.")
        if not valid_from:
            errors.append("La fecha Desde es obligatoria.")
        if valid_from and valid_to and valid_to < valid_from:
            errors.append("La fecha Hasta no puede ser menor a Desde.")
        if rate_value is None or rate_value <= 0:
            errors.append("La cotización debe ser mayor a 0.")

        if not errors and valid_from:
            rows = db.session.execute(
                select(ProjectCurrencyRateConfig).where(
                    ProjectCurrencyRateConfig.owner_user_id == g.user.id,
                    ProjectCurrencyRateConfig.from_currency == from_currency,
                    ProjectCurrencyRateConfig.to_currency == to_currency,
                    ProjectCurrencyRateConfig.is_active.is_(True),
                )
            ).scalars().all()
            for row in rows:
                if target and row.id == target.id:
                    continue
                if _ranges_overlap(valid_from, valid_to, row.valid_from, row.valid_to):
                    errors.append("Ya existe una cotización activa superpuesta para ese par de monedas.")
                    break

        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            if target:
                target.from_currency = from_currency
                target.to_currency = to_currency
                target.valid_from = valid_from
                target.valid_to = valid_to
                target.rate = rate_value
                target.notes = notes or None
                target.is_active = True
                flash("Cotización actualizada.", "success")
            else:
                db.session.add(
                    ProjectCurrencyRateConfig(
                        owner_user_id=g.user.id,
                        from_currency=from_currency,
                        to_currency=to_currency,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        rate=rate_value,
                        notes=notes or None,
                        is_active=True,
                    )
                )
                flash("Cotización agregada.", "success")
            db.session.commit()
            return redirect(url_for("settings.project_currency_rates"))

    rates = db.session.execute(
        select(ProjectCurrencyRateConfig)
        .where(
            ProjectCurrencyRateConfig.owner_user_id == g.user.id,
            ProjectCurrencyRateConfig.is_active.is_(True),
        )
        .order_by(
            ProjectCurrencyRateConfig.from_currency.asc(),
            ProjectCurrencyRateConfig.to_currency.asc(),
            ProjectCurrencyRateConfig.valid_from.desc(),
        )
    ).scalars().all()

    return render_template(
        "settings/project_currency_rates.html",
        rates=rates,
        edit_rate=edit_rate,
        form_values=request.form if request.method == "POST" else {},
    )


@bp.route("/projects/currency-rates/<int:rate_id>/delete", methods=["POST"])
@login_required
def delete_project_currency_rate(rate_id: int):
    rate = db.session.get(ProjectCurrencyRateConfig, rate_id)
    if not rate or rate.owner_user_id != g.user.id:
        abort(404)
    rate.is_active = False
    db.session.commit()
    flash("Cotización eliminada.", "info")
    return redirect(url_for("settings.project_currency_rates"))


@bp.route("/team")
@login_required
def team_settings():
    ensure_system_team_roles()
    _ensure_team_catalog_defaults()
    return render_template(
        "settings/team.html",
        team_catalog_fields=TEAM_CATALOG_FIELDS,
        team_catalog_descriptions=TEAM_CATALOG_DESCRIPTIONS,
        shared_catalog_fields=SHARED_CLIENT_CATALOG_FIELDS_BY_MODULE.get("team", {}),
    )


@bp.route("/team/calendars", methods=["GET", "POST"])
@login_required
def team_calendars():
    _ensure_team_catalog_defaults()
    calendar_options = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "team",
            SystemCatalogOptionConfig.catalog_key == "calendars",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.name.asc())
    ).scalars().all()

    requested_calendar = _safe_strip(request.args.get("calendar"))
    valid_calendars = set(calendar_options)
    if requested_calendar and requested_calendar in valid_calendars:
        selected_calendar = requested_calendar
    else:
        selected_calendar = calendar_options[0] if calendar_options else ""
    holidays = []
    if selected_calendar:
        holidays = db.session.execute(
            select(TeamCalendarHolidayConfig)
            .where(
                TeamCalendarHolidayConfig.owner_user_id == g.user.id,
                TeamCalendarHolidayConfig.calendar_name == selected_calendar,
                TeamCalendarHolidayConfig.is_active.is_(True),
            )
            .order_by(TeamCalendarHolidayConfig.holiday_date.asc())
        ).scalars().all()

    if request.method == "POST":
        calendar_name = _safe_strip(request.form.get("calendar_name"))
        holiday_date = _parse_date(request.form.get("holiday_date"))
        label = _safe_strip(request.form.get("label"))
        errors: list[str] = []
        if calendar_name not in set(calendar_options):
            errors.append("Calendario inválido.")
        if not holiday_date:
            errors.append("Fecha inválida.")
        if len(label) < 2:
            errors.append("Descripción inválida.")
        if errors:
            for error in errors:
                flash(error, "danger")
            return redirect(url_for("settings.team_calendars", calendar=selected_calendar or calendar_name))

        existing = db.session.execute(
            select(TeamCalendarHolidayConfig).where(
                TeamCalendarHolidayConfig.owner_user_id == g.user.id,
                TeamCalendarHolidayConfig.calendar_name == calendar_name,
                TeamCalendarHolidayConfig.holiday_date == holiday_date,
            )
        ).scalar_one_or_none()
        if existing:
            existing.label = label
            existing.is_active = True
            flash("Feriado actualizado/reactivado.", "success")
        else:
            db.session.add(
                TeamCalendarHolidayConfig(
                    owner_user_id=g.user.id,
                    calendar_name=calendar_name,
                    holiday_date=holiday_date,
                    label=label,
                    is_active=True,
                )
            )
            flash("Feriado agregado.", "success")
        db.session.commit()
        return redirect(url_for("settings.team_calendars", calendar=calendar_name))

    return render_template(
        "settings/team_calendars.html",
        calendar_options=calendar_options,
        selected_calendar=selected_calendar,
        holidays=holidays,
    )


@bp.route("/team/calendars/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_team_calendar_holiday(item_id: int):
    item = db.session.get(TeamCalendarHolidayConfig, item_id)
    if not item or item.owner_user_id != g.user.id:
        abort(404)
    item.is_active = False
    db.session.commit()
    flash("Feriado eliminado.", "info")
    calendar_item_id = request.args.get("calendar_item_id")
    if calendar_item_id:
        try:
            return redirect(url_for("settings.edit_team_catalog", catalog_key="calendars", item_id=int(calendar_item_id)))
        except ValueError:
            pass
    return redirect(url_for("settings.team_calendars", calendar=item.calendar_name))


@bp.route("/team/catalog/calendars/<int:item_id>/holidays/add", methods=["POST"])
@login_required
def add_team_calendar_holiday_from_edit(item_id: int):
    calendar_item = db.session.get(SystemCatalogOptionConfig, item_id)
    if (
        not calendar_item
        or calendar_item.owner_user_id != g.user.id
        or calendar_item.module_key != "team"
        or calendar_item.catalog_key != "calendars"
        or not calendar_item.is_active
    ):
        abort(404)

    holiday_date = _parse_date(request.form.get("holiday_date"))
    label = _safe_strip(request.form.get("label"))
    if not holiday_date:
        flash("Fecha inválida.", "danger")
        return redirect(url_for("settings.edit_team_catalog", catalog_key="calendars", item_id=calendar_item.id))
    if len(label) < 2:
        flash("Descripción inválida.", "danger")
        return redirect(url_for("settings.edit_team_catalog", catalog_key="calendars", item_id=calendar_item.id))

    existing = db.session.execute(
        select(TeamCalendarHolidayConfig).where(
            TeamCalendarHolidayConfig.owner_user_id == g.user.id,
            TeamCalendarHolidayConfig.calendar_name == calendar_item.name,
            TeamCalendarHolidayConfig.holiday_date == holiday_date,
        )
    ).scalar_one_or_none()
    if existing:
        existing.label = label
        existing.is_active = True
        flash("Feriado actualizado/reactivado.", "success")
    else:
        db.session.add(
            TeamCalendarHolidayConfig(
                owner_user_id=g.user.id,
                calendar_name=calendar_item.name,
                holiday_date=holiday_date,
                label=label,
                is_active=True,
            )
        )
        flash("Feriado agregado.", "success")
    db.session.commit()
    return redirect(url_for("settings.edit_team_catalog", catalog_key="calendars", item_id=calendar_item.id))


@bp.route("/team/roles", methods=["GET", "POST"])
@login_required
def team_roles():
    ensure_system_team_roles()
    if request.method == "POST":
        name = _canonical_team_role_name(_safe_strip(request.form.get("name")))
        description = _safe_strip(request.form.get("description"))
        if len(name) < 2:
            flash("El nombre del rol es inválido.", "danger")
        elif db.session.execute(
            select(TeamRole.id).where(func.lower(TeamRole.name) == name.lower())
        ).scalar_one_or_none():
            flash("Ya existe un rol con ese nombre.", "danger")
        else:
            db.session.add(
                TeamRole(
                    name=name,
                    description=description,
                    is_active=True,
                    is_system=False,
                    is_editable=True,
                    is_deletable=True,
                )
            )
            db.session.commit()
            flash("Rol creado.", "success")
        return redirect(url_for("settings.team_roles"))

    roles = db.session.execute(select(TeamRole).order_by(TeamRole.name.asc())).scalars().all()
    role_usage = {role.id: _team_role_usage_count(role.id) for role in roles}
    return render_template("settings/team_roles.html", roles=roles, role_usage=role_usage)


@bp.route("/team/knowledges", methods=["GET", "POST"])
@login_required
def team_knowledges():
    if request.method == "POST":
        name = " ".join(_safe_strip(request.form.get("name")).split())
        description = _safe_strip(request.form.get("description"))
        if len(name) < 2:
            flash("El nombre del conocimiento es inválido.", "danger")
        else:
            existing = db.session.execute(
                select(TeamKnowledge).where(func.lower(TeamKnowledge.name) == name.lower())
            ).scalar_one_or_none()
            if existing:
                existing.description = description or existing.description
                existing.is_active = True
                flash("Conocimiento reactivado.", "success")
            else:
                db.session.add(
                    TeamKnowledge(
                        name=name,
                        description=description,
                        is_active=True,
                    )
                )
                flash("Conocimiento creado.", "success")
            db.session.commit()
        return redirect(url_for("settings.team_knowledges"))

    knowledges = db.session.execute(select(TeamKnowledge).order_by(TeamKnowledge.name.asc())).scalars().all()
    usage_by_knowledge = {knowledge.id: _team_knowledge_usage_count(knowledge.id) for knowledge in knowledges}
    return render_template(
        "settings/team_knowledges.html",
        knowledges=knowledges,
        usage_by_knowledge=usage_by_knowledge,
    )


@bp.route("/team/knowledges/<int:knowledge_id>/edit", methods=["GET", "POST"])
@login_required
def edit_team_knowledge(knowledge_id: int):
    knowledge = db.session.get(TeamKnowledge, knowledge_id)
    if not knowledge:
        abort(404)

    if request.method == "POST":
        name = " ".join(_safe_strip(request.form.get("name")).split())
        description = _safe_strip(request.form.get("description"))
        if len(name) < 2:
            flash("El nombre del conocimiento es inválido.", "danger")
        elif db.session.execute(
            select(TeamKnowledge.id).where(
                TeamKnowledge.id != knowledge.id,
                func.lower(TeamKnowledge.name) == name.lower(),
            )
        ).scalar_one_or_none():
            flash("Ya existe otro conocimiento con ese nombre.", "danger")
        else:
            knowledge.name = name
            knowledge.description = description
            db.session.commit()
            flash("Conocimiento actualizado.", "success")
            return redirect(url_for("settings.team_knowledges"))

    return render_template(
        "settings/edit_item.html",
        item=knowledge,
        kind="conocimiento",
        back_url=url_for("settings.team_knowledges"),
    )


@bp.route("/team/knowledges/<int:knowledge_id>/toggle", methods=["POST"])
@login_required
def toggle_team_knowledge(knowledge_id: int):
    knowledge = db.session.get(TeamKnowledge, knowledge_id)
    if not knowledge:
        abort(404)
    if knowledge.is_active:
        usage_count = _team_knowledge_usage_count(knowledge.id)
        if usage_count > 0:
            flash(f"No se puede desactivar: el conocimiento está siendo utilizado ({usage_count} referencia/s).", "danger")
            return redirect(url_for("settings.team_knowledges"))
    knowledge.is_active = not knowledge.is_active
    db.session.commit()
    flash("Estado del conocimiento actualizado.", "info")
    return redirect(url_for("settings.team_knowledges"))


@bp.route("/team/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def edit_team_role(role_id: int):
    ensure_system_team_roles()
    role = db.session.get(TeamRole, role_id)
    if not role:
        abort(404)
    if not role.is_editable:
        flash("No se puede editar: el rol es de sistema.", "danger")
        return redirect(url_for("settings.team_roles"))

    if request.method == "POST":
        name = _canonical_team_role_name(_safe_strip(request.form.get("name")))
        description = _safe_strip(request.form.get("description"))
        if len(name) < 2:
            flash("El nombre del rol es inválido.", "danger")
        elif db.session.execute(
            select(TeamRole.id).where(
                TeamRole.id != role.id,
                func.lower(TeamRole.name) == name.lower(),
            )
        ).scalar_one_or_none():
            flash("Ya existe otro rol con ese nombre.", "danger")
        else:
            role.name = name
            role.description = description
            db.session.commit()
            flash("Rol actualizado.", "success")
            return redirect(url_for("settings.team_roles"))

    return render_template(
        "settings/edit_item.html",
        item=role,
        kind="rol de equipo",
        back_url=url_for("settings.team_roles"),
    )


@bp.route("/team/roles/<int:role_id>/toggle", methods=["POST"])
@login_required
def toggle_team_role(role_id: int):
    ensure_system_team_roles()
    role = db.session.get(TeamRole, role_id)
    if not role:
        abort(404)
    if role.is_active:
        if not role.is_deletable:
            flash("No se puede desactivar: el rol es de sistema.", "danger")
            return redirect(url_for("settings.team_roles"))
        usage_count = _team_role_usage_count(role.id)
        if usage_count > 0:
            flash(f"No se puede desactivar: el rol está siendo utilizado ({usage_count} referencia/s).", "danger")
            return redirect(url_for("settings.team_roles"))
    role.is_active = not role.is_active
    db.session.commit()
    flash("Estado del rol actualizado.", "info")
    return redirect(url_for("settings.team_roles"))


@bp.route("/team/catalog/<catalog_key>", methods=["GET", "POST"])
@login_required
def team_catalog(catalog_key: str):
    _ensure_team_catalog_defaults()
    catalog_label = TEAM_CATALOG_FIELDS.get(catalog_key)
    if not catalog_label:
        abort(404)

    if request.method == "POST":
        name = _normalize_team_catalog_name(catalog_key, _safe_strip(request.form.get("name")))
        if len(name) < 2:
            flash(f"{catalog_label} debe tener al menos 2 caracteres.", "danger")
        else:
            existing = db.session.execute(
                select(SystemCatalogOptionConfig).where(
                    SystemCatalogOptionConfig.owner_user_id == g.user.id,
                    SystemCatalogOptionConfig.module_key == "team",
                    SystemCatalogOptionConfig.catalog_key == catalog_key,
                    SystemCatalogOptionConfig.name.ilike(name),
                )
            ).scalar_one_or_none()
            if existing:
                existing.is_active = True
                flash("Valor reactivado.", "success")
            else:
                db.session.add(
                    SystemCatalogOptionConfig(
                        owner_user_id=g.user.id,
                        module_key="team",
                        catalog_key=catalog_key,
                        name=name,
                        is_active=True,
                    )
                )
                flash("Valor agregado.", "success")
            db.session.commit()
        return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))

    items = db.session.execute(
        select(SystemCatalogOptionConfig)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "team",
            SystemCatalogOptionConfig.catalog_key == catalog_key,
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    usage_counts = {item.id: _team_catalog_in_use(catalog_key, item.name) for item in items}
    return render_template(
        "settings/team_catalog.html",
        items=items,
        catalog_key=catalog_key,
        catalog_label=catalog_label,
        usage_counts=usage_counts,
    )


@bp.route("/team/catalog/<catalog_key>/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_team_catalog(catalog_key: str, item_id: int):
    catalog_label = TEAM_CATALOG_FIELDS.get(catalog_key)
    if not catalog_label:
        abort(404)

    item = db.session.get(SystemCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.module_key != "team"
        or item.catalog_key != catalog_key
    ):
        abort(404)
    if not item.is_editable:
        flash("No se puede editar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))
    if catalog_key in {"resource_types", "availability_types", "availability_exception_types"} and item.is_system:
        flash("No se puede editar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))

    if request.method == "POST":
        old_name = item.name
        name = _normalize_team_catalog_name(catalog_key, _safe_strip(request.form.get("name")))
        if len(name) < 2:
            flash(f"{catalog_label} debe tener al menos 2 caracteres.", "danger")
        else:
            exists = db.session.execute(
                select(SystemCatalogOptionConfig).where(
                    SystemCatalogOptionConfig.owner_user_id == g.user.id,
                    SystemCatalogOptionConfig.module_key == "team",
                    SystemCatalogOptionConfig.catalog_key == catalog_key,
                    SystemCatalogOptionConfig.name.ilike(name),
                    SystemCatalogOptionConfig.id != item.id,
                )
            ).scalar_one_or_none()
            if exists:
                flash(f"Ya existe un valor para {catalog_label} con ese nombre.", "danger")
            else:
                item.name = name
                if catalog_key == "calendars" and old_name != name:
                    db.session.execute(
                        TeamCalendarHolidayConfig.__table__.update()
                        .where(
                            TeamCalendarHolidayConfig.owner_user_id == g.user.id,
                            TeamCalendarHolidayConfig.calendar_name == old_name,
                        )
                        .values(calendar_name=name)
                    )
                db.session.commit()
                flash("Valor actualizado.", "success")
                return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))

    if catalog_key == "calendars":
        holidays = db.session.execute(
            select(TeamCalendarHolidayConfig)
            .where(
                TeamCalendarHolidayConfig.owner_user_id == g.user.id,
                TeamCalendarHolidayConfig.calendar_name == item.name,
                TeamCalendarHolidayConfig.is_active.is_(True),
            )
            .order_by(TeamCalendarHolidayConfig.holiday_date.asc())
        ).scalars().all()
        return render_template(
            "settings/edit_team_calendar.html",
            item=item,
            kind=catalog_label,
            holidays=holidays,
            back_url=url_for("settings.team_catalog", catalog_key=catalog_key),
        )

    return render_template(
        "settings/edit_item.html",
        item=item,
        kind=catalog_label,
        back_url=url_for("settings.team_catalog", catalog_key=catalog_key),
    )


@bp.route("/team/catalog/<catalog_key>/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_team_catalog(catalog_key: str, item_id: int):
    if catalog_key not in TEAM_CATALOG_FIELDS:
        abort(404)
    item = db.session.get(SystemCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.module_key != "team"
        or item.catalog_key != catalog_key
    ):
        abort(404)
    if not item.is_deletable:
        flash("No se puede eliminar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))
    if _team_catalog_in_use(catalog_key, item.name):
        flash("No se puede eliminar: la opción está siendo utilizada.", "danger")
        return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))
    item.is_active = False
    db.session.commit()
    flash("Valor eliminado.", "info")
    return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))


@bp.route("/projects/catalog/<catalog_key>", methods=["GET", "POST"])
@login_required
def project_catalog(catalog_key: str):
    catalog_label = PROJECT_CATALOG_FIELDS.get(catalog_key)
    if not catalog_label:
        abort(404)
    seed_default_catalogs_for_user(g.user.id)
    db.session.commit()

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash(f"{catalog_label} debe tener al menos 2 caracteres.", "danger")
        else:
            existing = db.session.execute(
                select(SystemCatalogOptionConfig).where(
                    SystemCatalogOptionConfig.owner_user_id == g.user.id,
                    SystemCatalogOptionConfig.module_key == "projects",
                    SystemCatalogOptionConfig.catalog_key == catalog_key,
                    SystemCatalogOptionConfig.name.ilike(name),
                )
            ).scalar_one_or_none()
            if existing:
                existing.is_active = True
                flash("Valor reactivado.", "success")
            else:
                db.session.add(
                    SystemCatalogOptionConfig(
                        owner_user_id=g.user.id,
                        module_key="projects",
                        catalog_key=catalog_key,
                        name=name,
                        is_active=True,
                    )
                )
                flash("Valor agregado.", "success")
            db.session.commit()
        return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))

    items = db.session.execute(
        select(SystemCatalogOptionConfig)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == catalog_key,
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    usage_counts = {item.id: _project_catalog_usage_count(catalog_key, item.name) for item in items}
    return render_template(
        "settings/project_catalog.html",
        items=items,
        catalog_key=catalog_key,
        catalog_label=catalog_label,
        usage_counts=usage_counts,
    )


@bp.route("/projects/catalog/<catalog_key>/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project_catalog(catalog_key: str, item_id: int):
    catalog_label = PROJECT_CATALOG_FIELDS.get(catalog_key)
    if not catalog_label:
        abort(404)

    item = db.session.get(SystemCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.module_key != "projects"
        or item.catalog_key != catalog_key
    ):
        abort(404)
    if not item.is_editable:
        flash("No se puede editar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash(f"{catalog_label} debe tener al menos 2 caracteres.", "danger")
        else:
            exists = db.session.execute(
                select(SystemCatalogOptionConfig).where(
                    SystemCatalogOptionConfig.owner_user_id == g.user.id,
                    SystemCatalogOptionConfig.module_key == "projects",
                    SystemCatalogOptionConfig.catalog_key == catalog_key,
                    SystemCatalogOptionConfig.name.ilike(name),
                    SystemCatalogOptionConfig.id != item.id,
                )
            ).scalar_one_or_none()
            if exists:
                flash(f"Ya existe un valor para {catalog_label} con ese nombre.", "danger")
            else:
                item.name = name
                db.session.commit()
                flash("Valor actualizado.", "success")
                return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))

    return render_template(
        "settings/edit_item.html",
        item=item,
        kind=catalog_label,
        back_url=url_for("settings.project_catalog", catalog_key=catalog_key),
    )


@bp.route("/projects/catalog/<catalog_key>/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_project_catalog(catalog_key: str, item_id: int):
    if catalog_key not in PROJECT_CATALOG_FIELDS:
        abort(404)
    item = db.session.get(SystemCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.module_key != "projects"
        or item.catalog_key != catalog_key
    ):
        abort(404)
    if not item.is_deletable:
        flash("No se puede eliminar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))
    if _project_catalog_in_use(catalog_key, item.name):
        flash("No se puede eliminar: la opción está siendo utilizada.", "danger")
        return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))
    item.is_active = False
    db.session.commit()
    flash("Valor eliminado.", "info")
    return redirect(url_for("settings.project_catalog", catalog_key=catalog_key))


@bp.route("/clients")
@login_required
def clients_settings():
    return render_template("settings/clients.html", catalog_fields=CLIENT_CATALOG_FIELDS)


@bp.route("/clients/company-types", methods=["GET", "POST"])
@login_required
def company_types():
    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash("El tipo de empresa debe tener al menos 2 caracteres.", "danger")
        else:
            created = _upsert_config_item(CompanyTypeConfig, name)
            db.session.commit()
            flash(
                "Tipo de empresa creado." if created else "Tipo de empresa reactivado.",
                "success",
            )
        return redirect(url_for("settings.company_types"))

    items = _get_active_items(CompanyTypeConfig)
    return render_template("settings/client_company_types.html", items=items)


@bp.route("/clients/company-types/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_company_type(item_id: int):
    item = db.session.get(CompanyTypeConfig, item_id)
    if not item or item.owner_user_id != g.user.id:
        abort(404)
    if _company_type_in_use(item.name):
        flash("No se puede eliminar: el tipo de empresa está en uso.", "danger")
        return redirect(url_for("settings.company_types"))
    item.is_active = False
    db.session.commit()
    flash("Tipo de empresa eliminado.", "info")
    return redirect(url_for("settings.company_types"))


@bp.route("/clients/company-types/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_company_type(item_id: int):
    item = db.session.get(CompanyTypeConfig, item_id)
    if not item or item.owner_user_id != g.user.id:
        abort(404)

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash("El tipo de empresa debe tener al menos 2 caracteres.", "danger")
        elif not _validate_unique_name(CompanyTypeConfig, g.user.id, name, current_id=item.id):
            flash("Ya existe un tipo de empresa con ese nombre.", "danger")
        else:
            item.name = name
            db.session.commit()
            flash("Tipo de empresa actualizado.", "success")
            return redirect(url_for("settings.company_types"))

    return render_template("settings/edit_item.html", item=item, kind="tipo de empresa")


@bp.route("/clients/payment-types", methods=["GET", "POST"])
@login_required
def payment_types():
    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash("El tipo de pago debe tener al menos 2 caracteres.", "danger")
        else:
            created = _upsert_config_item(PaymentTypeConfig, name)
            db.session.commit()
            flash(
                "Tipo de pago creado." if created else "Tipo de pago reactivado.",
                "success",
            )
        return redirect(url_for("settings.payment_types"))

    items = _get_active_items(PaymentTypeConfig)
    return render_template("settings/client_payment_types.html", items=items)


@bp.route("/clients/payment-types/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_payment_type(item_id: int):
    item = db.session.get(PaymentTypeConfig, item_id)
    if not item or item.owner_user_id != g.user.id:
        abort(404)
    if _payment_type_in_use(item.name):
        flash("No se puede eliminar: el tipo de pago está en uso.", "danger")
        return redirect(url_for("settings.payment_types"))
    item.is_active = False
    db.session.commit()
    flash("Tipo de pago eliminado.", "info")
    return redirect(url_for("settings.payment_types"))


@bp.route("/clients/payment-types/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_payment_type(item_id: int):
    item = db.session.get(PaymentTypeConfig, item_id)
    if not item or item.owner_user_id != g.user.id:
        abort(404)

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash("El tipo de pago debe tener al menos 2 caracteres.", "danger")
        elif not _validate_unique_name(PaymentTypeConfig, g.user.id, name, current_id=item.id):
            flash("Ya existe un tipo de pago con ese nombre.", "danger")
        else:
            item.name = name
            db.session.commit()
            flash("Tipo de pago actualizado.", "success")
            return redirect(url_for("settings.payment_types"))

    return render_template("settings/edit_item.html", item=item, kind="tipo de pago")


@bp.route("/clients/catalog/<field_key>", methods=["GET", "POST"])
@login_required
def client_catalog(field_key: str):
    field_label = CLIENT_CATALOG_FIELDS.get(field_key)
    if not field_label:
        abort(404)

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash(f"{field_label} debe tener al menos 2 caracteres.", "danger")
        else:
            existing = db.session.execute(
                select(ClientCatalogOptionConfig).where(
                    ClientCatalogOptionConfig.owner_user_id == g.user.id,
                    ClientCatalogOptionConfig.field_key == field_key,
                    ClientCatalogOptionConfig.name.ilike(name),
                )
            ).scalar_one_or_none()
            if existing:
                existing.is_active = True
                flash("Valor reactivado.", "success")
            else:
                db.session.add(
                    ClientCatalogOptionConfig(
                        owner_user_id=g.user.id,
                        field_key=field_key,
                        name=name,
                        is_active=True,
                    )
                )
                flash("Valor agregado.", "success")
            db.session.commit()
        return redirect(url_for("settings.client_catalog", field_key=field_key))

    items = db.session.execute(
        select(ClientCatalogOptionConfig)
        .where(
            ClientCatalogOptionConfig.owner_user_id == g.user.id,
            ClientCatalogOptionConfig.field_key == field_key,
            ClientCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(ClientCatalogOptionConfig.name.asc())
    ).scalars()
    return render_template(
        "settings/client_catalog.html",
        items=items,
        field_key=field_key,
        field_label=field_label,
    )


@bp.route("/clients/catalog/<field_key>/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client_catalog(field_key: str, item_id: int):
    field_label = CLIENT_CATALOG_FIELDS.get(field_key)
    if not field_label:
        abort(404)

    item = db.session.get(ClientCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.field_key != field_key
    ):
        abort(404)
    if not item.is_editable:
        flash("No se puede editar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.client_catalog", field_key=field_key))

    if request.method == "POST":
        name = _safe_strip(request.form.get("name"))
        if len(name) < 2:
            flash(f"{field_label} debe tener al menos 2 caracteres.", "danger")
        else:
            exists = db.session.execute(
                select(ClientCatalogOptionConfig).where(
                    ClientCatalogOptionConfig.owner_user_id == g.user.id,
                    ClientCatalogOptionConfig.field_key == field_key,
                    ClientCatalogOptionConfig.name.ilike(name),
                    ClientCatalogOptionConfig.id != item.id,
                )
            ).scalar_one_or_none()
            if exists:
                flash(f"Ya existe un valor para {field_label} con ese nombre.", "danger")
            else:
                item.name = name
                db.session.commit()
                flash("Valor actualizado.", "success")
                return redirect(url_for("settings.client_catalog", field_key=field_key))

    return render_template(
        "settings/edit_item.html",
        item=item,
        kind=field_label,
        back_url=url_for("settings.client_catalog", field_key=field_key),
    )


@bp.route("/clients/catalog/<field_key>/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_client_catalog(field_key: str, item_id: int):
    if field_key not in CLIENT_CATALOG_FIELDS:
        abort(404)
    item = db.session.get(ClientCatalogOptionConfig, item_id)
    if (
        not item
        or item.owner_user_id != g.user.id
        or item.field_key != field_key
    ):
        abort(404)
    if not item.is_deletable:
        flash("No se puede eliminar: la opción es de sistema.", "danger")
        return redirect(url_for("settings.client_catalog", field_key=field_key))
    if _client_catalog_in_use(field_key, item.name):
        flash("No se puede eliminar: la opción está siendo utilizada.", "danger")
        return redirect(url_for("settings.client_catalog", field_key=field_key))
    item.is_active = False
    db.session.commit()
    flash("Valor eliminado.", "info")
    return redirect(url_for("settings.client_catalog", field_key=field_key))
