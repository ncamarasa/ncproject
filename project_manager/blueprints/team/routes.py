from datetime import date
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.team import bp
from project_manager.extensions import db
from project_manager.models import (
    Client,
    ClientResource,
    Project,
    ProjectResource,
    Resource,
    ResourceAvailability,
    ResourceCost,
    ResourceRole,
    Task,
    TaskResource,
    TeamRole,
)
from project_manager.services.team_business_rules import (
    close_previous_cost_if_needed,
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


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _normalize_role_name(value: str | None) -> str:
    return " ".join(_safe_strip(value).split())


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


def _active_roles():
    return db.session.execute(select(TeamRole).where(TeamRole.is_active.is_(True)).order_by(TeamRole.name.asc())).scalars().all()


def _active_resources():
    return db.session.execute(select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())).scalars().all()


def _resource_or_404(resource_id: int) -> Resource:
    resource = db.session.execute(
        select(Resource)
        .where(Resource.id == resource_id)
        .options(
            selectinload(Resource.role_links).selectinload(ResourceRole.role),
            selectinload(Resource.availabilities),
            selectinload(Resource.costs),
            selectinload(Resource.client_assignments).selectinload(ClientResource.client),
            selectinload(Resource.client_assignments).selectinload(ClientResource.role),
            selectinload(Resource.project_assignments).selectinload(ProjectResource.project),
            selectinload(Resource.project_assignments).selectinload(ProjectResource.role),
            selectinload(Resource.task_assignments).selectinload(TaskResource.task),
            selectinload(Resource.task_assignments).selectinload(TaskResource.role),
        )
    ).scalar_one_or_none()
    if not resource:
        abort(404)
    return resource


def _team_role_in_use(role_id: int) -> bool:
    has_resource_links = (
        db.session.execute(select(ResourceRole.id).where(ResourceRole.role_id == role_id).limit(1)).scalar_one_or_none()
        is not None
    )
    has_client_assignments = (
        db.session.execute(select(ClientResource.id).where(ClientResource.role_id == role_id).limit(1)).scalar_one_or_none()
        is not None
    )
    has_project_assignments = (
        db.session.execute(select(ProjectResource.id).where(ProjectResource.role_id == role_id).limit(1)).scalar_one_or_none()
        is not None
    )
    has_task_assignments = (
        db.session.execute(select(TaskResource.id).where(TaskResource.role_id == role_id).limit(1)).scalar_one_or_none()
        is not None
    )
    return has_resource_links or has_client_assignments or has_project_assignments or has_task_assignments


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
    if resource_type in {"internal", "external"}:
        stmt = stmt.where(Resource.resource_type == resource_type)
    if role_id:
        stmt = stmt.join(ResourceRole, ResourceRole.resource_id == Resource.id).where(ResourceRole.role_id == role_id)

    resources = db.session.execute(stmt).scalars().all()
    return render_template(
        "team/resource_list.html",
        resources=resources,
        roles=_active_roles(),
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
    if request.method == "POST":
        payload = {
            "first_name": _safe_strip(request.form.get("first_name")),
            "last_name": _safe_strip(request.form.get("last_name")),
            "email": normalize_email(request.form.get("email")),
            "phone": _safe_strip(request.form.get("phone")),
            "position": _safe_strip(request.form.get("position")),
            "area": _safe_strip(request.form.get("area")),
            "resource_type": _safe_strip(request.form.get("resource_type")).lower(),
            "vendor_name": _safe_strip(request.form.get("vendor_name")),
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(payload)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("team/resource_form.html", resource=None, form_values=request.form)

        resource = Resource(**payload)
        sync_resource_full_name(resource)
        db.session.add(resource)
        db.session.commit()
        flash("Recurso creado.", "success")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    return render_template("team/resource_form.html", resource=None, form_values={})


@bp.route("/resources/<int:resource_id>/edit", methods=["GET", "POST"])
@login_required
def edit_resource(resource_id: int):
    resource = _resource_or_404(resource_id)

    if request.method == "POST":
        payload = {
            "first_name": _safe_strip(request.form.get("first_name")),
            "last_name": _safe_strip(request.form.get("last_name")),
            "email": normalize_email(request.form.get("email")),
            "phone": _safe_strip(request.form.get("phone")),
            "position": _safe_strip(request.form.get("position")),
            "area": _safe_strip(request.form.get("area")),
            "resource_type": _safe_strip(request.form.get("resource_type")).lower(),
            "vendor_name": _safe_strip(request.form.get("vendor_name")),
            "is_active": _to_bool(request.form.get("is_active", "1")),
        }
        errors = validate_resource_payload(payload, current_resource_id=resource.id)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("team/resource_form.html", resource=resource, form_values=request.form)

        for key, value in payload.items():
            setattr(resource, key, value)
        sync_resource_full_name(resource)
        db.session.commit()
        flash("Recurso actualizado.", "success")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    return render_template("team/resource_form.html", resource=resource, form_values={})


@bp.route("/resources/<int:resource_id>/toggle", methods=["POST"])
@login_required
def toggle_resource(resource_id: int):
    resource = _resource_or_404(resource_id)
    resource.is_active = not resource.is_active
    db.session.commit()
    flash("Estado del recurso actualizado.", "info")
    return redirect(request.referrer or url_for("team.list_resources"))


@bp.route("/resources/<int:resource_id>")
@login_required
def resource_detail(resource_id: int):
    resource = _resource_or_404(resource_id)
    role_ids = {link.role_id for link in resource.role_links}

    clients = db.session.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())).scalars().all()
    projects_stmt = select(Project).where(Project.is_active.is_(True)).order_by(Project.name.asc())
    allowed_ids = allowed_project_ids(g.user)
    if allowed_ids is not None:
        projects_stmt = projects_stmt.where(Project.id.in_(allowed_ids))
    projects = db.session.execute(projects_stmt).scalars().all()

    tasks = db.session.execute(
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.is_active.is_(True), Project.is_active.is_(True))
        .order_by(Task.id.desc())
        .limit(300)
    ).scalars().all()

    return render_template(
        "team/resource_detail.html",
        resource=resource,
        roles=_active_roles(),
        role_ids=role_ids,
        clients=clients,
        projects=projects,
        tasks=tasks,
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
    errors = validate_availability_payload(resource.id, payload)
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
    resource = _resource_or_404(resource_id)
    client_id = _to_int(request.form.get("client_id"))
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
    client = db.session.get(Client, client_id) if client_id else None
    if not client or not client.is_active:
        errors.append("Cliente inválido.")
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("team.resource_detail", resource_id=resource.id))

    db.session.add(ClientResource(client_id=client.id, resource_id=resource.id, role_id=role_id, **payload))
    db.session.commit()
    flash("Asignación a cliente creada.", "success")
    return redirect(url_for("team.resource_detail", resource_id=resource.id))


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
    assignment = db.session.get(ClientResource, assignment_id)
    if not assignment:
        abort(404)
    assignment.is_active = not assignment.is_active
    db.session.commit()
    flash("Asignación actualizada.", "info")
    return redirect(url_for("team.resource_detail", resource_id=assignment.resource_id))


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
    if request.method == "POST":
        name = _normalize_role_name(request.form.get("name"))
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
        return redirect(url_for("team.manage_roles"))

    roles = db.session.execute(select(TeamRole).order_by(TeamRole.name.asc())).scalars().all()
    return render_template("team/role_list.html", roles=roles)


@bp.route("/roles/<int:role_id>/edit", methods=["GET", "POST"])
@login_required
def edit_role(role_id: int):
    role = db.session.get(TeamRole, role_id)
    if not role:
        abort(404)
    if not role.is_editable:
        flash("No se puede editar: el rol es de sistema.", "danger")
        return redirect(url_for("team.manage_roles"))

    if request.method == "POST":
        name = _normalize_role_name(request.form.get("name"))
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
            return redirect(url_for("team.manage_roles"))

    return render_template("team/role_form.html", role=role)


@bp.route("/roles/<int:role_id>/toggle", methods=["POST"])
@login_required
def toggle_role(role_id: int):
    role = db.session.get(TeamRole, role_id)
    if not role:
        abort(404)
    if role.is_active:
        if not role.is_deletable:
            flash("No se puede desactivar: el rol es de sistema.", "danger")
            return redirect(url_for("team.manage_roles"))
        if _team_role_in_use(role.id):
            flash("No se puede desactivar: el rol está siendo utilizado.", "danger")
            return redirect(url_for("team.manage_roles"))
    role.is_active = not role.is_active
    db.session.commit()
    flash("Estado del rol actualizado.", "info")
    return redirect(url_for("team.manage_roles"))
