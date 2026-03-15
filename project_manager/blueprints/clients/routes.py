import os
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import (
    allowed_client_ids,
    allowed_project_ids,
    has_permission,
    login_required,
)
from project_manager.blueprints.clients import bp
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
    UserClientAssignment,
)

CLIENT_TYPES = ["Empresa", "Gobierno", "ONG", "Startup", "Otro"]
PAYMENT_TYPES = ["Contado", "15 días", "30 días", "45 días", "60 días"]
CLIENT_STATUS_DELETED = "Eliminado"
CLIENT_STATUSES = ["Prospecto", "Activo", "En pausa", "Inactivo", CLIENT_STATUS_DELETED]
SEGMENTS = ["Enterprise", "Mid-Market", "SMB", "Publico"]
INDUSTRIES = ["Software", "Finanzas", "Salud", "Educacion", "Retail", "Manufactura"]
COMPANY_SIZES = ["Micro", "PyME", "Mediana", "Grande", "Enterprise"]
COUNTRIES = ["Argentina", "Chile", "Uruguay", "Mexico", "Colombia", "Espana"]
CURRENCIES = ["ARS", "USD", "EUR", "CLP", "UYU", "COP"]
TAX_CONDITIONS = ["Responsable Inscripto", "Monotributo", "Exento", "Consumidor Final"]
SUPPORT_CHANNELS = ["Email", "WhatsApp", "Portal", "Telefono", "Slack", "Teams"]
LANGUAGES = ["Espanol", "Ingles", "Portugues"]
COMMERCIAL_PRIORITIES = ["Baja", "Media", "Alta", "Critica"]
COMMERCIAL_STATUSES = ["Descubierto", "Calificado", "Propuesta", "Negociacion", "Ganado", "Perdido"]
RISK_LEVELS = ["Bajo", "Medio", "Alto", "Critico"]
INFLUENCE_LEVELS = ["Baja", "Media", "Alta"]
INTEREST_LEVELS = ["Bajo", "Medio", "Alto"]
CONTRACT_STATUSES = ["Borrador", "Vigente", "Vencido", "Rescindido"]
INTERACTION_TYPES = ["Nota", "Llamada", "Email", "Reunion", "Soporte", "Riesgo"]
ALLOWED_ATTACHMENT_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "png", "jpg", "jpeg", "txt"}
CONTRACT_ENDPOINTS = {
    "clients.manage_contracts",
    "clients.edit_contract",
    "clients.download_contract_attachment",
    "clients.delete_contract",
}


@bp.before_request
def _authorize_clients_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))

    endpoint = request.endpoint or ""
    module_key = "contracts" if endpoint in CONTRACT_ENDPOINTS else "clients"
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    needed_permission = f"{module_key}.edit" if is_write else f"{module_key}.view"
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    if not has_permission(g.user, needed_permission):
        flash("No tienes permisos para acceder al módulo de clientes.", "danger")
        return redirect(url_for("main.home"))


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _build_page_url(page_param: str, page_num: int) -> str:
    args = request.args.to_dict(flat=True)
    args[page_param] = page_num
    return url_for(request.endpoint, **args)


def _to_int(value: str | None):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_decimal(value: str | None):
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_bool(value: str | None) -> bool:
    return value == "1"


def _validate_choice(value: str | None, options: list[str], label: str, errors: list[str]) -> str:
    value = _safe_strip(value)
    if not value:
        return ""
    if value not in options:
        errors.append(f"{label} no es válido.")
    return value


def _active_menu_context():
    client_types = _user_config_values(CompanyTypeConfig, CLIENT_TYPES)
    payment_types = _user_config_values(PaymentTypeConfig, PAYMENT_TYPES)
    industries = _catalog_options("industry", INDUSTRIES)
    company_sizes = _catalog_options("company_size", COMPANY_SIZES)
    countries = _catalog_options("country", COUNTRIES)
    currencies = _catalog_options("currency_code", CURRENCIES)
    segments = _catalog_options("segment", SEGMENTS)
    tax_conditions = _catalog_options("tax_condition", TAX_CONDITIONS)
    support_channels = _catalog_options("preferred_support_channel", SUPPORT_CHANNELS)
    languages = _catalog_options("language", LANGUAGES)
    return {
        "client_types": client_types,
        "payment_types": payment_types,
        "industries": industries,
        "company_sizes": company_sizes,
        "countries": countries,
        "currencies": currencies,
        "segments": segments,
        "tax_conditions": tax_conditions,
        "support_channels": support_channels,
        "languages": languages,
        "client_statuses": CLIENT_STATUSES,
        "commercial_priorities": COMMERCIAL_PRIORITIES,
        "commercial_statuses": COMMERCIAL_STATUSES,
        "risk_levels": RISK_LEVELS,
        "influence_levels": INFLUENCE_LEVELS,
        "interest_levels": INTEREST_LEVELS,
        "contract_statuses": CONTRACT_STATUSES,
        "interaction_types": INTERACTION_TYPES,
    }


def _user_config_values(model, fallback: list[str]):
    if not g.user:
        return fallback
    values = db.session.execute(
        select(model.name)
        .where(model.owner_user_id == g.user.id, model.is_active.is_(True))
        .order_by(model.name.asc())
    ).scalars().all()
    return values or fallback


def _catalog_options(field_key: str, fallback: list[str]):
    if not g.user:
        return fallback
    values = db.session.execute(
        select(ClientCatalogOptionConfig.name)
        .where(
            ClientCatalogOptionConfig.owner_user_id == g.user.id,
            ClientCatalogOptionConfig.field_key == field_key,
            ClientCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(ClientCatalogOptionConfig.name.asc())
    ).scalars().all()
    return values or fallback


def _load_client_or_404(client_id: int) -> Client:
    if client_id and not g.user.full_access and g.user.username != "admin":
        allowed_ids = allowed_client_ids(g.user)
        if allowed_ids is not None and client_id not in set(allowed_ids):
            abort(403)

    stmt = (
        select(Client)
        .options(
            selectinload(Client.contacts),
            selectinload(Client.contracts),
            selectinload(Client.documents),
            selectinload(Client.interactions),
        )
        .where(Client.id == client_id)
    )
    client = db.session.execute(stmt).scalar_one_or_none()
    if not client:
        abort(404)
    return client


def _has_allowed_attachment_extension(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_ATTACHMENT_EXTENSIONS


def _save_attachment(file_storage, upload_folder: str):
    if not file_storage or not file_storage.filename:
        return None, None, None

    original_name = secure_filename(file_storage.filename)
    if not original_name or not _has_allowed_attachment_extension(original_name):
        return None, None, "Formato de archivo no permitido."

    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{ext}"
    os.makedirs(upload_folder, exist_ok=True)
    file_storage.save(os.path.join(upload_folder, stored_name))
    return stored_name, original_name, None


def _delete_stored_file(upload_folder: str, file_name: str | None):
    if not file_name:
        return
    path = os.path.join(upload_folder, file_name)
    if os.path.exists(path):
        os.remove(path)


def _validate_client_form(
    form,
    client_id: int | None = None,
    *,
    client_type_options: list[str],
    payment_type_options: list[str],
    industry_options: list[str],
    company_size_options: list[str],
    country_options: list[str],
    currency_options: list[str],
    segment_options: list[str],
    tax_condition_options: list[str],
    support_channel_options: list[str],
    language_options: list[str],
):
    errors = []

    name = _safe_strip(form.get("name"))
    contact_name = _safe_strip(form.get("contact_name"))
    email = _safe_strip(form.get("email"))
    phone = _safe_strip(form.get("phone"))
    notes = _safe_strip(form.get("notes"))

    legal_name = _safe_strip(form.get("legal_name"))
    trade_name = _safe_strip(form.get("trade_name"))
    tax_id = _safe_strip(form.get("tax_id"))
    client_type = _validate_choice(
        form.get("client_type"), client_type_options, "Tipo de cliente", errors
    )
    status = _validate_choice(form.get("status"), CLIENT_STATUSES, "Estado de cliente", errors)
    industry = _validate_choice(form.get("industry"), industry_options, "Rubro", errors)
    company_size = _validate_choice(form.get("company_size"), company_size_options, "Tamaño", errors)
    country = _validate_choice(form.get("country"), country_options, "País", errors)
    region = _safe_strip(form.get("region"))
    city = _safe_strip(form.get("city"))
    address = _safe_strip(form.get("address"))
    website = _safe_strip(form.get("website"))
    currency_code = _validate_choice(form.get("currency_code"), currency_options, "Moneda", errors)
    onboarding_date = _parse_date(form.get("onboarding_date"))
    observations = _safe_strip(form.get("observations"))

    lead_source = _safe_strip(form.get("lead_source"))
    segment = _validate_choice(form.get("segment"), segment_options, "Segmento", errors)
    commercial_priority = _validate_choice(
        form.get("commercial_priority"), COMMERCIAL_PRIORITIES, "Prioridad comercial", errors
    )
    sales_executive = _safe_strip(form.get("sales_executive"))
    account_manager = _safe_strip(form.get("account_manager"))
    commercial_status = _validate_choice(
        form.get("commercial_status"), COMMERCIAL_STATUSES, "Estado comercial", errors
    )
    billing_potential = _to_decimal(form.get("billing_potential"))
    health_score = _to_int(form.get("health_score"))
    risk_level = _validate_choice(form.get("risk_level"), RISK_LEVELS, "Riesgo", errors)
    last_interaction_at = _parse_date(form.get("last_interaction_at"))
    next_action_at = _parse_date(form.get("next_action_at"))

    tax_condition = _validate_choice(
        form.get("tax_condition"), tax_condition_options, "Condición impositiva", errors
    )
    fiscal_address = _safe_strip(form.get("fiscal_address"))
    billing_email = _safe_strip(form.get("billing_email"))
    payment_terms = _validate_choice(
        form.get("payment_terms"), payment_type_options, "Condición de pago", errors
    )
    purchase_order_required = _to_bool(form.get("purchase_order_required"))
    rate_card = _safe_strip(form.get("rate_card"))
    credit_limit = _to_decimal(form.get("credit_limit"))

    methodology = _safe_strip(form.get("methodology"))
    preferred_support_channel = _validate_choice(
        form.get("preferred_support_channel"),
        support_channel_options,
        "Canal de soporte preferido",
        errors,
    )
    support_hours = _safe_strip(form.get("support_hours"))
    timezone = _safe_strip(form.get("timezone"))
    language = _validate_choice(form.get("language"), language_options, "Idioma", errors)
    delivery_manager = _safe_strip(form.get("delivery_manager"))
    criticality_level = _validate_choice(form.get("criticality_level"), RISK_LEVELS, "Criticidad", errors)
    service_type = _safe_strip(form.get("service_type"))
    billing_mode = _safe_strip(form.get("billing_mode"))
    default_rate = _to_decimal(form.get("default_rate"))
    contracted_hours = _to_decimal(form.get("contracted_hours"))
    approval_flow = _safe_strip(form.get("approval_flow"))

    if len(name) < 2:
        errors.append("El nombre del cliente debe tener al menos 2 caracteres.")

    if tax_id:
        tax_id_exists_stmt = select(Client).where(func.lower(Client.tax_id) == tax_id.lower())
        if client_id:
            tax_id_exists_stmt = tax_id_exists_stmt.where(Client.id != client_id)
        tax_id_exists = db.session.execute(tax_id_exists_stmt).scalar_one_or_none()
        if tax_id_exists:
            errors.append("Ya existe un cliente con ese CUIT/Tax ID.")

    name_exists_stmt = select(Client).where(func.lower(Client.name) == name.lower())
    if client_id:
        name_exists_stmt = name_exists_stmt.where(Client.id != client_id)
    name_exists = db.session.execute(name_exists_stmt).scalar_one_or_none()
    if name_exists:
        errors.append("Ya existe un cliente con ese nombre.")

    if health_score is not None and not 0 <= health_score <= 100:
        errors.append("El health score debe estar entre 0 y 100.")

    if billing_potential is None and _safe_strip(form.get("billing_potential")):
        errors.append("Potencial de facturación inválido.")
    if credit_limit is None and _safe_strip(form.get("credit_limit")):
        errors.append("Límite de crédito inválido.")
    if default_rate is None and _safe_strip(form.get("default_rate")):
        errors.append("Tarifa por defecto inválida.")
    if contracted_hours is None and _safe_strip(form.get("contracted_hours")):
        errors.append("Horas contratadas inválidas.")

    if last_interaction_at and next_action_at and last_interaction_at > next_action_at:
        errors.append("La próxima acción no puede ser anterior a la última interacción.")

    return {
        "errors": errors,
        "payload": {
            "name": name,
            "contact_name": contact_name,
            "email": email,
            "phone": phone,
            "notes": notes,
            "legal_name": legal_name,
            "trade_name": trade_name,
            "tax_id": tax_id,
            "client_type": client_type,
            "status": status,
            "industry": industry,
            "company_size": company_size,
            "country": country,
            "region": region,
            "city": city,
            "address": address,
            "website": website,
            "currency_code": currency_code,
            "onboarding_date": onboarding_date,
            "observations": observations,
            "lead_source": lead_source,
            "segment": segment,
            "commercial_priority": commercial_priority,
            "sales_executive": sales_executive,
            "account_manager": account_manager,
            "commercial_status": commercial_status,
            "billing_potential": billing_potential,
            "health_score": health_score,
            "risk_level": risk_level,
            "last_interaction_at": last_interaction_at,
            "next_action_at": next_action_at,
            "tax_condition": tax_condition,
            "fiscal_address": fiscal_address,
            "billing_email": billing_email,
            "payment_terms": payment_terms,
            "purchase_order_required": purchase_order_required,
            "rate_card": rate_card,
            "credit_limit": credit_limit,
            "methodology": methodology,
            "preferred_support_channel": preferred_support_channel,
            "support_hours": support_hours,
            "timezone": timezone,
            "language": language,
            "delivery_manager": delivery_manager,
            "criticality_level": criticality_level,
            "service_type": service_type,
            "billing_mode": billing_mode,
            "default_rate": default_rate,
            "contracted_hours": contracted_hours,
            "approval_flow": approval_flow,
        },
    }


@bp.route("/")
@login_required
def list_clients():
    page = _to_int(request.args.get("page")) or 1
    search = _safe_strip(request.args.get("q"))
    active = _safe_strip(request.args.get("active", "all"))
    status = _safe_strip(request.args.get("status"))
    segment = _safe_strip(request.args.get("segment"))
    risk = _safe_strip(request.args.get("risk"))

    stmt = select(Client).order_by(Client.updated_at.desc())
    allowed_ids = allowed_client_ids(g.user)
    if allowed_ids is not None:
        stmt = stmt.where(Client.id.in_(allowed_ids))

    if search:
        token = f"%{search}%"
        stmt = stmt.where(
            or_(
                Client.name.ilike(token),
                Client.legal_name.ilike(token),
                Client.trade_name.ilike(token),
                Client.tax_id.ilike(token),
                Client.contact_name.ilike(token),
                Client.email.ilike(token),
            )
        )

    if active in {"1", "0"}:
        stmt = stmt.where(Client.is_active.is_(active == "1"))
    if status:
        stmt = stmt.where(Client.status == status)
    if segment:
        stmt = stmt.where(Client.segment == segment)
    if risk:
        stmt = stmt.where(Client.risk_level == risk)

    clients_pagination = db.paginate(stmt, page=page, per_page=10, error_out=False)

    return render_template(
        "clients/client_list.html",
        clients=clients_pagination.items,
        clients_pagination=clients_pagination,
        build_page_url=_build_page_url,
        filters={
            "q": search,
            "active": active,
            "status": status,
            "segment": segment,
            "risk": risk,
        },
        **_active_menu_context(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_client():
    if request.method == "POST":
        result = _validate_client_form(
            request.form,
            client_type_options=_user_config_values(CompanyTypeConfig, CLIENT_TYPES),
            payment_type_options=_user_config_values(PaymentTypeConfig, PAYMENT_TYPES),
            industry_options=_catalog_options("industry", INDUSTRIES),
            company_size_options=_catalog_options("company_size", COMPANY_SIZES),
            country_options=_catalog_options("country", COUNTRIES),
            currency_options=_catalog_options("currency_code", CURRENCIES),
            segment_options=_catalog_options("segment", SEGMENTS),
            tax_condition_options=_catalog_options("tax_condition", TAX_CONDITIONS),
            support_channel_options=_catalog_options("preferred_support_channel", SUPPORT_CHANNELS),
            language_options=_catalog_options("language", LANGUAGES),
        )
        errors = result["errors"]

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "clients/client_form.html",
                client=None,
                form_values=request.form,
                is_edit=False,
                **_active_menu_context(),
            )

        client = Client(**result["payload"])
        db.session.add(client)
        db.session.flush()
        if g.user and not g.user.full_access and g.user.username != "admin":
            assigned = db.session.execute(
                select(UserClientAssignment.id).where(
                    UserClientAssignment.user_id == g.user.id,
                    UserClientAssignment.client_id == client.id,
                )
            ).scalar_one_or_none()
            if not assigned:
                db.session.add(UserClientAssignment(user_id=g.user.id, client_id=client.id))
        db.session.commit()

        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("clients.client_detail", client_id=client.id))

    return render_template(
        "clients/client_form.html",
        client=None,
        form_values={},
        is_edit=False,
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>")
@login_required
def client_detail(client_id: int):
    client = _load_client_or_404(client_id)

    contacts_page = _to_int(request.args.get("contacts_page")) or 1
    contracts_page = _to_int(request.args.get("contracts_page")) or 1
    documents_page = _to_int(request.args.get("documents_page")) or 1
    interactions_page = _to_int(request.args.get("interactions_page")) or 1
    projects_page = _to_int(request.args.get("projects_page")) or 1

    contacts_pagination = db.paginate(
        select(ClientContact).where(ClientContact.client_id == client.id).order_by(ClientContact.created_at.desc()),
        page=contacts_page,
        per_page=8,
        error_out=False,
    )
    contracts_pagination = db.paginate(
        select(ClientContract).where(ClientContract.client_id == client.id).order_by(ClientContract.created_at.desc()),
        page=contracts_page,
        per_page=6,
        error_out=False,
    )
    documents_pagination = db.paginate(
        select(ClientDocument).where(ClientDocument.client_id == client.id).order_by(ClientDocument.created_at.desc()),
        page=documents_page,
        per_page=6,
        error_out=False,
    )
    interactions_pagination = db.paginate(
        select(ClientInteraction)
        .where(ClientInteraction.client_id == client.id)
        .order_by(ClientInteraction.interaction_date.desc()),
        page=interactions_page,
        per_page=8,
        error_out=False,
    )
    project_stmt = select(Project).where(Project.client_id == client.id).order_by(Project.updated_at.desc())
    allowed_projects = allowed_project_ids(g.user)
    if allowed_projects is not None:
        project_stmt = project_stmt.where(Project.id.in_(allowed_projects))
    projects_pagination = db.paginate(
        project_stmt,
        page=projects_page,
        per_page=8,
        error_out=False,
    )

    stats = {
        "active_projects": db.session.execute(
            select(func.count(Project.id)).where(Project.client_id == client.id, Project.is_active.is_(True))
        ).scalar_one(),
        "contacts": db.session.execute(
            select(func.count(ClientContact.id)).where(ClientContact.client_id == client.id)
        ).scalar_one(),
        "contracts": db.session.execute(
            select(func.count(ClientContract.id)).where(ClientContract.client_id == client.id)
        ).scalar_one(),
        "documents": db.session.execute(
            select(func.count(ClientDocument.id)).where(ClientDocument.client_id == client.id)
        ).scalar_one(),
        "interactions": db.session.execute(
            select(func.count(ClientInteraction.id)).where(ClientInteraction.client_id == client.id)
        ).scalar_one(),
    }

    return render_template(
        "clients/client_detail.html",
        client=client,
        contacts=contacts_pagination.items,
        contracts=contracts_pagination.items,
        documents=documents_pagination.items,
        interactions=interactions_pagination.items,
        projects=projects_pagination.items,
        contacts_pagination=contacts_pagination,
        contracts_pagination=contracts_pagination,
        documents_pagination=documents_pagination,
        interactions_pagination=interactions_pagination,
        projects_pagination=projects_pagination,
        build_page_url=_build_page_url,
        stats=stats,
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)

    if request.method == "POST":
        result = _validate_client_form(
            request.form,
            client_id=client.id,
            client_type_options=_user_config_values(CompanyTypeConfig, CLIENT_TYPES),
            payment_type_options=_user_config_values(PaymentTypeConfig, PAYMENT_TYPES),
            industry_options=_catalog_options("industry", INDUSTRIES),
            company_size_options=_catalog_options("company_size", COMPANY_SIZES),
            country_options=_catalog_options("country", COUNTRIES),
            currency_options=_catalog_options("currency_code", CURRENCIES),
            segment_options=_catalog_options("segment", SEGMENTS),
            tax_condition_options=_catalog_options("tax_condition", TAX_CONDITIONS),
            support_channel_options=_catalog_options("preferred_support_channel", SUPPORT_CHANNELS),
            language_options=_catalog_options("language", LANGUAGES),
        )
        errors = result["errors"]
        is_active = _to_bool(request.form.get("is_active"))

        active_projects = db.session.execute(
            select(func.count(Project.id)).where(Project.client_id == client.id, Project.is_active.is_(True))
        ).scalar_one()
        if not is_active and active_projects > 0:
            errors.append("No puedes dar de baja un cliente con proyectos activos.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "clients/client_form.html",
                client=client,
                form_values=request.form,
                is_edit=True,
                **_active_menu_context(),
            )

        for key, value in result["payload"].items():
            setattr(client, key, value)
        client.is_active = is_active

        db.session.commit()

        flash("Cliente actualizado correctamente.", "success")
        return redirect(url_for("clients.client_detail", client_id=client.id))

    return render_template(
        "clients/client_form.html",
        client=client,
        form_values={},
        is_edit=True,
        **_active_menu_context(),
    )


def _contact_payload_from_form(form):
    errors = []
    full_name = _safe_strip(form.get("full_name"))
    if len(full_name) < 2:
        errors.append("El contacto debe tener nombre válido.")

    payload = {
        "full_name": full_name,
        "job_title": _safe_strip(form.get("job_title")),
        "area": _safe_strip(form.get("area")),
        "email": _safe_strip(form.get("email")),
        "phone": _safe_strip(form.get("phone")),
        "whatsapp": _safe_strip(form.get("whatsapp")),
        "relationship_role": _safe_strip(form.get("relationship_role")),
        "influence_level": _validate_choice(form.get("influence_level"), INFLUENCE_LEVELS, "Influencia", []),
        "interest_level": _validate_choice(form.get("interest_level"), INTEREST_LEVELS, "Interés", []),
        "is_primary": _to_bool(form.get("is_primary")),
        "is_technical": _to_bool(form.get("is_technical")),
        "is_administrative": _to_bool(form.get("is_administrative")),
        "is_billing": _to_bool(form.get("is_billing")),
        "notes": _safe_strip(form.get("notes")),
    }
    return payload, errors


@bp.route("/<int:client_id>/contacts", methods=["GET", "POST"])
@login_required
def manage_contacts(client_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    edit_id = _to_int(request.args.get("edit_id"))
    edit_contact = None
    if edit_id:
        edit_contact = db.session.get(ClientContact, edit_id)
        if not edit_contact or edit_contact.client_id != client.id:
            edit_contact = None

    if request.method == "POST":
        payload, errors = _contact_payload_from_form(request.form)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            contact = ClientContact(client_id=client.id, **payload)
            if contact.is_primary:
                db.session.execute(
                    update(ClientContact)
                    .where(ClientContact.client_id == client.id, ClientContact.is_primary.is_(True))
                    .values(is_primary=False)
                )
            db.session.add(contact)
            db.session.commit()
            flash("Contacto agregado.", "success")
            return redirect(url_for("clients.manage_contacts", client_id=client.id, page=page))

    contacts_pagination = db.paginate(
        select(ClientContact).where(ClientContact.client_id == client.id).order_by(ClientContact.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_contacts.html",
        client=client,
        contacts=contacts_pagination.items,
        contacts_pagination=contacts_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_contact=edit_contact,
        form_values={},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contact(client_id: int, contact_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    contact = db.session.get(ClientContact, contact_id)
    if not contact or contact.client_id != client.id:
        abort(404)

    if request.method == "POST":
        payload, errors = _contact_payload_from_form(request.form)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(contact, key, value)
            if contact.is_primary:
                db.session.execute(
                    update(ClientContact)
                    .where(
                        ClientContact.client_id == client.id,
                        ClientContact.id != contact.id,
                        ClientContact.is_primary.is_(True),
                    )
                    .values(is_primary=False)
                )
            db.session.commit()
            flash("Contacto actualizado.", "success")
            return redirect(url_for("clients.manage_contacts", client_id=client.id, page=page))

    contacts_pagination = db.paginate(
        select(ClientContact).where(ClientContact.client_id == client.id).order_by(ClientContact.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_contacts.html",
        client=client,
        contacts=contacts_pagination.items,
        contacts_pagination=contacts_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_contact=contact,
        form_values=request.form if request.method == "POST" else {},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/contacts/<int:contact_id>/delete", methods=["POST"])
@login_required
def delete_contact(client_id: int, contact_id: int):
    page = _to_int(request.args.get("page")) or 1
    contact = db.session.get(ClientContact, contact_id)
    if not contact or contact.client_id != client_id:
        abort(404)
    db.session.delete(contact)
    db.session.commit()
    flash("Contacto eliminado.", "info")
    return redirect(url_for("clients.manage_contacts", client_id=client_id, page=page))


def _contract_payload_from_form(form, files, *, require_attachment: bool = False):
    errors = []
    contract_type = _safe_strip(form.get("contract_type"))
    if not contract_type:
        errors.append("Debes indicar tipo de contrato.")
    contract_name = _safe_strip(form.get("contract_name"))

    start_date = _parse_date(form.get("start_date"))
    end_date = _parse_date(form.get("end_date"))
    renewal_date = _parse_date(form.get("renewal_date"))
    if start_date and end_date and start_date > end_date:
        errors.append("La fecha de inicio no puede ser mayor a la de fin.")

    upload_folder = current_app.config["CLIENT_CONTRACT_UPLOAD_FOLDER"]
    file_name, original_name, file_error = _save_attachment(files.get("attachment"), upload_folder)
    if file_error:
        errors.append(file_error)
    if require_attachment and not file_name:
        errors.append("Debes adjuntar un archivo de contrato.")

    status = _validate_choice(form.get("status"), CONTRACT_STATUSES, "Estado de contrato", errors)
    payload = {
        "contract_type": contract_type,
        "contract_code": _safe_strip(form.get("contract_code")),
        "contract_name": contract_name,
        "start_date": start_date,
        "end_date": end_date,
        "auto_renewal": _to_bool(form.get("auto_renewal")),
        "renewal_date": renewal_date,
        "sla_level": _safe_strip(form.get("sla_level")),
        "nda_signed": _to_bool(form.get("nda_signed")),
        "data_processing_agreement": _to_bool(form.get("data_processing_agreement")),
        "status": status,
        "billing_mode": _safe_strip(form.get("billing_mode")),
        "currency_code": _safe_strip(form.get("currency_code")),
        "amount": _to_decimal(form.get("amount")),
        "notes": _safe_strip(form.get("notes")),
    }
    return payload, file_name, original_name, errors


@bp.route("/<int:client_id>/contracts", methods=["GET", "POST"])
@login_required
def manage_contracts(client_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    if request.method == "POST":
        payload, file_name, original_name, errors = _contract_payload_from_form(
            request.form, request.files, require_attachment=False
        )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            contract = ClientContract(
                client_id=client.id,
                attachment_file_name=file_name,
                attachment_original_name=original_name,
                **payload,
            )
            db.session.add(contract)
            db.session.commit()
            flash("Contrato agregado.", "success")
            return redirect(url_for("clients.manage_contracts", client_id=client.id, page=page))

    contracts_pagination = db.paginate(
        select(ClientContract).where(ClientContract.client_id == client.id).order_by(ClientContract.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_contracts.html",
        client=client,
        contracts=contracts_pagination.items,
        contracts_pagination=contracts_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_contract=None,
        form_values={},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/contracts/<int:contract_id>/edit", methods=["GET", "POST"])
@login_required
def edit_contract(client_id: int, contract_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    contract = db.session.get(ClientContract, contract_id)
    if not contract or contract.client_id != client.id:
        abort(404)

    if request.method == "POST":
        payload, new_file_name, new_original_name, errors = _contract_payload_from_form(
            request.form, request.files, require_attachment=False
        )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(contract, key, value)
            if new_file_name:
                _delete_stored_file(current_app.config["CLIENT_CONTRACT_UPLOAD_FOLDER"], contract.attachment_file_name)
                contract.attachment_file_name = new_file_name
                contract.attachment_original_name = new_original_name
            db.session.commit()
            flash("Contrato actualizado.", "success")
            return redirect(url_for("clients.manage_contracts", client_id=client.id, page=page))

    contracts_pagination = db.paginate(
        select(ClientContract).where(ClientContract.client_id == client.id).order_by(ClientContract.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_contracts.html",
        client=client,
        contracts=contracts_pagination.items,
        contracts_pagination=contracts_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_contract=contract,
        form_values=request.form if request.method == "POST" else {},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/contracts/<int:contract_id>/download")
@login_required
def download_contract_attachment(client_id: int, contract_id: int):
    contract = db.session.get(ClientContract, contract_id)
    if not contract or contract.client_id != client_id or not contract.attachment_file_name:
        abort(404)
    return send_from_directory(
        current_app.config["CLIENT_CONTRACT_UPLOAD_FOLDER"],
        contract.attachment_file_name,
        as_attachment=True,
        download_name=contract.attachment_original_name or contract.attachment_file_name,
    )


@bp.route("/<int:client_id>/contracts/<int:contract_id>/delete", methods=["POST"])
@login_required
def delete_contract(client_id: int, contract_id: int):
    page = _to_int(request.args.get("page")) or 1
    contract = db.session.get(ClientContract, contract_id)
    if not contract or contract.client_id != client_id:
        abort(404)

    _delete_stored_file(current_app.config["CLIENT_CONTRACT_UPLOAD_FOLDER"], contract.attachment_file_name)
    db.session.delete(contract)
    db.session.commit()
    flash("Contrato eliminado.", "info")
    return redirect(url_for("clients.manage_contracts", client_id=client_id, page=page))


def _document_payload_from_form(form, files, *, require_file: bool):
    errors = []
    title = _safe_strip(form.get("title"))
    if len(title) < 2:
        errors.append("Debes indicar un título para el documento.")

    upload_folder = current_app.config["CLIENT_DOCUMENT_UPLOAD_FOLDER"]
    file_name, original_name, file_error = _save_attachment(files.get("file"), upload_folder)
    if file_error:
        errors.append(file_error)
    if require_file and not file_name:
        errors.append("Debes adjuntar un archivo.")

    payload = {
        "title": title,
        "category": _safe_strip(form.get("category")),
        "expires_on": _parse_date(form.get("expires_on")),
        "uploaded_by": _safe_strip(form.get("uploaded_by")),
        "notes": _safe_strip(form.get("notes")),
    }
    return payload, file_name, original_name, errors


@bp.route("/<int:client_id>/documents", methods=["GET", "POST"])
@login_required
def manage_documents(client_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    if request.method == "POST":
        payload, file_name, original_name, errors = _document_payload_from_form(
            request.form, request.files, require_file=True
        )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            document = ClientDocument(
                client_id=client.id,
                file_name=file_name,
                original_name=original_name,
                **payload,
            )
            db.session.add(document)
            db.session.commit()
            flash("Documento agregado.", "success")
            return redirect(url_for("clients.manage_documents", client_id=client.id, page=page))

    documents_pagination = db.paginate(
        select(ClientDocument).where(ClientDocument.client_id == client.id).order_by(ClientDocument.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_documents.html",
        client=client,
        documents=documents_pagination.items,
        documents_pagination=documents_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_document=None,
        form_values={},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/documents/<int:document_id>/edit", methods=["GET", "POST"])
@login_required
def edit_document(client_id: int, document_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    document = db.session.get(ClientDocument, document_id)
    if not document or document.client_id != client.id:
        abort(404)

    if request.method == "POST":
        payload, new_file_name, new_original_name, errors = _document_payload_from_form(
            request.form, request.files, require_file=False
        )
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(document, key, value)
            if new_file_name:
                _delete_stored_file(current_app.config["CLIENT_DOCUMENT_UPLOAD_FOLDER"], document.file_name)
                document.file_name = new_file_name
                document.original_name = new_original_name
            db.session.commit()
            flash("Documento actualizado.", "success")
            return redirect(url_for("clients.manage_documents", client_id=client.id, page=page))

    documents_pagination = db.paginate(
        select(ClientDocument).where(ClientDocument.client_id == client.id).order_by(ClientDocument.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_documents.html",
        client=client,
        documents=documents_pagination.items,
        documents_pagination=documents_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_document=document,
        form_values=request.form if request.method == "POST" else {},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/documents/<int:document_id>/download")
@login_required
def download_document(client_id: int, document_id: int):
    document = db.session.get(ClientDocument, document_id)
    if not document or document.client_id != client_id:
        abort(404)

    return send_from_directory(
        current_app.config["CLIENT_DOCUMENT_UPLOAD_FOLDER"],
        document.file_name,
        as_attachment=True,
        download_name=document.original_name,
    )


@bp.route("/<int:client_id>/documents/<int:document_id>/delete", methods=["POST"])
@login_required
def delete_document(client_id: int, document_id: int):
    page = _to_int(request.args.get("page")) or 1
    document = db.session.get(ClientDocument, document_id)
    if not document or document.client_id != client_id:
        abort(404)

    _delete_stored_file(current_app.config["CLIENT_DOCUMENT_UPLOAD_FOLDER"], document.file_name)
    db.session.delete(document)
    db.session.commit()
    flash("Documento eliminado.", "info")
    return redirect(url_for("clients.manage_documents", client_id=client_id, page=page))


def _interaction_payload_from_form(form):
    errors = []
    interaction_type = _validate_choice(
        form.get("interaction_type"), INTERACTION_TYPES, "Tipo de interacción", errors
    )
    subject = _safe_strip(form.get("subject"))
    interaction_date = _parse_date(form.get("interaction_date"))
    next_action_date = _parse_date(form.get("next_action_date"))
    risk_level = _validate_choice(form.get("risk_level"), RISK_LEVELS, "Riesgo", errors)

    if len(subject) < 3:
        errors.append("El asunto debe tener al menos 3 caracteres.")
    if not interaction_date:
        errors.append("Debes indicar fecha de interacción.")
    if interaction_date and next_action_date and interaction_date > next_action_date:
        errors.append("La próxima acción no puede ser anterior a la interacción.")

    payload = {
        "interaction_type": interaction_type,
        "subject": subject,
        "description": _safe_strip(form.get("description")),
        "interaction_date": interaction_date,
        "next_action_date": next_action_date,
        "owner": _safe_strip(form.get("owner")),
        "risk_level": risk_level,
    }
    return payload, errors


@bp.route("/<int:client_id>/interactions", methods=["GET", "POST"])
@login_required
def manage_interactions(client_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    if request.method == "POST":
        payload, errors = _interaction_payload_from_form(request.form)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            interaction = ClientInteraction(client_id=client.id, **payload)
            db.session.add(interaction)
            client.last_interaction_at = payload["interaction_date"]
            if payload["next_action_date"]:
                client.next_action_at = payload["next_action_date"]
            db.session.commit()
            flash("Interacción registrada.", "success")
            return redirect(url_for("clients.manage_interactions", client_id=client.id, page=page))

    interactions_pagination = db.paginate(
        select(ClientInteraction)
        .where(ClientInteraction.client_id == client.id)
        .order_by(ClientInteraction.interaction_date.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_interactions.html",
        client=client,
        interactions=interactions_pagination.items,
        interactions_pagination=interactions_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_interaction=None,
        form_values={},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/interactions/<int:interaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_interaction(client_id: int, interaction_id: int):
    client = _load_client_or_404(client_id)
    page = _to_int(request.args.get("page")) or 1
    interaction = db.session.get(ClientInteraction, interaction_id)
    if not interaction or interaction.client_id != client.id:
        abort(404)

    if request.method == "POST":
        payload, errors = _interaction_payload_from_form(request.form)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(interaction, key, value)
            client.last_interaction_at = payload["interaction_date"]
            if payload["next_action_date"]:
                client.next_action_at = payload["next_action_date"]
            db.session.commit()
            flash("Interacción actualizada.", "success")
            return redirect(url_for("clients.manage_interactions", client_id=client.id, page=page))

    interactions_pagination = db.paginate(
        select(ClientInteraction)
        .where(ClientInteraction.client_id == client.id)
        .order_by(ClientInteraction.interaction_date.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "clients/client_interactions.html",
        client=client,
        interactions=interactions_pagination.items,
        interactions_pagination=interactions_pagination,
        current_page=page,
        build_page_url=_build_page_url,
        edit_interaction=interaction,
        form_values=request.form if request.method == "POST" else {},
        **_active_menu_context(),
    )


@bp.route("/<int:client_id>/interactions/<int:interaction_id>/delete", methods=["POST"])
@login_required
def delete_interaction(client_id: int, interaction_id: int):
    page = _to_int(request.args.get("page")) or 1
    interaction = db.session.get(ClientInteraction, interaction_id)
    if not interaction or interaction.client_id != client_id:
        abort(404)

    db.session.delete(interaction)
    db.session.commit()
    flash("Interacción eliminada.", "info")
    return redirect(url_for("clients.manage_interactions", client_id=client_id, page=page))


@bp.route("/<int:client_id>/delete", methods=["POST"])
@login_required
def delete_client(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)

    if not client.is_active and client.status == CLIENT_STATUS_DELETED:
        flash("El cliente ya está marcado como eliminado.", "info")
        return redirect(url_for("clients.edit_client", client_id=client.id))

    related_projects = db.session.execute(
        select(func.count(Project.id)).where(Project.client_id == client.id)
    ).scalar_one()
    related_contracts = db.session.execute(
        select(func.count(ClientContract.id)).where(ClientContract.client_id == client.id)
    ).scalar_one()

    if related_projects > 0 or related_contracts > 0:
        flash(
            "No puedes eliminar este cliente porque tiene proyectos o contratos asociados.",
            "warning",
        )
        return redirect(url_for("clients.edit_client", client_id=client.id))

    client.is_active = False
    client.status = CLIENT_STATUS_DELETED
    db.session.commit()
    flash("Cliente marcado como eliminado (baja lógica).", "info")
    return redirect(url_for("clients.list_clients"))
