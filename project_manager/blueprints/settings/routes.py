from flask import abort, g, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from project_manager.auth_utils import has_permission, login_required
from project_manager.blueprints.settings import bp
from project_manager.extensions import db
from project_manager.models import (
    ClientCatalogOptionConfig,
    CompanyTypeConfig,
    PaymentTypeConfig,
    SystemCatalogOptionConfig,
)


CLIENT_CATALOG_FIELDS = {
    "industry": "Rubro",
    "company_size": "Tamaño",
    "country": "País",
    "currency_code": "Moneda",
    "segment": "Segmento",
    "tax_condition": "Condición impositiva",
    "preferred_support_channel": "Canal de soporte preferido",
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


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


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
    )


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
    item.is_active = False
    db.session.commit()
    flash("Valor eliminado.", "info")
    return redirect(url_for("settings.client_catalog", field_key=field_key))
