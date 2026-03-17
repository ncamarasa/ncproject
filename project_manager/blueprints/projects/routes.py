import os
from datetime import date
from uuid import uuid4

from flask import (
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import (
    allowed_client_ids,
    allowed_project_ids,
    has_permission,
    login_required,
)
from project_manager.blueprints.projects import bp
from project_manager.extensions import db
from project_manager.models import (
    Client,
    ClientContract,
    Project,
    ProjectResource,
    Resource,
    Stakeholder,
    SystemCatalogOptionConfig,
    TeamRole,
)
from project_manager.models import UserProjectAssignment
from project_manager.services.code_generation import generate_client_code, generate_project_code

ALLOWED_CONTRACT_EXTENSIONS = {"pdf", "doc", "docx"}


@bp.before_request
def _authorize_projects_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    needed_permission = "projects.edit" if is_write else "projects.view"
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    if not has_permission(g.user, needed_permission):
        flash("No tienes permisos para acceder al módulo de proyectos.", "danger")
        return redirect(url_for("main.home"))


def _to_int(value: str, default: int = 1) -> int:
    try:
        converted = int(value)
        return converted if converted > 0 else default
    except (TypeError, ValueError):
        return default


def _to_decimal(value: str | None):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _has_allowed_contract_extension(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_CONTRACT_EXTENSIONS


def _save_contract_file(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None, None

    original_name = secure_filename(file_storage.filename)
    if not original_name or not _has_allowed_contract_extension(original_name):
        return None, None, "Formato de contrato no permitido. Usar PDF, DOC o DOCX."

    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{ext}"
    upload_folder = current_app.config["CONTRACT_UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)
    file_storage.save(os.path.join(upload_folder, stored_name))

    return stored_name, original_name, None


def _active_contracts_for_client(client_id: int):
    today = date.today()
    return db.session.execute(
        select(ClientContract)
        .where(
            ClientContract.client_id == client_id,
            ClientContract.status.in_(["Vigente", "Activo", "Borrador"]),
            (ClientContract.end_date.is_(None) | (ClientContract.end_date >= today)),
        )
        .order_by(ClientContract.start_date.desc().nullslast(), ClientContract.created_at.desc())
    ).scalars().all()


def _active_team_role_id(*candidate_names: str) -> int | None:
    normalized = {name.strip().lower() for name in candidate_names if name and name.strip()}
    if not normalized:
        return None
    role = db.session.execute(
        select(TeamRole).where(TeamRole.is_active.is_(True)).order_by(TeamRole.name.asc())
    ).scalars().all()
    for item in role:
        if (item.name or "").strip().lower() in normalized:
            return item.id
    return None


def _sync_project_manager_assignments(project: Project, payload: dict) -> None:
    role_mapping = [
        (
            payload.get("project_manager_resource_id"),
            _active_team_role_id("Project Manager"),
        ),
        (
            payload.get("commercial_manager_resource_id"),
            _active_team_role_id("Ejecutivo comercial", "Responsable comercial", "Account manager"),
        ),
        (
            payload.get("functional_manager_resource_id"),
            _active_team_role_id("Responsable funcional"),
        ),
        (
            payload.get("technical_manager_resource_id"),
            _active_team_role_id("Responsable técnico", "Responsable delivery"),
        ),
    ]

    for resource_id, role_id in role_mapping:
        if not role_id:
            continue

        existing = db.session.execute(
            select(ProjectResource)
            .where(
                ProjectResource.project_id == project.id,
                ProjectResource.role_id == role_id,
            )
            .order_by(ProjectResource.id.asc())
        ).scalars().all()

        if not resource_id:
            for row in existing:
                row.is_active = False
            continue

        active_row = next((row for row in existing if row.is_active), None)
        if active_row:
            active_row.resource_id = resource_id
            active_row.is_active = True
            active_row.is_primary = True
            continue

        db.session.add(
            ProjectResource(
                project_id=project.id,
                resource_id=resource_id,
                role_id=role_id,
                is_primary=True,
                is_active=True,
                start_date=project.estimated_start_date or project.actual_start_date,
            )
        )


def _build_project_payload(form):
    project_manager_resource_id = _to_int(form.get("project_manager_resource_id"), default=0) or None
    commercial_manager_resource_id = _to_int(form.get("commercial_manager_resource_id"), default=0) or None
    functional_manager_resource_id = _to_int(form.get("functional_manager_resource_id"), default=0) or None
    technical_manager_resource_id = _to_int(form.get("technical_manager_resource_id"), default=0) or None

    project_manager = _safe_strip(form.get("project_manager"))
    commercial_manager = _safe_strip(form.get("commercial_manager"))
    functional_manager = _safe_strip(form.get("functional_manager"))
    technical_manager = _safe_strip(form.get("technical_manager"))

    if project_manager_resource_id:
        resource = db.session.get(Resource, project_manager_resource_id)
        if resource and resource.is_active:
            project_manager = resource.full_name
    if commercial_manager_resource_id:
        resource = db.session.get(Resource, commercial_manager_resource_id)
        if resource and resource.is_active:
            commercial_manager = resource.full_name
    if functional_manager_resource_id:
        resource = db.session.get(Resource, functional_manager_resource_id)
        if resource and resource.is_active:
            functional_manager = resource.full_name
    if technical_manager_resource_id:
        resource = db.session.get(Resource, technical_manager_resource_id)
        if resource and resource.is_active:
            technical_manager = resource.full_name

    return {
        "name": _safe_strip(form.get("name")),
        "description": _safe_strip(form.get("description")),
        "objective": _safe_strip(form.get("objective")),
        "project_type": _safe_strip(form.get("project_type")),
        "status": _safe_strip(form.get("status")),
        "business_unit": _safe_strip(form.get("business_unit")),
        "product_solution": _safe_strip(form.get("product_solution")),
        "service_module": _safe_strip(form.get("service_module")),
        "category": _safe_strip(form.get("category")),
        "priority": _safe_strip(form.get("priority")),
        "complexity_level": _safe_strip(form.get("complexity_level")),
        "criticality_level": _safe_strip(form.get("criticality_level")),
        "project_origin": _safe_strip(form.get("project_origin")),
        "project_manager": project_manager,
        "project_manager_resource_id": project_manager_resource_id,
        "commercial_manager": commercial_manager,
        "commercial_manager_resource_id": commercial_manager_resource_id,
        "functional_manager": functional_manager,
        "functional_manager_resource_id": functional_manager_resource_id,
        "technical_manager": technical_manager,
        "technical_manager_resource_id": technical_manager_resource_id,
        "client_sponsor": _safe_strip(form.get("client_sponsor")),
        "key_user": _safe_strip(form.get("key_user")),
        "onboarding_date": _parse_date(form.get("onboarding_date")),
        "estimated_start_date": _parse_date(form.get("estimated_start_date")),
        "actual_start_date": _parse_date(form.get("actual_start_date")),
        "estimated_end_date": _parse_date(form.get("estimated_end_date")),
        "actual_end_date": _parse_date(form.get("actual_end_date")),
        "estimated_duration_days": _to_int(form.get("estimated_duration_days"), default=0) or None,
        "kickoff_date": _parse_date(form.get("kickoff_date")),
        "close_date": _parse_date(form.get("close_date")),
        "methodology": _safe_strip(form.get("methodology")),
        "documentation_repo": _safe_strip(form.get("documentation_repo")),
        "external_board_url": _safe_strip(form.get("external_board_url")),
        "committee_frequency": _safe_strip(form.get("committee_frequency")),
        "communication_channel": _safe_strip(form.get("communication_channel")),
        "billing_mode": _safe_strip(form.get("billing_mode")),
        "currency_code": _safe_strip(form.get("currency_code")),
        "sold_budget": _to_decimal(form.get("sold_budget")),
        "estimated_cost": _to_decimal(form.get("estimated_cost")),
        "estimated_margin": _to_decimal(form.get("estimated_margin")),
        "estimated_hours": _to_decimal(form.get("estimated_hours")),
        "average_rate": _to_decimal(form.get("average_rate")),
        "cost_center": _safe_strip(form.get("cost_center")),
        "erp_psa_code": _safe_strip(form.get("erp_psa_code")),
        "owner": _safe_strip(form.get("owner")),
        "observations": _safe_strip(form.get("observations")),
    }


def _stakeholder_payload_from_form(form, project_id: int, current_id: int | None = None):
    errors = []
    name = _safe_strip(form.get("name"))
    if len(name) < 2:
        errors.append("El stakeholder debe tener nombre válido.")

    duplicate_stmt = select(Stakeholder.id).where(
        Stakeholder.project_id == project_id,
        Stakeholder.name.ilike(name),
    )
    if current_id:
        duplicate_stmt = duplicate_stmt.where(Stakeholder.id != current_id)
    duplicate_id = db.session.execute(duplicate_stmt).scalar_one_or_none()
    if duplicate_id:
        errors.append("Ya existe un stakeholder con ese nombre en el proyecto.")

    payload = {
        "name": name,
        "role": _safe_strip(form.get("role")),
        "email": _safe_strip(form.get("email")),
        "phone": _safe_strip(form.get("phone")),
        "notes": _safe_strip(form.get("notes")),
    }
    return payload, errors


def _active_menu_context():
    def _catalog_values(catalog_key: str):
        if not g.user:
            return []
        values = db.session.execute(
            select(SystemCatalogOptionConfig.name)
            .where(
                SystemCatalogOptionConfig.owner_user_id == g.user.id,
                SystemCatalogOptionConfig.module_key == "projects",
                SystemCatalogOptionConfig.catalog_key == catalog_key,
                SystemCatalogOptionConfig.is_active.is_(True),
            )
            .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
        ).scalars().all()
        return values

    return {
        "project_types": _catalog_values("project_types"),
        "project_statuses": _catalog_values("project_statuses"),
        "project_priorities": _catalog_values("project_priorities"),
        "project_complexities": _catalog_values("project_complexities"),
        "project_criticalities": _catalog_values("project_criticalities"),
        "project_methodologies": _catalog_values("project_methodologies"),
        "project_close_reasons": _catalog_values("project_close_reasons"),
        "project_close_results": _catalog_values("project_close_results"),
        "project_origins": _catalog_values("project_origins"),
        "task_types": _catalog_values("task_types"),
        "task_statuses": _catalog_values("task_statuses"),
        "task_priorities": _catalog_values("task_priorities"),
        "task_dependency_types": _catalog_values("task_dependency_types"),
        "risk_categories": _catalog_values("risk_categories"),
        "active_resources": db.session.execute(
            select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
        ).scalars().all(),
    }


def _load_project_or_404(project_id: int) -> Project:
    if project_id and not g.user.full_access and g.user.username != "admin":
        allowed_ids = allowed_project_ids(g.user)
        if allowed_ids is not None and project_id not in set(allowed_ids):
            abort(403)

    stmt = (
        select(Project)
        .options(
            selectinload(Project.client),
            selectinload(Project.client_contract),
            selectinload(Project.stakeholders),
            selectinload(Project.tasks),
        )
        .where(Project.id == project_id)
    )
    project = db.session.execute(stmt).scalar_one_or_none()
    if not project:
        abort(404)
    return project


@bp.route("/")
@login_required
def list_projects():
    page = _to_int(request.args.get("page"), default=1)
    search = _safe_strip(request.args.get("q"))
    status = _safe_strip(request.args.get("status"))
    priority = _safe_strip(request.args.get("priority"))
    project_type = _safe_strip(request.args.get("project_type"))
    active = _safe_strip(request.args.get("active", "all"))
    client_id = _to_int(request.args.get("client_id"), default=0)
    stmt = (
        select(Project)
        .options(selectinload(Project.client), selectinload(Project.client_contract))
        .order_by(Project.updated_at.desc())
    )
    allowed_ids = allowed_project_ids(g.user)
    if allowed_ids is not None:
        stmt = stmt.where(Project.id.in_(allowed_ids))

    if search:
        token = f"%{search}%"
        stmt = stmt.where(
            or_(
                Project.name.ilike(token),
                Project.description.ilike(token),
                Project.owner.ilike(token),
            )
        )

    if status:
        stmt = stmt.where(Project.status == status)
    else:
        excluded_statuses = db.session.execute(
            select(SystemCatalogOptionConfig.name).where(
                SystemCatalogOptionConfig.owner_user_id == g.user.id,
                SystemCatalogOptionConfig.module_key == "projects",
                SystemCatalogOptionConfig.catalog_key == "project_statuses",
                SystemCatalogOptionConfig.exclude_from_default_list.is_(True),
                SystemCatalogOptionConfig.is_active.is_(True),
            )
        ).scalars().all()
        if excluded_statuses:
            stmt = stmt.where(Project.status.not_in(excluded_statuses))
    if priority:
        stmt = stmt.where(Project.priority == priority)
    if project_type:
        stmt = stmt.where(Project.project_type == project_type)
    if client_id:
        stmt = stmt.where(Project.client_id == client_id)

    if active in {"1", "0"}:
        stmt = stmt.where(Project.is_active.is_(active == "1"))

    projects_pagination = db.paginate(stmt, page=page, per_page=10, error_out=False)

    clients_stmt = select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    allowed_client_scope = allowed_client_ids(g.user)
    if allowed_client_scope is not None:
        clients_stmt = clients_stmt.where(Client.id.in_(allowed_client_scope))
    clients = db.session.execute(clients_stmt).scalars().all()

    filter_args = {}
    if search:
        filter_args["q"] = search
    if status:
        filter_args["status"] = status
    if priority:
        filter_args["priority"] = priority
    if project_type:
        filter_args["project_type"] = project_type
    if active != "all":
        filter_args["active"] = active
    if client_id:
        filter_args["client_id"] = client_id

    return render_template(
        "projects/project_list.html",
        projects=projects_pagination.items,
        pagination=projects_pagination,
        filter_args=filter_args,
        clients=clients,
        filters={
            "q": search,
            "status": status,
            "priority": priority,
            "project_type": project_type,
            "active": active,
            "client_id": client_id,
        },
        **_active_menu_context(),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_project():
    clients_stmt = select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    allowed_client_scope = allowed_client_ids(g.user)
    if allowed_client_scope is not None:
        clients_stmt = clients_stmt.where(Client.id.in_(allowed_client_scope))
    clients = db.session.execute(clients_stmt).scalars().all()

    parent_stmt = select(Project).where(Project.is_active.is_(True)).order_by(Project.name.asc())
    allowed_project_scope = allowed_project_ids(g.user)
    if allowed_project_scope is not None:
        parent_stmt = parent_stmt.where(Project.id.in_(allowed_project_scope))
    parent_projects = db.session.execute(parent_stmt).scalars().all()

    if not clients:
        flash("Debes crear al menos un cliente antes de dar de alta un proyecto.", "warning")
        return redirect(url_for("clients.list_clients"))

    if request.method == "POST":
        errors = []
        payload = _build_project_payload(request.form)
        name = payload["name"]
        project_type = payload["project_type"]
        status = payload["status"]
        priority = payload["priority"]
        owner = payload["owner"]

        selected_client_id = _to_int(request.form.get("client_id"), default=0)
        selected_contract_id = _to_int(request.form.get("client_contract_id"), default=0)
        selected_parent_project_id = _to_int(request.form.get("parent_project_id"), default=0)
        estimated_start_date = payload["estimated_start_date"]
        estimated_end_date = payload["estimated_end_date"]
        manager_fields = [
            ("Project Manager", payload.get("project_manager_resource_id")),
            ("Responsable comercial", payload.get("commercial_manager_resource_id")),
            ("Responsable funcional", payload.get("functional_manager_resource_id")),
            ("Responsable técnico", payload.get("technical_manager_resource_id")),
        ]

        if len(name) < 3:
            errors.append("El nombre del proyecto debe tener al menos 3 caracteres.")
        if not owner:
            errors.append("Debes indicar un responsable.")
        if project_type not in _active_menu_context()["project_types"]:
            errors.append("El tipo seleccionado no es válido.")
        if status not in _active_menu_context()["project_statuses"]:
            errors.append("El estado seleccionado no es válido.")
        if priority not in _active_menu_context()["project_priorities"]:
            errors.append("La prioridad seleccionada no es válida.")
        for label, resource_id in manager_fields:
            if resource_id:
                resource = db.session.get(Resource, resource_id)
                if not resource or not resource.is_active:
                    errors.append(f"{label} inválido.")

        allowed_client_scope_set = set(allowed_client_scope) if allowed_client_scope is not None else None
        allowed_project_scope_set = set(allowed_project_scope) if allowed_project_scope is not None else None

        client = db.session.get(Client, selected_client_id)
        if not client or not client.is_active:
            errors.append("Debes seleccionar un cliente activo.")
        elif allowed_client_scope_set is not None and selected_client_id not in allowed_client_scope_set:
            errors.append("No tienes alcance sobre el cliente seleccionado.")

        contract = None
        if selected_contract_id:
            contract = db.session.get(ClientContract, selected_contract_id)
            if not contract or contract.client_id != selected_client_id:
                errors.append("El contrato seleccionado no pertenece al cliente.")

        parent_project = None
        if selected_parent_project_id:
            parent_project = db.session.get(Project, selected_parent_project_id)
            if not parent_project:
                errors.append("El proyecto padre seleccionado no existe.")
            elif (
                allowed_project_scope_set is not None
                and selected_parent_project_id not in allowed_project_scope_set
            ):
                errors.append("No tienes alcance sobre el proyecto padre seleccionado.")

        if estimated_start_date and estimated_end_date and estimated_start_date > estimated_end_date:
            errors.append("La fecha estimada de inicio no puede ser posterior a la de fin.")

        contract_file_name, contract_original_name, file_error = _save_contract_file(
            request.files.get("contract")
        )
        if file_error:
            errors.append(file_error)

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "projects/project_form.html",
                project=None,
                clients=clients,
                parent_projects=parent_projects,
                contract_options=_active_contracts_for_client(selected_client_id) if selected_client_id else [],
                form_values=request.form,
                is_edit=False,
                **_active_menu_context(),
            )

        project = Project(
            client_id=selected_client_id,
            client_contract_id=contract.id if contract else None,
            parent_project_id=parent_project.id if parent_project else None,
            contract_file_name=contract_file_name,
            contract_original_name=contract_original_name,
            **payload,
        )
        # Código autogenerado de proyecto: CLIENTE-###.
        if client and not client.client_code:
            client.client_code = generate_client_code(
                Client,
                Client.client_code,
                client.name,
            )
        if not project.project_code and client and client.client_code:
            project.project_code = generate_project_code(
                Project,
                Project.project_code,
                client.client_code,
            )
        db.session.add(project)
        db.session.flush()
        if g.user and not g.user.full_access and g.user.username != "admin":
            assigned = db.session.execute(
                select(UserProjectAssignment.id).where(
                    UserProjectAssignment.user_id == g.user.id,
                    UserProjectAssignment.project_id == project.id,
                )
            ).scalar_one_or_none()
            if not assigned:
                db.session.add(UserProjectAssignment(user_id=g.user.id, project_id=project.id))
        _sync_project_manager_assignments(project, payload)
        db.session.commit()

        flash("Proyecto creado correctamente.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template(
        "projects/project_form.html",
        project=None,
        clients=clients,
        parent_projects=parent_projects,
        contract_options=[],
        form_values={},
        is_edit=False,
        **_active_menu_context(),
    )


@bp.route("/contracts-by-client/<int:client_id>")
@login_required
def contracts_by_client(client_id: int):
    contracts = _active_contracts_for_client(client_id)
    return jsonify(
        [
            {
                "id": contract.id,
                "label": f"{contract.contract_code or '-'} - {contract.contract_name or contract.contract_type}",
            }
            for contract in contracts
        ]
    )


@bp.route("/<int:project_id>")
@login_required
def project_detail(project_id: int):
    project = _load_project_or_404(project_id)
    today = date.today()
    task_total = len(project.tasks)
    task_pending = sum(1 for task in project.tasks if (task.status or "").strip() == "Pendiente")
    task_completed = sum(1 for task in project.tasks if (task.status or "").strip() == "Completada")
    task_milestones = sum(1 for task in project.tasks if task.is_milestone)
    task_blocked = sum(1 for task in project.tasks if (task.status or "").strip() == "Bloqueada")
    task_overdue = sum(
        1
        for task in project.tasks
        if task.due_date and task.due_date < today and (task.status or "").strip() != "Completada"
    )
    return render_template(
        "projects/project_detail.html",
        project=project,
        task_total=task_total,
        task_pending=task_pending,
        task_completed=task_completed,
        task_milestones=task_milestones,
        task_blocked=task_blocked,
        task_overdue=task_overdue,
        **_active_menu_context(),
    )


@bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id: int):
    project = _load_project_or_404(project_id)
    clients_stmt = select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    allowed_client_scope = allowed_client_ids(g.user)
    if allowed_client_scope is not None:
        clients_stmt = clients_stmt.where(Client.id.in_(allowed_client_scope))
    clients = db.session.execute(clients_stmt).scalars().all()

    parent_stmt = (
        select(Project).where(Project.id != project.id, Project.is_active.is_(True)).order_by(Project.name.asc())
    )
    allowed_project_scope = allowed_project_ids(g.user)
    if allowed_project_scope is not None:
        parent_stmt = parent_stmt.where(Project.id.in_(allowed_project_scope))
    parent_projects = db.session.execute(parent_stmt).scalars().all()

    if request.method == "POST":
        errors = []
        payload = _build_project_payload(request.form)
        name = payload["name"]
        project_type = payload["project_type"]
        status = payload["status"]
        priority = payload["priority"]
        owner = payload["owner"]
        selected_client_id = _to_int(request.form.get("client_id"), default=0)
        selected_contract_id = _to_int(request.form.get("client_contract_id"), default=0)
        selected_parent_project_id = _to_int(request.form.get("parent_project_id"), default=0)

        estimated_start_date = payload["estimated_start_date"]
        estimated_end_date = payload["estimated_end_date"]
        manager_fields = [
            ("Project Manager", payload.get("project_manager_resource_id")),
            ("Responsable comercial", payload.get("commercial_manager_resource_id")),
            ("Responsable funcional", payload.get("functional_manager_resource_id")),
            ("Responsable técnico", payload.get("technical_manager_resource_id")),
        ]

        if len(name) < 3:
            errors.append("El nombre del proyecto debe tener al menos 3 caracteres.")
        if not owner:
            errors.append("Debes indicar un responsable.")
        if project_type not in _active_menu_context()["project_types"]:
            errors.append("El tipo seleccionado no es válido.")
        if status not in _active_menu_context()["project_statuses"]:
            errors.append("El estado seleccionado no es válido.")
        if priority not in _active_menu_context()["project_priorities"]:
            errors.append("La prioridad seleccionada no es válida.")
        for label, resource_id in manager_fields:
            if resource_id:
                resource = db.session.get(Resource, resource_id)
                if not resource or not resource.is_active:
                    errors.append(f"{label} inválido.")

        allowed_client_scope_set = set(allowed_client_scope) if allowed_client_scope is not None else None
        allowed_project_scope_set = set(allowed_project_scope) if allowed_project_scope is not None else None

        client = db.session.get(Client, selected_client_id)
        if not client or not client.is_active:
            errors.append("Debes seleccionar un cliente activo.")
        elif allowed_client_scope_set is not None and selected_client_id not in allowed_client_scope_set:
            errors.append("No tienes alcance sobre el cliente seleccionado.")

        contract = None
        if selected_contract_id:
            contract = db.session.get(ClientContract, selected_contract_id)
            if not contract or contract.client_id != selected_client_id:
                errors.append("El contrato seleccionado no pertenece al cliente.")

        parent_project = None
        if selected_parent_project_id:
            parent_project = db.session.get(Project, selected_parent_project_id)
            if not parent_project:
                errors.append("El proyecto padre seleccionado no existe.")
            elif (
                allowed_project_scope_set is not None
                and selected_parent_project_id not in allowed_project_scope_set
            ):
                errors.append("No tienes alcance sobre el proyecto padre seleccionado.")

        if estimated_start_date and estimated_end_date and estimated_start_date > estimated_end_date:
            errors.append("La fecha estimada de inicio no puede ser posterior a la de fin.")

        new_contract_name, new_contract_original_name, file_error = _save_contract_file(
            request.files.get("contract")
        )
        if file_error:
            errors.append(file_error)

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "projects/project_form.html",
                project=project,
                clients=clients,
                parent_projects=parent_projects,
                contract_options=_active_contracts_for_client(selected_client_id) if selected_client_id else [],
                form_values=request.form,
                is_edit=True,
                **_active_menu_context(),
            )

        if new_contract_name:
            if project.contract_file_name:
                old_path = os.path.join(
                    current_app.config["CONTRACT_UPLOAD_FOLDER"], project.contract_file_name
                )
                if os.path.exists(old_path):
                    os.remove(old_path)
            project.contract_file_name = new_contract_name
            project.contract_original_name = new_contract_original_name

        project.client_id = selected_client_id
        project.client_contract_id = contract.id if contract else None
        project.parent_project_id = parent_project.id if parent_project else None
        for key, value in payload.items():
            setattr(project, key, value)
        if client and not client.client_code:
            client.client_code = generate_client_code(
                Client,
                Client.client_code,
                client.name,
            )
        if not project.project_code and client and client.client_code:
            project.project_code = generate_project_code(
                Project,
                Project.project_code,
                client.client_code,
            )

        _sync_project_manager_assignments(project, payload)
        db.session.commit()
        flash("Proyecto actualizado correctamente.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template(
        "projects/project_form.html",
        project=project,
        clients=clients,
        parent_projects=parent_projects,
        contract_options=_active_contracts_for_client(project.client_id),
        form_values={},
        is_edit=True,
        **_active_menu_context(),
    )


@bp.route("/<int:project_id>/stakeholders", methods=["GET", "POST"])
@login_required
def manage_stakeholders(project_id: int):
    project = _load_project_or_404(project_id)
    page = _to_int(request.args.get("page")) or 1

    if request.method == "POST":
        payload, errors = _stakeholder_payload_from_form(request.form, project.id)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            stakeholder = Stakeholder(project_id=project.id, **payload)
            db.session.add(stakeholder)
            db.session.commit()
            flash("Stakeholder agregado.", "success")
            return redirect(url_for("projects.manage_stakeholders", project_id=project.id, page=page))

    stakeholders_pagination = db.paginate(
        select(Stakeholder)
        .where(Stakeholder.project_id == project.id)
        .order_by(Stakeholder.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "projects/project_stakeholders.html",
        project=project,
        stakeholders=stakeholders_pagination.items,
        stakeholders_pagination=stakeholders_pagination,
        current_page=page,
        edit_stakeholder=None,
        form_values={},
        **_active_menu_context(),
    )


@bp.route("/<int:project_id>/stakeholders/<int:stakeholder_id>/edit", methods=["GET", "POST"])
@login_required
def edit_stakeholder(project_id: int, stakeholder_id: int):
    project = _load_project_or_404(project_id)
    page = _to_int(request.args.get("page")) or 1
    stakeholder = db.session.get(Stakeholder, stakeholder_id)
    if not stakeholder or stakeholder.project_id != project.id:
        abort(404)

    if request.method == "POST":
        payload, errors = _stakeholder_payload_from_form(request.form, project.id, current_id=stakeholder.id)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(stakeholder, key, value)
            db.session.commit()
            flash("Stakeholder actualizado.", "success")
            return redirect(url_for("projects.manage_stakeholders", project_id=project.id, page=page))

    stakeholders_pagination = db.paginate(
        select(Stakeholder)
        .where(Stakeholder.project_id == project.id)
        .order_by(Stakeholder.created_at.desc()),
        page=page,
        per_page=10,
        error_out=False,
    )
    return render_template(
        "projects/project_stakeholders.html",
        project=project,
        stakeholders=stakeholders_pagination.items,
        stakeholders_pagination=stakeholders_pagination,
        current_page=page,
        edit_stakeholder=stakeholder,
        form_values=request.form if request.method == "POST" else {},
        **_active_menu_context(),
    )


@bp.route("/<int:project_id>/stakeholders/<int:stakeholder_id>/delete", methods=["POST"])
@login_required
def delete_stakeholder(project_id: int, stakeholder_id: int):
    page = _to_int(request.args.get("page")) or 1
    stakeholder = db.session.get(Stakeholder, stakeholder_id)
    if not stakeholder or stakeholder.project_id != project_id:
        abort(404)
    db.session.delete(stakeholder)
    db.session.commit()
    flash("Stakeholder eliminado.", "info")
    return redirect(url_for("projects.manage_stakeholders", project_id=project_id, page=page))


@bp.route("/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id: int):
    project = _load_project_or_404(project_id)
    if project.status not in {"Cancelado", "Completado"}:
        flash("Solo puedes dar de baja proyectos cancelados o completados.", "warning")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    project.is_active = False
    db.session.commit()
    flash("Proyecto dado de baja correctamente.", "info")
    return redirect(url_for("projects.list_projects"))


@bp.route("/<int:project_id>/contract")
@login_required
def download_contract(project_id: int):
    project = _load_project_or_404(project_id)
    if not project.contract_file_name:
        abort(404)

    return send_from_directory(
        current_app.config["CONTRACT_UPLOAD_FOLDER"],
        project.contract_file_name,
        as_attachment=True,
        download_name=project.contract_original_name or project.contract_file_name,
    )
