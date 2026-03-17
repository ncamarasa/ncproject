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
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceRole,
    SystemCatalogOptionConfig,
    Task,
    TaskDependency,
    TaskResource,
    TeamRole,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import ensure_system_team_roles


CLIENT_CATALOG_FIELDS = {
    "industry": "Rubro",
    "company_size": "Tamaño",
    "country": "País",
    "currency_code": "Moneda",
    "billing_mode": "Modalidad de facturación",
    "document_category": "Categoría de documento",
    "client_status": "Estado de cliente",
    "segment": "Segmento",
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
    "timezone": "Zona horaria",
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
    "task_dependency_types": "Tipos de dependencia",
    "risk_categories": "Categorías de riesgo",
    "project_close_reasons": "Motivos de cierre",
    "project_close_results": "Resultados de cierre",
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
    "task_dependency_types": "Gestiona tipos de dependencia entre tareas (FS, SS, FF, SF).",
    "risk_categories": "Configura categorías de riesgo para análisis y mitigación.",
    "project_close_reasons": "Define motivos de cierre del proyecto para trazabilidad de gestión.",
    "project_close_results": "Configura resultados de cierre para análisis de performance.",
}

SHARED_CLIENT_CATALOG_FIELDS_BY_MODULE = {
    "projects": {
        "currency_code": "Moneda",
        "billing_mode": "Modalidad de facturación",
    },
}

TEAM_CATALOG_FIELDS = {
    "resource_types": "Tipos de recurso",
    "availability_types": "Tipos de disponibilidad",
    "positions": "Cargos",
    "areas": "Areas",
    "vendors": "Proveedores",
}

TEAM_CATALOG_DESCRIPTIONS = {
    "resource_types": "Define los tipos de recurso para la ficha de Equipo (interno, tercerizado, etc.).",
    "availability_types": "Configura los tipos de disponibilidad para capacidad operativa (full time, part time, custom).",
    "positions": "Administra el catalogo de cargos disponibles para los recursos.",
    "areas": "Administra el catalogo de areas organizativas para clasificar recursos.",
    "vendors": "Administra el catalogo de proveedores/partners para recursos tercerizados.",
}
TEAM_ROLE_CANONICAL_NAMES = {
    "ejecutivo de cuenta": "Ejecutivo comercial",
    "ejecutivo comercial": "Ejecutivo comercial",
    "gerente de cuenta": "Account manager",
    "account manager": "Account manager",
    "delivery manager": "Responsable delivery",
    "responsable delivery": "Responsable delivery",
    "responsable tecnico": "Responsable delivery",
    "responsable técnico": "Responsable delivery",
}


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _normalize_team_catalog_name(catalog_key: str, name: str) -> str:
    if catalog_key in {"resource_types", "availability_types"}:
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
            _count_usage(Client, Client.billing_mode, name) > 0
            or _count_usage(ClientContract, ClientContract.billing_mode, name) > 0
            or _count_usage(Project, Project.billing_mode, name) > 0
        )
    if field_key == "document_category":
        return _count_usage(ClientDocument, ClientDocument.category, name) > 0
    if field_key == "client_status":
        return _count_usage(Client, Client.status, name) > 0
    if field_key == "segment":
        return _count_usage(Client, Client.segment, name) > 0
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
    if field_key == "timezone":
        return _count_usage(Client, Client.timezone, name) > 0
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
    if catalog_key == "task_dependency_types":
        return _count_usage(TaskDependency, TaskDependency.dependency_type, name) > 0
    return False


def _team_catalog_in_use(catalog_key: str, name: str) -> bool:
    if catalog_key == "resource_types":
        return _count_usage(Resource, Resource.resource_type, name) > 0
    if catalog_key == "availability_types":
        return _count_usage(ResourceAvailability, ResourceAvailability.availability_type, name) > 0
    if catalog_key == "positions":
        return _count_usage(Resource, Resource.position, name) > 0
    if catalog_key == "areas":
        return _count_usage(Resource, Resource.area, name) > 0
    if catalog_key == "vendors":
        return _count_usage(Resource, Resource.vendor_name, name) > 0
    return False


@bp.before_request
def _authorize_settings_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    needed_permission = "settings.edit" if is_write else "settings.view"
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    if not has_permission(g.user, needed_permission):
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


@bp.route("/team")
@login_required
def team_settings():
    ensure_system_team_roles()
    _ensure_team_catalog_defaults()
    return render_template(
        "settings/team.html",
        team_catalog_fields=TEAM_CATALOG_FIELDS,
        team_catalog_descriptions=TEAM_CATALOG_DESCRIPTIONS,
    )


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
    return render_template("settings/team_roles.html", roles=roles)


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
        in_use = (
            db.session.execute(select(func.count()).select_from(ResourceRole).where(ResourceRole.role_id == role.id)).scalar_one()
            + db.session.execute(select(func.count()).select_from(ProjectResource).where(ProjectResource.role_id == role.id)).scalar_one()
            + db.session.execute(select(func.count()).select_from(TaskResource).where(TaskResource.role_id == role.id)).scalar_one()
        ) > 0
        if in_use:
            flash("No se puede desactivar: el rol está siendo utilizado.", "danger")
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
    ).scalars()
    return render_template(
        "settings/team_catalog.html",
        items=items,
        catalog_key=catalog_key,
        catalog_label=catalog_label,
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

    if request.method == "POST":
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
                db.session.commit()
                flash("Valor actualizado.", "success")
                return redirect(url_for("settings.team_catalog", catalog_key=catalog_key))

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
        .order_by(SystemCatalogOptionConfig.name.asc())
    ).scalars()
    return render_template(
        "settings/project_catalog.html",
        items=items,
        catalog_key=catalog_key,
        catalog_label=catalog_label,
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
