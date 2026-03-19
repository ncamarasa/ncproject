from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import has_permission, login_required
from project_manager.blueprints.team import bp
from project_manager.extensions import db
from project_manager.models import (
    Client,
    ClientCatalogOptionConfig,
    Project,
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceAvailabilityException,
    ResourceCost,
    ResourceRole,
    SystemCatalogOptionConfig,
    Task,
    TaskResource,
    TeamRole,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import (
    calculate_resource_net_availability,
    close_previous_cost_if_needed,
    ensure_system_team_roles,
    estimate_planned_daily_hours,
    find_applicable_cost_id,
    normalize_email,
    normalize_working_days,
    resource_cost_usage_count,
    sync_resource_full_name,
    validate_assignment,
    validate_availability_payload,
    validate_availability_exception_payload,
    validate_cost_payload,
    validate_resource_payload,
    validate_task_assignment_project_consistency,
)
from project_manager.utils.dates import parse_date_input
from urllib.parse import urlsplit


@bp.before_request
def _authorize_team_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    needed_permission = "team.edit" if is_write else "team.view"
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    if not has_permission(g.user, needed_permission):
        flash("No tienes permisos para acceder al módulo de equipo.", "danger")
        return redirect(url_for("main.home"))
    ensure_system_team_roles()


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _to_int(value: str | None):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_decimal(value: str | None):
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


_parse_date = parse_date_input


def _to_bool(value: str | None) -> bool:
    return value == "1"


def _canonical_assignment_role_name(role_name: str | None) -> str:
    normalized = " ".join((role_name or "").strip().lower().split())
    if normalized == "project manager":
        return "Project Manager"
    return role_name or "-"


def _canonical_resource_type(value: str | None) -> str:
    normalized = _safe_strip(value).lower()
    if normalized == "interno":
        return "internal"
    if normalized == "externo":
        return "external"
    return normalized


def _active_roles():
    return db.session.execute(select(TeamRole).where(TeamRole.is_active.is_(True)).order_by(TeamRole.name.asc())).scalars().all()


def _active_resources():
    return db.session.execute(select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())).scalars().all()


def _team_catalog_values(catalog_key: str, fallback: list[str]) -> list[str]:
    if not g.get("user"):
        return fallback
    values = db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "team",
            SystemCatalogOptionConfig.catalog_key == catalog_key,
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    if not values:
        seed_default_catalogs_for_user(g.user.id)
        db.session.commit()
        values = db.session.execute(
            select(SystemCatalogOptionConfig.name)
            .where(
                SystemCatalogOptionConfig.owner_user_id == g.user.id,
                SystemCatalogOptionConfig.module_key == "team",
                SystemCatalogOptionConfig.catalog_key == catalog_key,
                SystemCatalogOptionConfig.is_active.is_(True),
            )
            .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
        ).scalars().all()
    return values or fallback


def _shared_client_catalog_values(field_key: str, fallback: list[str]) -> list[str]:
    if not g.get("user"):
        return fallback
    values = db.session.execute(
        select(ClientCatalogOptionConfig.name)
        .where(
            ClientCatalogOptionConfig.owner_user_id == g.user.id,
            ClientCatalogOptionConfig.field_key == field_key,
            ClientCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(ClientCatalogOptionConfig.is_system.asc(), ClientCatalogOptionConfig.name.asc())
    ).scalars().all()
    if not values:
        seed_default_catalogs_for_user(g.user.id)
        db.session.commit()
        values = db.session.execute(
            select(ClientCatalogOptionConfig.name)
            .where(
                ClientCatalogOptionConfig.owner_user_id == g.user.id,
                ClientCatalogOptionConfig.field_key == field_key,
                ClientCatalogOptionConfig.is_active.is_(True),
            )
            .order_by(ClientCatalogOptionConfig.is_system.asc(), ClientCatalogOptionConfig.name.asc())
        ).scalars().all()
    return values or fallback


def _validate_catalog_value(value: str, options: list[str], field_label: str, errors: list[str]) -> str:
    cleaned = _safe_strip(value)
    if not cleaned:
        return ""
    if cleaned not in set(options):
        errors.append(f"{field_label} no es valido.")
    return cleaned


def _resource_or_404(resource_id: int) -> Resource:
    resource = db.session.execute(
        select(Resource)
        .where(Resource.id == resource_id)
        .options(
            selectinload(Resource.role_links).selectinload(ResourceRole.role),
            selectinload(Resource.availabilities),
            selectinload(Resource.availability_exceptions),
            selectinload(Resource.costs),
            selectinload(Resource.project_assignments).selectinload(ProjectResource.project),
            selectinload(Resource.project_assignments).selectinload(ProjectResource.role),
            selectinload(Resource.task_assignments).selectinload(TaskResource.task),
            selectinload(Resource.task_assignments).selectinload(TaskResource.task).selectinload(Task.project),
            selectinload(Resource.task_assignments).selectinload(TaskResource.role),
        )
    ).scalar_one_or_none()
    if not resource:
        abort(404)
    return resource


def _safe_next_url() -> str | None:
    candidate = _safe_strip(request.form.get("next") or request.args.get("next"))
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith("/"):
        return None
    return candidate


def _redirect_with_next(default_endpoint: str, **kwargs):
    next_url = _safe_next_url()
    if next_url:
        return redirect(next_url)
    return redirect(url_for(default_endpoint, **kwargs))


def _resource_usage_messages(resource_id: int) -> list[str]:
    messages: list[str] = []

    sales_exec_count = db.session.execute(
        select(func.count()).select_from(Client).where(Client.sales_executive_resource_id == resource_id)
    ).scalar_one()
    account_manager_count = db.session.execute(
        select(func.count()).select_from(Client).where(Client.account_manager_resource_id == resource_id)
    ).scalar_one()
    delivery_manager_count = db.session.execute(
        select(func.count()).select_from(Client).where(Client.delivery_manager_resource_id == resource_id)
    ).scalar_one()
    if sales_exec_count:
        messages.append(f"Está asignado como Ejecutivo comercial en {sales_exec_count} cliente(s).")
    if account_manager_count:
        messages.append(f"Está asignado como Account manager en {account_manager_count} cliente(s).")
    if delivery_manager_count:
        messages.append(f"Está asignado como Responsable delivery en {delivery_manager_count} cliente(s).")

    project_manager_count = db.session.execute(
        select(func.count()).select_from(Project).where(Project.project_manager_resource_id == resource_id)
    ).scalar_one()
    commercial_manager_count = db.session.execute(
        select(func.count()).select_from(Project).where(Project.commercial_manager_resource_id == resource_id)
    ).scalar_one()
    functional_manager_count = db.session.execute(
        select(func.count()).select_from(Project).where(Project.functional_manager_resource_id == resource_id)
    ).scalar_one()
    technical_manager_count = db.session.execute(
        select(func.count()).select_from(Project).where(Project.technical_manager_resource_id == resource_id)
    ).scalar_one()
    if project_manager_count:
        messages.append(f"Está asignado como Project manager en {project_manager_count} proyecto(s).")
    if commercial_manager_count:
        messages.append(f"Está asignado como Responsable comercial en {commercial_manager_count} proyecto(s).")
    if functional_manager_count:
        messages.append(f"Está asignado como Responsable funcional en {functional_manager_count} proyecto(s).")
    if technical_manager_count:
        messages.append(f"Está asignado como Responsable técnico/delivery en {technical_manager_count} proyecto(s).")

    task_responsible_count = db.session.execute(
        select(func.count()).select_from(Task).where(Task.responsible_resource_id == resource_id)
    ).scalar_one()
    if task_responsible_count:
        messages.append(f"Está asignado como responsable en {task_responsible_count} tarea(s).")

    project_assignment_count = db.session.execute(
        select(func.count()).select_from(ProjectResource).where(ProjectResource.resource_id == resource_id)
    ).scalar_one()
    task_assignment_count = db.session.execute(
        select(func.count()).select_from(TaskResource).where(TaskResource.resource_id == resource_id)
    ).scalar_one()
    if project_assignment_count:
        messages.append(f"Tiene {project_assignment_count} asignación(es) a proyectos.")
    if task_assignment_count:
        messages.append(f"Tiene {task_assignment_count} asignación(es) a tareas.")

    return messages


@bp.route("/")
@login_required
def index():
    return redirect(url_for("team.list_resources"))


@bp.route("/resources")
@login_required
def list_resources():
    q = _safe_strip(request.args.get("q"))
    active = _safe_strip(request.args.get("active", "1"))
    resource_type = _canonical_resource_type(request.args.get("resource_type"))
    role_id = _to_int(request.args.get("role_id"))

    stmt = select(Resource).order_by(Resource.updated_at.desc())
    if q:
        token = f"%{q}%"
        stmt = stmt.where(
            or_(
                Resource.full_name.ilike(token),
                Resource.email.ilike(token),
                Resource.position.ilike(token),
                Resource.area.ilike(token),
            )
        )
    if active in {"1", "0"}:
        stmt = stmt.where(Resource.is_active.is_(active == "1"))
    resource_types = _team_catalog_values("resource_types", ["internal", "external"])
    if resource_type in set(resource_types):
        stmt = stmt.where(Resource.resource_type == resource_type)
    if role_id:
        stmt = stmt.join(ResourceRole, ResourceRole.resource_id == Resource.id).where(ResourceRole.role_id == role_id)

    resources = db.session.execute(stmt).scalars().all()
    return render_template(
        "team/resource_list.html",
        resources=resources,
        roles=_active_roles(),
        resource_types=resource_types,
        filters={
            "q": q,
            "active": active,
            "resource_type": resource_type,
            "role_id": role_id or "",
        },
    )


@bp.route("/calendar")
@login_required
def team_calendar():
    resources = db.session.execute(
        select(Resource)
        .where(Resource.is_active.is_(True))
        .options(selectinload(Resource.role_links).selectinload(ResourceRole.role))
        .order_by(Resource.full_name.asc())
    ).scalars().all()
    roles = _active_roles()
    requested_resource_id = _to_int(request.args.get("resource_id"))
    selected_resource = None
    if requested_resource_id:
        selected_resource = next((item for item in resources if item.id == requested_resource_id), None)
    if not selected_resource and resources:
        selected_resource = resources[0]
    requested_role_id = _to_int(request.args.get("role_id"))
    selected_role_id = requested_role_id if requested_role_id and any(role.id == requested_role_id for role in roles) else None
    back_url = _safe_next_url() or url_for("team.list_resources")
    resources_meta = [
        {
            "id": resource.id,
            "full_name": resource.full_name,
            "role_ids": [link.role_id for link in resource.role_links if link.role and link.role.is_active],
            "role_names": [link.role.name for link in resource.role_links if link.role and link.role.is_active],
        }
        for resource in resources
    ]

    return render_template(
        "team/team_calendar.html",
        resources=resources,
        roles=roles,
        selected_resource=selected_resource,
        selected_role_id=selected_role_id,
        resources_meta=resources_meta,
        back_url=back_url,
    )


@bp.route("/resources/new", methods=["GET", "POST"])
@login_required
def create_resource():
    resource_types = _team_catalog_values("resource_types", ["internal", "external"])
    calendar_options = _team_catalog_values("calendars", [])
    timezone_options = _shared_client_catalog_values("timezone", [])
    position_options = _team_catalog_values("positions", [])
    area_options = _team_catalog_values("areas", [])
    vendor_options = _team_catalog_values("vendors", [])
    if request.method == "POST":
        payload = {
            "first_name": _safe_strip(request.form.get("first_name")),
            "last_name": _safe_strip(request.form.get("last_name")),
            "email": normalize_email(request.form.get("email")),
            "phone": _safe_strip(request.form.get("phone")),
            "position": "",
            "area": "",
            "resource_type": _canonical_resource_type(request.form.get("resource_type")),
            "calendar_name": "",
            "timezone": "",
            "vendor_name": "",
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(payload, allowed_resource_types=resource_types)
        payload["calendar_name"] = _validate_catalog_value(
            request.form.get("calendar_name"), calendar_options, "Calendario", errors
        )
        payload["timezone"] = _validate_catalog_value(
            request.form.get("timezone"), timezone_options, "Zona horaria", errors
        )
        payload["position"] = _validate_catalog_value(request.form.get("position"), position_options, "Cargo", errors)
        payload["area"] = _validate_catalog_value(request.form.get("area"), area_options, "Area", errors)
        payload["vendor_name"] = _validate_catalog_value(request.form.get("vendor_name"), vendor_options, "Proveedor", errors)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "team/resource_form.html",
                resource=None,
                form_values=request.form,
                resource_types=resource_types,
                calendar_options=calendar_options,
                timezone_options=timezone_options,
                position_options=position_options,
                area_options=area_options,
                vendor_options=vendor_options,
            )

        resource = Resource(**payload)
        sync_resource_full_name(resource)
        db.session.add(resource)
        db.session.commit()
        flash("Recurso creado.", "success")
        return redirect(url_for("team.list_resources"))

    return render_template(
        "team/resource_form.html",
        resource=None,
        form_values={},
        resource_types=resource_types,
        calendar_options=calendar_options,
        timezone_options=timezone_options,
        position_options=position_options,
        area_options=area_options,
        vendor_options=vendor_options,
    )


@bp.route("/resources/<int:resource_id>/edit", methods=["GET", "POST"])
@login_required
def edit_resource(resource_id: int):
    resource = _resource_or_404(resource_id)
    resource_types = _team_catalog_values("resource_types", ["internal", "external"])
    calendar_options = _team_catalog_values("calendars", [])
    timezone_options = _shared_client_catalog_values("timezone", [])
    position_options = _team_catalog_values("positions", [])
    area_options = _team_catalog_values("areas", [])
    vendor_options = _team_catalog_values("vendors", [])

    if request.method == "POST":
        payload = {
            "first_name": _safe_strip(request.form.get("first_name")),
            "last_name": _safe_strip(request.form.get("last_name")),
            "email": normalize_email(request.form.get("email")),
            "phone": _safe_strip(request.form.get("phone")),
            "position": "",
            "area": "",
            "resource_type": _canonical_resource_type(request.form.get("resource_type")),
            "calendar_name": "",
            "timezone": "",
            "vendor_name": "",
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(
            payload,
            current_resource_id=resource.id,
            allowed_resource_types=resource_types,
        )
        payload["calendar_name"] = _validate_catalog_value(
            request.form.get("calendar_name"), calendar_options, "Calendario", errors
        )
        payload["timezone"] = _validate_catalog_value(
            request.form.get("timezone"), timezone_options, "Zona horaria", errors
        )
        payload["position"] = _validate_catalog_value(request.form.get("position"), position_options, "Cargo", errors)
        payload["area"] = _validate_catalog_value(request.form.get("area"), area_options, "Area", errors)
        payload["vendor_name"] = _validate_catalog_value(request.form.get("vendor_name"), vendor_options, "Proveedor", errors)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "team/resource_form.html",
                resource=resource,
                form_values=request.form,
                resource_types=resource_types,
                calendar_options=calendar_options,
                timezone_options=timezone_options,
                position_options=position_options,
                area_options=area_options,
                vendor_options=vendor_options,
            )

        for key, value in payload.items():
            setattr(resource, key, value)
        sync_resource_full_name(resource)
        db.session.commit()
        flash("Recurso actualizado.", "success")
        return redirect(url_for("team.list_resources"))

    return render_template(
        "team/resource_form.html",
        resource=resource,
        form_values={},
        resource_types=resource_types,
        calendar_options=calendar_options,
        timezone_options=timezone_options,
        position_options=position_options,
        area_options=area_options,
        vendor_options=vendor_options,
    )


@bp.route("/resources/<int:resource_id>/toggle", methods=["POST"])
@login_required
def toggle_resource(resource_id: int):
    resource = _resource_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    flash("Estado del recurso actualizado.", "info")
    return redirect(request.referrer or url_for("team.list_resources"))


@bp.route("/resources/<int:resource_id>/delete", methods=["POST"])
@login_required
def delete_resource(resource_id: int):
    _resource_or_404(resource_id)
    flash("La eliminación física de recursos está deshabilitada. Usa Activar/Desactivar.", "warning")
    return redirect(request.referrer or url_for("team.list_resources"))


@bp.route("/resources/<int:resource_id>")
@login_required
def resource_detail(resource_id: int):
    resource = _resource_or_404(resource_id)
    assignment_rows: list[dict[str, object]] = []
    seen_keys: set[tuple[str, int, str]] = set()

    def _project_label(project_code: str | None, project_name: str | None) -> str:
        code = (project_code or "").strip()
        name = (project_name or "").strip()
        if code and name:
            return f"{code} - {name}"
        return name or "-"

    client_rows = db.session.execute(
        select(
            Client.id,
            Client.name,
            Client.is_active,
            Client.onboarding_date,
            Client.created_at,
            Client.sales_executive_resource_id,
            Client.account_manager_resource_id,
            Client.delivery_manager_resource_id,
        )
        .where(
            or_(
                Client.sales_executive_resource_id == resource.id,
                Client.account_manager_resource_id == resource.id,
                Client.delivery_manager_resource_id == resource.id,
            )
        )
        .order_by(Client.name.asc())
    ).all()

    client_role_labels = (
        ("Ejecutivo comercial", 5),
        ("Account manager", 6),
        ("Responsable delivery", 7),
    )
    for row in client_rows:
        for label, idx in client_role_labels:
            if row[idx] != resource.id:
                continue
            display_role = _canonical_assignment_role_name(label)
            key = ("client", row[0], display_role)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            assignment_rows.append(
                {
                    "entity_type": "Cliente",
                    "client_id": row[0],
                    "project_id": None,
                    "client_name": row[1],
                    "project_name": "-",
                    "role_name": display_role,
                    "start_date": row[3] or (row[4].date() if row[4] else None),
                    "end_date": None,
                    "status_label": "Activo" if bool(row[2]) else "Inactivo",
                }
            )

    explicit_project_ids = {item.project_id for item in resource.project_assignments if item.project_id}
    project_client_map: dict[int, str] = {}
    if explicit_project_ids:
        project_client_rows = db.session.execute(
            select(Project.id, Client.name).join(Client, Client.id == Project.client_id).where(Project.id.in_(explicit_project_ids))
        ).all()
        project_client_map = {row[0]: row[1] for row in project_client_rows}

    for item in resource.project_assignments:
        if not item.project:
            continue
        role_name = _canonical_assignment_role_name(item.role.name if item.role else "-")
        key = ("project", item.project_id, role_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        is_active = bool(item.is_active and item.project.is_active)
        assignment_rows.append(
            {
                "entity_type": "Proyecto",
                "client_id": item.project.client_id,
                "project_id": item.project.id,
                "project_name": _project_label(item.project.project_code, item.project.name),
                "client_name": project_client_map.get(item.project_id, "-"),
                "role_name": role_name,
                "end_date": item.end_date,
                "status_label": "Activo" if is_active else "Inactivo",
                "start_date": item.start_date or (item.created_at.date() if item.created_at else None),
            }
        )

    project_rows = db.session.execute(
        select(
            Project.id,
            Project.name,
            Project.project_code,
            Project.is_active,
            Client.name,
            Project.onboarding_date,
            Project.estimated_start_date,
            Project.actual_end_date,
            Project.close_date,
            Project.created_at,
            Project.project_manager_resource_id,
            Project.commercial_manager_resource_id,
            Project.functional_manager_resource_id,
            Project.technical_manager_resource_id,
            Project.client_id,
        )
        .join(Client, Client.id == Project.client_id)
        .where(
            or_(
                Project.project_manager_resource_id == resource.id,
                Project.commercial_manager_resource_id == resource.id,
                Project.functional_manager_resource_id == resource.id,
                Project.technical_manager_resource_id == resource.id,
            )
        )
        .order_by(Project.name.asc())
    ).all()

    role_labels = (
        ("Project Manager", 10),
        ("Responsable comercial", 11),
        ("Responsable funcional", 12),
        ("Responsable tecnico/delivery", 13),
    )
    for row in project_rows:
        for label, idx in role_labels:
            if row[idx] != resource.id:
                continue
            key = ("project", row[0], label)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            assignment_rows.append(
                {
                    "entity_type": "Proyecto",
                    "client_id": row[14],
                    "project_id": row[0],
                    "project_name": _project_label(row[2], row[1]),
                    "client_name": row[4],
                    "role_name": label,
                    "end_date": row[7] or row[8],
                    "status_label": "Activo" if bool(row[3]) else "Inactivo",
                    "start_date": row[5] or row[6] or (row[9].date() if row[9] else None),
                }
            )

    assignment_rows.sort(
        key=lambda item: (item.get("start_date") is None, item.get("start_date")),
        reverse=True,
    )
    usage_by_cost_id = {item.id: resource_cost_usage_count(item.id) for item in resource.costs}

    return render_template(
        "team/resource_detail.html",
        resource=resource,
        assignment_rows=assignment_rows,
        today=date.today(),
        current_availability=next(
            (
                item
                for item in sorted(resource.availabilities, key=lambda row: row.valid_from, reverse=True)
                if item.is_active and item.valid_from <= date.today() and (item.valid_to is None or item.valid_to >= date.today())
            ),
            None,
        ),
        current_cost=next(
            (
                item
                for item in sorted(resource.costs, key=lambda row: row.valid_from, reverse=True)
                if item.valid_from <= date.today() and (item.valid_to is None or item.valid_to >= date.today())
            ),
            None,
        ),
        usage_by_cost_id=usage_by_cost_id,
    )


@bp.route("/resources/<int:resource_id>/roles")
@login_required
def manage_resource_roles(resource_id: int):
    resource = _resource_or_404(resource_id)
    role_ids = {link.role_id for link in resource.role_links}
    return render_template(
        "team/resource_roles.html",
        resource=resource,
        roles=_active_roles(),
        role_ids=role_ids,
    )


@bp.route("/resources/<int:resource_id>/availability")
@login_required
def manage_resource_availability(resource_id: int):
    resource = _resource_or_404(resource_id)
    edit_availability = None
    edit_exception = None

    edit_availability_id = _to_int(request.args.get("edit_availability_id"))
    if edit_availability_id:
        edit_availability = db.session.get(ResourceAvailability, edit_availability_id)
        if not edit_availability or edit_availability.resource_id != resource.id:
            abort(404)

    edit_exception_id = _to_int(request.args.get("edit_exception_id"))
    if edit_exception_id:
        edit_exception = db.session.get(ResourceAvailabilityException, edit_exception_id)
        if not edit_exception or edit_exception.resource_id != resource.id:
            abort(404)

    selected_working_days = set((edit_availability.working_days or "").split(",")) if edit_availability else {"mon", "tue", "wed", "thu", "fri"}
    return render_template(
        "team/resource_availability.html",
        resource=resource,
        availability_types=_team_catalog_values("availability_types", ["full_time", "part_time", "custom"]),
        availability_exception_types=_team_catalog_values(
            "availability_exception_types",
            ["time_off", "vacation", "leave", "holiday", "blocked"],
        ),
        edit_availability=edit_availability,
        edit_exception=edit_exception,
        availability_form_values={},
        exception_form_values={},
        selected_working_days=selected_working_days,
    )


@bp.route("/resources/<int:resource_id>/costs")
@login_required
def manage_resource_costs(resource_id: int):
    resource = _resource_or_404(resource_id)
    edit_cost = None
    edit_cost_id = _to_int(request.args.get("edit_cost_id"))
    if edit_cost_id:
        edit_cost = db.session.get(ResourceCost, edit_cost_id)
        if not edit_cost or edit_cost.resource_id != resource.id:
            abort(404)

    return render_template(
        "team/resource_costs.html",
        resource=resource,
        currency_options=_shared_client_catalog_values("currency_code", ["USD"]),
        usage_by_cost_id={item.id: resource_cost_usage_count(item.id) for item in resource.costs},
        edit_cost=edit_cost,
        edit_cost_usage_count=resource_cost_usage_count(edit_cost.id) if edit_cost else 0,
        cost_form_values={},
    )


@bp.route("/resources/<int:resource_id>/roles/add", methods=["POST"])
@login_required
def add_resource_role(resource_id: int):
    resource = _resource_or_404(resource_id)
    role_id = _to_int(request.form.get("role_id"))
    if not role_id:
        flash("Selecciona un rol.", "danger")
        return _redirect_with_next("team.manage_resource_roles", resource_id=resource.id)

    errors = validate_assignment(resource.id, role_id)
    if errors:
        for error in errors:
            flash(error, "danger")
        return _redirect_with_next("team.manage_resource_roles", resource_id=resource.id)

    existing = db.session.execute(
        select(ResourceRole).where(ResourceRole.resource_id == resource.id, ResourceRole.role_id == role_id)
    ).scalar_one_or_none()
    if existing:
        flash("El rol ya está asignado al recurso.", "warning")
    else:
        db.session.add(ResourceRole(resource_id=resource.id, role_id=role_id))
        db.session.commit()
        flash("Rol asignado.", "success")
    return _redirect_with_next("team.manage_resource_roles", resource_id=resource.id)


@bp.route("/resource-role/<int:link_id>/delete", methods=["POST"])
@login_required
def remove_resource_role(link_id: int):
    link = db.session.get(ResourceRole, link_id)
    if not link:
        abort(404)

    project_names = db.session.execute(
        select(Project.name)
        .join(ProjectResource, ProjectResource.project_id == Project.id)
        .where(
            ProjectResource.resource_id == link.resource_id,
            ProjectResource.role_id == link.role_id,
            ProjectResource.is_active.is_(True),
        )
        .order_by(Project.name.asc())
        .limit(3)
    ).scalars().all()

    if project_names:
        flash("No se puede remover el rol porque el recurso lo tiene asignado en proyectos activos.", "danger")
        flash(f"Proyectos detectados: {', '.join(project_names)}.", "warning")
        return _redirect_with_next("team.manage_resource_roles", resource_id=link.resource_id)

    resource_id = link.resource_id
    db.session.delete(link)
    db.session.commit()
    flash("Rol removido.", "info")
    return _redirect_with_next("team.manage_resource_roles", resource_id=resource_id)


@bp.route("/resources/<int:resource_id>/availability/add", methods=["POST"])
@login_required
def add_availability(resource_id: int):
    resource = _resource_or_404(resource_id)
    working_days = normalize_working_days(request.form.getlist("working_days"))

    payload = {
        "availability_type": _safe_strip(request.form.get("availability_type")).lower(),
        "weekly_hours": _to_decimal(request.form.get("weekly_hours")),
        "daily_hours": _to_decimal(request.form.get("daily_hours")),
        "working_days": working_days,
        "valid_from": _parse_date(request.form.get("valid_from")),
        "valid_to": _parse_date(request.form.get("valid_to")),
        "observations": _safe_strip(request.form.get("observations")),
        "is_active": _to_bool(request.form.get("is_active", "1")),
    }
    errors = validate_availability_payload(
        resource.id,
        payload,
        allowed_availability_types=_team_catalog_values("availability_types", ["full_time", "part_time", "custom"]),
    )
    if errors:
        for error in errors:
            flash(error, "danger")
        return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)

    db.session.add(ResourceAvailability(resource_id=resource.id, **payload))
    db.session.commit()
    flash("Disponibilidad guardada.", "success")
    return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)


@bp.route("/resources/<int:resource_id>/availability-exceptions/add", methods=["POST"])
@login_required
def add_availability_exception(resource_id: int):
    resource = _resource_or_404(resource_id)
    availability_exception_types = _team_catalog_values(
        "availability_exception_types",
        ["time_off", "vacation", "leave", "holiday", "blocked"],
    )
    payload = {
        "exception_type": _safe_strip(request.form.get("exception_type")).lower(),
        "start_date": _parse_date(request.form.get("start_date")),
        "end_date": _parse_date(request.form.get("end_date")),
        "hours_lost": _to_decimal(request.form.get("hours_lost")),
        "observations": _safe_strip(request.form.get("observations")),
        "is_active": True,
    }
    errors = validate_availability_exception_payload(
        resource.id,
        payload,
        allowed_exception_types=availability_exception_types,
    )
    if errors:
        for error in errors:
            flash(error, "danger")
        return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)
    db.session.add(ResourceAvailabilityException(resource_id=resource.id, **payload))
    db.session.commit()
    flash("Excepción de disponibilidad guardada.", "success")
    return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)


@bp.route("/availability/<int:availability_id>/toggle", methods=["POST"])
@login_required
def toggle_availability(availability_id: int):
    availability = db.session.get(ResourceAvailability, availability_id)
    if not availability:
        abort(404)
    availability.is_active = not availability.is_active
    db.session.commit()
    flash("Estado de disponibilidad actualizado.", "info")
    return _redirect_with_next("team.manage_resource_availability", resource_id=availability.resource_id)


@bp.route("/availability/<int:availability_id>/edit", methods=["GET", "POST"])
@login_required
def edit_availability(availability_id: int):
    availability = db.session.get(ResourceAvailability, availability_id)
    if not availability:
        abort(404)
    resource = _resource_or_404(availability.resource_id)
    availability_types = _team_catalog_values("availability_types", ["full_time", "part_time", "custom"])

    if request.method == "GET":
        return redirect(
            url_for(
                "team.manage_resource_availability",
                resource_id=resource.id,
                edit_availability_id=availability.id,
            )
        )

    if request.method == "POST":
        working_days = normalize_working_days(request.form.getlist("working_days"))
        payload = {
            "availability_type": _safe_strip(request.form.get("availability_type")).lower(),
            "weekly_hours": _to_decimal(request.form.get("weekly_hours")),
            "daily_hours": _to_decimal(request.form.get("daily_hours")),
            "working_days": working_days,
            "valid_from": _parse_date(request.form.get("valid_from")),
            "valid_to": _parse_date(request.form.get("valid_to")),
            "observations": _safe_strip(request.form.get("observations")),
            "is_active": availability.is_active,
        }
        errors = validate_availability_payload(
            resource.id,
            payload,
            current_id=availability.id,
            allowed_availability_types=availability_types,
        )
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "team/resource_availability.html",
                resource=resource,
                availability_types=availability_types,
                availability_exception_types=_team_catalog_values(
                    "availability_exception_types",
                    ["time_off", "vacation", "leave", "holiday", "blocked"],
                ),
                edit_availability=availability,
                edit_exception=None,
                availability_form_values=request.form,
                exception_form_values={},
                selected_working_days=set(request.form.getlist("working_days")),
            )

        availability.availability_type = payload["availability_type"]
        availability.weekly_hours = payload["weekly_hours"]
        availability.daily_hours = payload["daily_hours"]
        availability.working_days = payload["working_days"]
        availability.valid_from = payload["valid_from"]
        availability.valid_to = payload["valid_to"]
        availability.observations = payload["observations"]
        db.session.commit()
        flash("Disponibilidad actualizada.", "success")
        return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)

    return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)


@bp.route("/availability-exception/<int:exception_id>/toggle", methods=["POST"])
@login_required
def toggle_availability_exception(exception_id: int):
    availability_exception = db.session.get(ResourceAvailabilityException, exception_id)
    if not availability_exception:
        abort(404)
    availability_exception.is_active = not availability_exception.is_active
    db.session.commit()
    flash("Estado de excepción actualizado.", "info")
    return _redirect_with_next("team.manage_resource_availability", resource_id=availability_exception.resource_id)


@bp.route("/availability-exception/<int:exception_id>/edit", methods=["GET", "POST"])
@login_required
def edit_availability_exception(exception_id: int):
    availability_exception = db.session.get(ResourceAvailabilityException, exception_id)
    if not availability_exception:
        abort(404)
    resource = _resource_or_404(availability_exception.resource_id)
    availability_exception_types = _team_catalog_values(
        "availability_exception_types",
        ["time_off", "vacation", "leave", "holiday", "blocked"],
    )
    if request.method == "GET":
        return redirect(
            url_for(
                "team.manage_resource_availability",
                resource_id=resource.id,
                edit_exception_id=availability_exception.id,
            )
        )

    if request.method == "POST":
        payload = {
            "exception_type": _safe_strip(request.form.get("exception_type")).lower(),
            "start_date": _parse_date(request.form.get("start_date")),
            "end_date": _parse_date(request.form.get("end_date")),
            "hours_lost": _to_decimal(request.form.get("hours_lost")),
            "observations": _safe_strip(request.form.get("observations")),
            "is_active": availability_exception.is_active,
        }
        errors = validate_availability_exception_payload(
            resource.id,
            payload,
            current_id=availability_exception.id,
            allowed_exception_types=availability_exception_types,
        )
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "team/resource_availability.html",
                resource=resource,
                availability_types=_team_catalog_values("availability_types", ["full_time", "part_time", "custom"]),
                availability_exception_types=availability_exception_types,
                edit_availability=None,
                edit_exception=availability_exception,
                availability_form_values={},
                exception_form_values=request.form,
                selected_working_days={"mon", "tue", "wed", "thu", "fri"},
            )

        availability_exception.exception_type = payload["exception_type"]
        availability_exception.start_date = payload["start_date"]
        availability_exception.end_date = payload["end_date"]
        availability_exception.hours_lost = payload["hours_lost"]
        availability_exception.observations = payload["observations"]
        db.session.commit()
        flash("Excepción de disponibilidad actualizada.", "success")
        return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)

    return _redirect_with_next("team.manage_resource_availability", resource_id=resource.id)


@bp.route("/resources/<int:resource_id>/costs/add", methods=["POST"])
@login_required
def add_cost(resource_id: int):
    resource = _resource_or_404(resource_id)
    cost_type = _safe_strip(request.form.get("cost_type")).lower()
    cost_amount = _to_decimal(request.form.get("cost_amount"))
    currency_options = _shared_client_catalog_values("currency_code", ["USD"])
    currency = _safe_strip(request.form.get("currency")).upper()

    payload = {
        "valid_from": _parse_date(request.form.get("valid_from")),
        "valid_to": _parse_date(request.form.get("valid_to")),
        "hourly_cost": cost_amount if cost_type == "hourly" else None,
        "monthly_cost": cost_amount if cost_type == "monthly" else None,
        "cost_type": cost_type,
        "currency": currency,
        "observations": _safe_strip(request.form.get("observations")),
        "is_active": True,
    }

    errors = validate_cost_payload(resource.id, payload)
    if currency not in set(currency_options):
        errors.append("Moneda inválida.")
    if errors:
        for error in errors:
            flash(error, "danger")
        return _redirect_with_next("team.manage_resource_costs", resource_id=resource.id)

    close_previous_cost_if_needed(resource.id, payload["valid_from"])
    persist_payload = {k: v for k, v in payload.items() if k != "cost_type"}
    db.session.add(ResourceCost(resource_id=resource.id, **persist_payload))
    db.session.commit()
    flash("Costo guardado.", "success")
    return _redirect_with_next("team.manage_resource_costs", resource_id=resource.id)


@bp.route("/cost/<int:cost_id>/edit", methods=["GET", "POST"])
@login_required
def edit_cost(cost_id: int):
    cost = db.session.get(ResourceCost, cost_id)
    if not cost:
        abort(404)
    usage_count = resource_cost_usage_count(cost.id)

    resource = _resource_or_404(cost.resource_id)
    currency_options = _shared_client_catalog_values("currency_code", ["USD"])
    if request.method == "GET":
        return redirect(
            url_for(
                "team.manage_resource_costs",
                resource_id=resource.id,
                edit_cost_id=cost.id,
            )
        )

    if request.method == "POST":
        cost_type = _safe_strip(request.form.get("cost_type")).lower()
        cost_amount = _to_decimal(request.form.get("cost_amount"))
        currency = _safe_strip(request.form.get("currency")).upper()
        payload = {
            "valid_from": _parse_date(request.form.get("valid_from")),
            "valid_to": _parse_date(request.form.get("valid_to")),
            "hourly_cost": cost_amount if cost_type == "hourly" else None,
            "monthly_cost": cost_amount if cost_type == "monthly" else None,
            "cost_type": cost_type,
            "currency": currency,
            "observations": _safe_strip(request.form.get("observations")),
            "is_active": True,
        }
        errors = validate_cost_payload(resource.id, payload, current_id=cost.id)
        if currency not in set(currency_options):
            errors.append("Moneda inválida.")
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template(
                "team/resource_costs.html",
                resource=resource,
                currency_options=currency_options,
                usage_by_cost_id={item.id: resource_cost_usage_count(item.id) for item in resource.costs},
                edit_cost=cost,
                edit_cost_usage_count=usage_count,
                cost_form_values=request.form,
            )

        close_previous_cost_if_needed(resource.id, payload["valid_from"], current_cost_id=cost.id)
        cost.valid_from = payload["valid_from"]
        cost.valid_to = payload["valid_to"]
        cost.hourly_cost = payload["hourly_cost"]
        cost.monthly_cost = payload["monthly_cost"]
        cost.currency = payload["currency"]
        cost.observations = payload["observations"]
        db.session.commit()
        flash("Tarifa actualizada.", "success")
        return _redirect_with_next("team.manage_resource_costs", resource_id=resource.id)

    return _redirect_with_next("team.manage_resource_costs", resource_id=resource.id)


@bp.route("/cost/<int:cost_id>/toggle", methods=["POST"])
@login_required
def toggle_cost(cost_id: int):
    cost = db.session.get(ResourceCost, cost_id)
    if not cost:
        abort(404)
    flash("Las tarifas no se pueden desactivar ni eliminar porque se usan para costeo histórico.", "warning")
    return _redirect_with_next("team.manage_resource_costs", resource_id=cost.resource_id)


@bp.route("/cost/<int:cost_id>/delete", methods=["POST"])
@login_required
def delete_cost(cost_id: int):
    cost = db.session.get(ResourceCost, cost_id)
    if not cost:
        abort(404)
    usage_count = resource_cost_usage_count(cost.id)
    if usage_count > 0:
        flash("No se puede eliminar la tarifa porque está en uso.", "danger")
        return _redirect_with_next("team.manage_resource_costs", resource_id=cost.resource_id)

    resource_id = cost.resource_id
    db.session.delete(cost)
    db.session.commit()
    flash("Tarifa eliminada.", "info")
    return _redirect_with_next("team.manage_resource_costs", resource_id=resource_id)


def _validate_assignment_dates(start_date, end_date) -> list[str]:
    if start_date and end_date and start_date > end_date:
        return ["Rango de fechas inválido."]
    return []


@bp.route("/resources/<int:resource_id>/availability/net", methods=["GET"])
@login_required
def resource_net_availability(resource_id: int):
    _resource_or_404(resource_id)
    date_from = _parse_date(request.args.get("date_from")) or date.today()
    date_to = _parse_date(request.args.get("date_to")) or (date_from + timedelta(days=13))
    if date_to < date_from:
        return jsonify({"error": "Rango de fechas inválido."}), 400
    if (date_to - date_from).days > 180:
        return jsonify({"error": "El rango máximo permitido es de 180 días."}), 400
    payload = calculate_resource_net_availability(resource_id, date_from, date_to, owner_user_id=g.user.id)
    return jsonify(payload)


@bp.route("/calendar/role-capacity", methods=["GET"])
@login_required
def role_capacity_calendar():
    date_from = _parse_date(request.args.get("date_from")) or date.today()
    date_to = _parse_date(request.args.get("date_to")) or (date_from + timedelta(days=31))
    if date_to < date_from:
        return jsonify({"error": "Rango de fechas inválido."}), 400
    if (date_to - date_from).days > 180:
        return jsonify({"error": "El rango máximo permitido es de 180 días."}), 400

    role_id = _to_int(request.args.get("role_id"))
    resources_stmt = (
        select(Resource)
        .where(Resource.is_active.is_(True))
        .options(selectinload(Resource.role_links).selectinload(ResourceRole.role))
        .order_by(Resource.full_name.asc())
    )
    if role_id:
        role = db.session.get(TeamRole, role_id)
        if not role or not role.is_active:
            return jsonify({"error": "Rol inválido."}), 400
        resources_stmt = resources_stmt.join(ResourceRole, ResourceRole.resource_id == Resource.id).where(
            ResourceRole.role_id == role_id
        )

    resources = db.session.execute(resources_stmt).scalars().unique().all()

    day_buckets: dict[str, dict] = {}
    cursor = date_from
    while cursor <= date_to:
        iso = cursor.isoformat()
        day_buckets[iso] = {
            "date": iso,
            "base_hours": 0.0,
            "exception_hours": 0.0,
            "assigned_hours": 0.0,
            "net_available_hours": 0.0,
            "overbooked_hours": 0.0,
            "entries": [],
        }
        cursor += timedelta(days=1)

    totals = {
        "base_hours": 0.0,
        "exception_hours": 0.0,
        "assigned_hours": 0.0,
        "net_available_hours": 0.0,
        "overbooked_hours": 0.0,
    }

    for resource in resources:
        role_names = [link.role.name for link in resource.role_links if link.role and link.role.is_active]
        payload = calculate_resource_net_availability(resource.id, date_from, date_to, owner_user_id=g.user.id)
        payload_totals = payload.get("totals", {})
        totals["base_hours"] += float(payload_totals.get("base_hours", 0.0))
        totals["exception_hours"] += float(payload_totals.get("exception_hours", 0.0))
        totals["assigned_hours"] += float(payload_totals.get("assigned_hours", 0.0))
        totals["net_available_hours"] += float(payload_totals.get("net_available_hours", 0.0))
        totals["overbooked_hours"] += float(payload_totals.get("overbooked_hours", 0.0))

        for day in payload.get("days", []):
            bucket = day_buckets.get(day["date"])
            if not bucket:
                continue
            bucket["base_hours"] += float(day.get("base_hours", 0.0))
            bucket["exception_hours"] += float(day.get("exception_hours", 0.0))
            bucket["assigned_hours"] += float(day.get("assigned_hours", 0.0))
            bucket["net_available_hours"] += float(day.get("net_available_hours", 0.0))
            bucket["overbooked_hours"] += float(day.get("overbooked_hours", 0.0))
            bucket["entries"].append(
                {
                    "resource_id": resource.id,
                    "resource_full_name": resource.full_name,
                    "role_names": role_names,
                    "base_hours": float(day.get("base_hours", 0.0)),
                    "exception_hours": float(day.get("exception_hours", 0.0)),
                    "assigned_hours": float(day.get("assigned_hours", 0.0)),
                    "net_available_hours": float(day.get("net_available_hours", 0.0)),
                    "overbooked_hours": float(day.get("overbooked_hours", 0.0)),
                    "calendar_holiday": bool(day.get("calendar_holiday")),
                    "calendar_holiday_label": day.get("calendar_holiday_label"),
                }
            )

    days = []
    for iso in sorted(day_buckets.keys()):
        bucket = day_buckets[iso]
        bucket["entries"] = sorted(
            bucket["entries"],
            key=lambda item: (item["net_available_hours"], item["resource_full_name"]),
            reverse=True,
        )
        days.append(bucket)

    return jsonify(
        {
            "role_id": role_id,
            "resource_count": len(resources),
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "totals": totals,
            "days": days,
        }
    )


@bp.route("/resources/<int:resource_id>/assign/client", methods=["POST"])
@login_required
def assign_client(resource_id: int):
    _resource_or_404(resource_id)
    flash("Las asignaciones manuales a cliente están deshabilitadas. Se gestionan automáticamente desde Clientes.", "warning")
    return redirect(url_for("team.resource_detail", resource_id=resource_id))


@bp.route("/resources/<int:resource_id>/assign/project", methods=["POST"])
@login_required
def assign_project(resource_id: int):
    resource = _resource_or_404(resource_id)
    project_id = _to_int(request.form.get("project_id"))
    role_id = _to_int(request.form.get("role_id"))
    payload = {
        "is_primary": _to_bool(request.form.get("is_primary")),
        "allocation_percent": _to_decimal(request.form.get("allocation_percent")),
        "planned_hours": _to_decimal(request.form.get("planned_hours")),
        "planned_daily_hours": None,
        "start_date": _parse_date(request.form.get("start_date")),
        "end_date": _parse_date(request.form.get("end_date")),
        "is_active": True,
    }
    payload["planned_daily_hours"] = estimate_planned_daily_hours(
        payload["planned_hours"], payload["start_date"], payload["end_date"]
    )

    errors = validate_assignment(resource.id, role_id)
    errors.extend(_validate_assignment_dates(payload["start_date"], payload["end_date"]))
    project = db.session.get(Project, project_id) if project_id else None
    if not project or not project.is_active:
        errors.append("Proyecto inválido.")
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    reference_date = payload["start_date"] or date.today()
    applied_cost_id = find_applicable_cost_id(resource.id, reference_date)
    db.session.add(
        ProjectResource(
            project_id=project.id,
            resource_id=resource.id,
            role_id=role_id,
            resource_cost_id=applied_cost_id,
            **payload,
        )
    )
    db.session.commit()
    flash("Asignación a proyecto creada.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


@bp.route("/resources/<int:resource_id>/assign/task", methods=["POST"])
@login_required
def assign_task(resource_id: int):
    resource = _resource_or_404(resource_id)
    task_id = _to_int(request.form.get("task_id"))
    role_id = _to_int(request.form.get("role_id"))
    payload = {
        "is_primary": _to_bool(request.form.get("is_primary")),
        "allocation_percent": _to_decimal(request.form.get("allocation_percent")),
        "planned_hours": _to_decimal(request.form.get("planned_hours")),
        "planned_daily_hours": None,
        "start_date": _parse_date(request.form.get("start_date")),
        "end_date": _parse_date(request.form.get("end_date")),
        "is_active": True,
    }
    payload["planned_daily_hours"] = estimate_planned_daily_hours(
        payload["planned_hours"], payload["start_date"], payload["end_date"]
    )

    errors = validate_assignment(resource.id, role_id)
    errors.extend(_validate_assignment_dates(payload["start_date"], payload["end_date"]))
    task = db.session.get(Task, task_id) if task_id else None
    if not task or not task.is_active:
        errors.append("Tarea inválida.")
    else:
        errors.extend(validate_task_assignment_project_consistency(task.id, resource.id))

    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    reference_date = payload["start_date"] or date.today()
    applied_cost_id = find_applicable_cost_id(resource.id, reference_date)
    db.session.add(
        TaskResource(
            task_id=task.id,
            resource_id=resource.id,
            role_id=role_id,
            resource_cost_id=applied_cost_id,
            **payload,
        )
    )
    db.session.commit()
    flash("Asignación a tarea creada.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


@bp.route("/client-assignment/<int:assignment_id>/toggle", methods=["POST"])
@login_required
def toggle_client_assignment(assignment_id: int):
    flash("Las asignaciones manuales a cliente están deshabilitadas. Se gestionan automáticamente desde Clientes.", "warning")
    return redirect(url_for("team.list_resources"))


@bp.route("/project-assignment/<int:assignment_id>/toggle", methods=["POST"])
@login_required
def toggle_project_assignment(assignment_id: int):
    assignment = db.session.get(ProjectResource, assignment_id)
    if not assignment:
        abort(404)
    assignment.is_active = not assignment.is_active
    db.session.commit()
    flash("Asignación actualizada.", "info")
    return redirect(url_for("team.resource_detail", resource_id=assignment.resource_id))


@bp.route("/task-assignment/<int:assignment_id>/toggle", methods=["POST"])
@login_required
def toggle_task_assignment(assignment_id: int):
    assignment = db.session.get(TaskResource, assignment_id)
    if not assignment:
        abort(404)
    assignment.is_active = not assignment.is_active
    db.session.commit()
    flash("Asignación actualizada.", "info")
    return redirect(url_for("team.resource_detail", resource_id=assignment.resource_id))


@bp.route("/roles", methods=["GET", "POST"])
@login_required
def manage_roles():
    return redirect(url_for("settings.team_roles"))


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def edit_role(role_id: int):
    return redirect(url_for("settings.edit_team_role", role_id=role_id))


@bp.route("/roles/<int:role_id>/toggle", methods=["POST"])
@login_required
def toggle_role(role_id: int):
    flash("La gestión de roles se realiza desde Configuración / Equipo.", "info")
    return redirect(url_for("settings.team_roles"))
