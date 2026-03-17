from datetime import date
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import has_permission, login_required
from project_manager.blueprints.team import bp
from project_manager.extensions import db
from project_manager.models import (
    Client,
    Project,
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceCost,
    ResourceRole,
    SystemCatalogOptionConfig,
    Task,
    TaskResource,
    TeamRole,
)
from project_manager.services.default_catalogs import seed_default_catalogs_for_user
from project_manager.services.team_business_rules import (
    close_previous_cost_if_needed,
    ensure_system_team_roles,
    normalize_email,
    sync_resource_full_name,
    validate_assignment,
    validate_availability_payload,
    validate_cost_payload,
    validate_resource_payload,
    validate_task_assignment_project_consistency,
)


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


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _to_bool(value: str | None) -> bool:
    return value == "1"


def _canonical_assignment_role_name(role_name: str | None) -> str:
    normalized = " ".join((role_name or "").strip().lower().split())
    if normalized == "project manager":
        return "Project Manager"
    return role_name or "-"


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
    resource_type = _safe_strip(request.args.get("resource_type"))
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


@bp.route("/resources/new", methods=["GET", "POST"])
@login_required
def create_resource():
    resource_types = _team_catalog_values("resource_types", ["internal", "external"])
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
            "resource_type": _safe_strip(request.form.get("resource_type")).lower(),
            "vendor_name": "",
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(payload, allowed_resource_types=resource_types)
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
        position_options=position_options,
        area_options=area_options,
        vendor_options=vendor_options,
    )


@bp.route("/resources/<int:resource_id>/edit", methods=["GET", "POST"])
@login_required
def edit_resource(resource_id: int):
    resource = _resource_or_404(resource_id)
    resource_types = _team_catalog_values("resource_types", ["internal", "external"])
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
            "resource_type": _safe_strip(request.form.get("resource_type")).lower(),
            "vendor_name": "",
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(
            payload,
            current_resource_id=resource.id,
            allowed_resource_types=resource_types,
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
    role_ids = {link.role_id for link in resource.role_links}
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

    return render_template(
        "team/resource_detail.html",
        resource=resource,
        roles=_active_roles(),
        role_ids=role_ids,
        assignment_rows=assignment_rows,
        availability_types=_team_catalog_values("availability_types", ["full_time", "part_time", "custom"]),
    )


@bp.route("/resources/<int:resource_id>/roles/add", methods=["POST"])
@login_required
def add_resource_role(resource_id: int):
    resource = _resource_or_404(resource_id)
    role_id = _to_int(request.form.get("role_id"))
    if not role_id:
        flash("Selecciona un rol.", "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    errors = validate_assignment(resource.id, role_id)
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    existing = db.session.execute(
        select(ResourceRole).where(ResourceRole.resource_id == resource.id, ResourceRole.role_id == role_id)
    ).scalar_one_or_none()
    if existing:
        flash("El rol ya está asignado al recurso.", "warning")
    else:
        db.session.add(ResourceRole(resource_id=resource.id, role_id=role_id))
        db.session.commit()
        flash("Rol asignado.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


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
        return redirect(url_for("team.resource_detail", resource_id=link.resource_id))

    resource_id = link.resource_id
    db.session.delete(link)
    db.session.commit()
    flash("Rol removido.", "info")
    return redirect(url_for("team.resource_detail", resource_id=resource_id))


@bp.route("/resources/<int:resource_id>/availability/add", methods=["POST"])
@login_required
def add_availability(resource_id: int):
    resource = _resource_or_404(resource_id)

    payload = {
        "availability_type": _safe_strip(request.form.get("availability_type")).lower(),
        "weekly_hours": _to_decimal(request.form.get("weekly_hours")),
        "daily_hours": _to_decimal(request.form.get("daily_hours")),
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
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    db.session.add(ResourceAvailability(resource_id=resource.id, **payload))
    db.session.commit()
    flash("Disponibilidad guardada.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


@bp.route("/availability/<int:availability_id>/toggle", methods=["POST"])
@login_required
def toggle_availability(availability_id: int):
    availability = db.session.get(ResourceAvailability, availability_id)
    if not availability:
        abort(404)
    availability.is_active = not availability.is_active
    db.session.commit()
    flash("Estado de disponibilidad actualizado.", "info")
    return redirect(url_for("team.resource_detail", resource_id=availability.resource_id))


@bp.route("/resources/<int:resource_id>/costs/add", methods=["POST"])
@login_required
def add_cost(resource_id: int):
    resource = _resource_or_404(resource_id)
    payload = {
        "valid_from": _parse_date(request.form.get("valid_from")),
        "valid_to": _parse_date(request.form.get("valid_to")),
        "hourly_cost": _to_decimal(request.form.get("hourly_cost")),
        "monthly_cost": _to_decimal(request.form.get("monthly_cost")),
        "currency": _safe_strip(request.form.get("currency")).upper(),
        "observations": _safe_strip(request.form.get("observations")),
        "is_active": _to_bool(request.form.get("is_active", "1")),
    }

    errors = validate_cost_payload(resource.id, payload)
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    close_previous_cost_if_needed(resource.id, payload["valid_from"])
    db.session.add(ResourceCost(resource_id=resource.id, **payload))
    db.session.commit()
    flash("Costo guardado.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


@bp.route("/cost/<int:cost_id>/toggle", methods=["POST"])
@login_required
def toggle_cost(cost_id: int):
    cost = db.session.get(ResourceCost, cost_id)
    if not cost:
        abort(404)
    cost.is_active = not cost.is_active
    db.session.commit()
    flash("Estado de costo actualizado.", "info")
    return redirect(url_for("team.resource_detail", resource_id=cost.resource_id))


def _validate_assignment_dates(start_date, end_date) -> list[str]:
    if start_date and end_date and start_date > end_date:
        return ["Rango de fechas inválido."]
    return []


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
        "start_date": _parse_date(request.form.get("start_date")),
        "end_date": _parse_date(request.form.get("end_date")),
        "is_active": True,
    }

    errors = validate_assignment(resource.id, role_id)
    errors.extend(_validate_assignment_dates(payload["start_date"], payload["end_date"]))
    project = db.session.get(Project, project_id) if project_id else None
    if not project or not project.is_active:
        errors.append("Proyecto inválido.")
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    db.session.add(ProjectResource(project_id=project.id, resource_id=resource.id, role_id=role_id, **payload))
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
        "start_date": _parse_date(request.form.get("start_date")),
        "end_date": _parse_date(request.form.get("end_date")),
        "is_active": True,
    }

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

    db.session.add(TaskResource(task_id=task.id, resource_id=resource.id, role_id=role_id, **payload))
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
