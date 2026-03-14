import os
from datetime import date
from uuid import uuid4

from flask import (
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import login_required
from project_manager.blueprints.projects import bp
from project_manager.extensions import db
from project_manager.models import Client, Project, Stakeholder

PROJECT_TYPES = ["Implementacion", "Mantenimiento", "Soporte", "Consultoria", "Interno"]
PROJECT_STATUSES = ["Planificado", "En progreso", "En pausa", "Completado", "Cancelado"]
PROJECT_PRIORITIES = ["Baja", "Media", "Alta", "Critica"]
ALLOWED_CONTRACT_EXTENSIONS = {"pdf", "doc", "docx"}


def _to_int(value: str, default: int = 1) -> int:
    try:
        converted = int(value)
        return converted if converted > 0 else default
    except (TypeError, ValueError):
        return default


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


def _extract_stakeholders(form):
    names = form.getlist("stakeholder_name[]")
    roles = form.getlist("stakeholder_role[]")
    emails = form.getlist("stakeholder_email[]")
    phones = form.getlist("stakeholder_phone[]")
    notes_list = form.getlist("stakeholder_notes[]")

    max_len = max(len(names), len(roles), len(emails), len(phones), len(notes_list), 0)
    stakeholder_rows = []
    errors = []

    for idx in range(max_len):
        name = _safe_strip(names[idx] if idx < len(names) else "")
        role = _safe_strip(roles[idx] if idx < len(roles) else "")
        email = _safe_strip(emails[idx] if idx < len(emails) else "")
        phone = _safe_strip(phones[idx] if idx < len(phones) else "")
        notes = _safe_strip(notes_list[idx] if idx < len(notes_list) else "")

        if not any([name, role, email, phone, notes]):
            continue

        if len(name) < 2:
            errors.append(f"El stakeholder #{len(stakeholder_rows) + 1} debe tener nombre válido.")

        stakeholder_rows.append(
            {
                "name": name,
                "role": role,
                "email": email,
                "phone": phone,
                "notes": notes,
            }
        )

    normalized_names = [row["name"].lower() for row in stakeholder_rows if row["name"]]
    if len(normalized_names) != len(set(normalized_names)):
        errors.append("No puedes repetir nombres de stakeholders dentro del mismo proyecto.")

    return stakeholder_rows, errors


def _active_menu_context():
    return {
        "project_types": PROJECT_TYPES,
        "project_statuses": PROJECT_STATUSES,
        "project_priorities": PROJECT_PRIORITIES,
    }


def _load_project_or_404(project_id: int) -> Project:
    stmt = (
        select(Project)
        .options(selectinload(Project.client), selectinload(Project.stakeholders))
        .where(Project.id == project_id)
    )
    project = db.session.execute(stmt).scalar_one_or_none()
    if not project:
        abort(404)
    return project


@bp.route("/")
@login_required
def list_projects():
    search = _safe_strip(request.args.get("q"))
    status = _safe_strip(request.args.get("status"))
    priority = _safe_strip(request.args.get("priority"))
    project_type = _safe_strip(request.args.get("project_type"))
    active = _safe_strip(request.args.get("active", "1"))
    client_id = _to_int(request.args.get("client_id"), default=0)
    stmt = select(Project).options(selectinload(Project.client)).order_by(Project.updated_at.desc())

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
    if priority:
        stmt = stmt.where(Project.priority == priority)
    if project_type:
        stmt = stmt.where(Project.project_type == project_type)
    if client_id:
        stmt = stmt.where(Project.client_id == client_id)

    if active in {"1", "0"}:
        stmt = stmt.where(Project.is_active.is_(active == "1"))

    projects = db.session.execute(stmt).scalars().all()

    clients = db.session.execute(
        select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    ).scalars()

    return render_template(
        "projects/project_list.html",
        projects=projects,
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
    clients = db.session.execute(
        select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    ).scalars().all()

    if not clients:
        flash("Debes crear al menos un cliente antes de dar de alta un proyecto.", "warning")
        return redirect(url_for("projects.list_clients"))

    if request.method == "POST":
        errors = []
        name = _safe_strip(request.form.get("name"))
        description = _safe_strip(request.form.get("description"))
        project_type = _safe_strip(request.form.get("project_type"))
        status = _safe_strip(request.form.get("status"))
        priority = _safe_strip(request.form.get("priority"))
        owner = _safe_strip(request.form.get("owner"))
        observations = _safe_strip(request.form.get("observations"))

        selected_client_id = _to_int(request.form.get("client_id"), default=0)
        estimated_start_date = _parse_date(request.form.get("estimated_start_date"))
        estimated_end_date = _parse_date(request.form.get("estimated_end_date"))

        stakeholder_rows, stakeholder_errors = _extract_stakeholders(request.form)
        errors.extend(stakeholder_errors)

        if len(name) < 3:
            errors.append("El nombre del proyecto debe tener al menos 3 caracteres.")
        if not owner:
            errors.append("Debes indicar un responsable.")
        if project_type not in PROJECT_TYPES:
            errors.append("El tipo seleccionado no es válido.")
        if status not in PROJECT_STATUSES:
            errors.append("El estado seleccionado no es válido.")
        if priority not in PROJECT_PRIORITIES:
            errors.append("La prioridad seleccionada no es válida.")

        client = db.session.get(Client, selected_client_id)
        if not client or not client.is_active:
            errors.append("Debes seleccionar un cliente activo.")

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
                stakeholder_rows=stakeholder_rows or [{}],
                form_values=request.form,
                is_edit=False,
                **_active_menu_context(),
            )

        project = Project(
            name=name,
            client_id=selected_client_id,
            description=description,
            project_type=project_type,
            status=status,
            priority=priority,
            estimated_start_date=estimated_start_date,
            estimated_end_date=estimated_end_date,
            owner=owner,
            observations=observations,
            contract_file_name=contract_file_name,
            contract_original_name=contract_original_name,
        )
        project.stakeholders = [Stakeholder(**row) for row in stakeholder_rows]
        db.session.add(project)
        db.session.commit()

        flash("Proyecto creado correctamente.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    return render_template(
        "projects/project_form.html",
        project=None,
        clients=clients,
        stakeholder_rows=[{}],
        form_values={},
        is_edit=False,
        **_active_menu_context(),
    )


@bp.route("/<int:project_id>")
@login_required
def project_detail(project_id: int):
    project = _load_project_or_404(project_id)
    return render_template("projects/project_detail.html", project=project, **_active_menu_context())


@bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
@login_required
def edit_project(project_id: int):
    project = _load_project_or_404(project_id)
    clients = db.session.execute(
        select(Client).where(Client.is_active.is_(True)).order_by(Client.name.asc())
    ).scalars().all()

    if request.method == "POST":
        errors = []
        name = _safe_strip(request.form.get("name"))
        description = _safe_strip(request.form.get("description"))
        project_type = _safe_strip(request.form.get("project_type"))
        status = _safe_strip(request.form.get("status"))
        priority = _safe_strip(request.form.get("priority"))
        owner = _safe_strip(request.form.get("owner"))
        observations = _safe_strip(request.form.get("observations"))
        selected_client_id = _to_int(request.form.get("client_id"), default=0)

        estimated_start_date = _parse_date(request.form.get("estimated_start_date"))
        estimated_end_date = _parse_date(request.form.get("estimated_end_date"))

        stakeholder_rows, stakeholder_errors = _extract_stakeholders(request.form)
        errors.extend(stakeholder_errors)

        if len(name) < 3:
            errors.append("El nombre del proyecto debe tener al menos 3 caracteres.")
        if not owner:
            errors.append("Debes indicar un responsable.")
        if project_type not in PROJECT_TYPES:
            errors.append("El tipo seleccionado no es válido.")
        if status not in PROJECT_STATUSES:
            errors.append("El estado seleccionado no es válido.")
        if priority not in PROJECT_PRIORITIES:
            errors.append("La prioridad seleccionada no es válida.")

        client = db.session.get(Client, selected_client_id)
        if not client or not client.is_active:
            errors.append("Debes seleccionar un cliente activo.")

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
                stakeholder_rows=stakeholder_rows or [{}],
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

        project.name = name
        project.client_id = selected_client_id
        project.description = description
        project.project_type = project_type
        project.status = status
        project.priority = priority
        project.estimated_start_date = estimated_start_date
        project.estimated_end_date = estimated_end_date
        project.owner = owner
        project.observations = observations
        project.stakeholders = [Stakeholder(**row) for row in stakeholder_rows]

        db.session.commit()
        flash("Proyecto actualizado correctamente.", "success")
        return redirect(url_for("projects.project_detail", project_id=project.id))

    stakeholder_rows = [
        {
            "name": stakeholder.name,
            "role": stakeholder.role,
            "email": stakeholder.email,
            "phone": stakeholder.phone,
            "notes": stakeholder.notes,
        }
        for stakeholder in project.stakeholders
    ] or [{}]

    return render_template(
        "projects/project_form.html",
        project=project,
        clients=clients,
        stakeholder_rows=stakeholder_rows,
        form_values={},
        is_edit=True,
        **_active_menu_context(),
    )


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


@bp.route("/clients")
@login_required
def list_clients():
    search = _safe_strip(request.args.get("q"))
    active = _safe_strip(request.args.get("active", "all"))
    stmt = select(Client).order_by(Client.updated_at.desc())
    if search:
        token = f"%{search}%"
        stmt = stmt.where(
            or_(
                Client.name.ilike(token),
                Client.contact_name.ilike(token),
                Client.email.ilike(token),
            )
        )
    if active in {"1", "0"}:
        stmt = stmt.where(Client.is_active.is_(active == "1"))

    clients = db.session.execute(stmt).scalars().all()

    return render_template(
        "projects/client_list.html",
        clients=clients,
        filters={"q": search, "active": active},
        **_active_menu_context(),
    )


@bp.route("/clients/new", methods=["GET", "POST"])
@login_required
def create_client():
    if request.method == "POST":
        errors = []
        name = _safe_strip(request.form.get("name"))
        contact_name = _safe_strip(request.form.get("contact_name"))
        email = _safe_strip(request.form.get("email"))
        phone = _safe_strip(request.form.get("phone"))
        notes = _safe_strip(request.form.get("notes"))

        if len(name) < 2:
            errors.append("El nombre del cliente debe tener al menos 2 caracteres.")

        exists = db.session.execute(
            select(Client).where(func.lower(Client.name) == name.lower())
        ).scalar_one_or_none()
        if exists:
            errors.append("Ya existe un cliente con ese nombre.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "projects/client_form.html",
                client=None,
                form_values=request.form,
                is_edit=False,
                **_active_menu_context(),
            )

        client = Client(name=name, contact_name=contact_name, email=email, phone=phone, notes=notes)
        db.session.add(client)
        db.session.commit()
        flash("Cliente creado correctamente.", "success")
        return redirect(url_for("projects.client_detail", client_id=client.id))

    return render_template(
        "projects/client_form.html",
        client=None,
        form_values={},
        is_edit=False,
        **_active_menu_context(),
    )


@bp.route("/clients/<int:client_id>")
@login_required
def client_detail(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)

    projects = db.session.execute(
        select(Project)
        .where(Project.client_id == client.id)
        .order_by(Project.updated_at.desc())
        .limit(8)
    ).scalars()

    return render_template(
        "projects/client_detail.html",
        client=client,
        projects=projects,
        **_active_menu_context(),
    )


@bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@login_required
def edit_client(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)

    if request.method == "POST":
        errors = []
        name = _safe_strip(request.form.get("name"))
        contact_name = _safe_strip(request.form.get("contact_name"))
        email = _safe_strip(request.form.get("email"))
        phone = _safe_strip(request.form.get("phone"))
        notes = _safe_strip(request.form.get("notes"))
        is_active = request.form.get("is_active") == "1"

        if len(name) < 2:
            errors.append("El nombre del cliente debe tener al menos 2 caracteres.")

        exists = db.session.execute(
            select(Client).where(func.lower(Client.name) == name.lower(), Client.id != client.id)
        ).scalar_one_or_none()
        if exists:
            errors.append("Ya existe otro cliente con ese nombre.")

        active_projects = db.session.execute(
            select(func.count(Project.id)).where(Project.client_id == client.id, Project.is_active.is_(True))
        ).scalar_one()
        if not is_active and active_projects > 0:
            errors.append("No puedes dar de baja un cliente con proyectos activos.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "projects/client_form.html",
                client=client,
                form_values=request.form,
                is_edit=True,
                **_active_menu_context(),
            )

        client.name = name
        client.contact_name = contact_name
        client.email = email
        client.phone = phone
        client.notes = notes
        client.is_active = is_active

        db.session.commit()
        flash("Cliente actualizado correctamente.", "success")
        return redirect(url_for("projects.client_detail", client_id=client.id))

    return render_template(
        "projects/client_form.html",
        client=client,
        form_values={},
        is_edit=True,
        **_active_menu_context(),
    )


@bp.route("/clients/<int:client_id>/delete", methods=["POST"])
@login_required
def delete_client(client_id: int):
    client = db.session.get(Client, client_id)
    if not client:
        abort(404)

    related_projects = db.session.execute(
        select(func.count(Project.id)).where(Project.client_id == client.id)
    ).scalar_one()
    if related_projects > 0:
        flash(
            "No puedes eliminar este cliente porque tiene proyectos asociados. "
            "Elimina primero sus proyectos uno por uno para evitar errores.",
            "warning",
        )
        return redirect(url_for("projects.client_detail", client_id=client.id))

    db.session.delete(client)
    db.session.commit()
    flash("Cliente eliminado correctamente. Esta acción no se puede deshacer.", "info")
    return redirect(url_for("projects.list_clients"))
