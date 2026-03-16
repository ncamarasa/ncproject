import os
from datetime import date, timedelta
from uuid import uuid4

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy import case, select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.tasks import bp
from project_manager.extensions import db
from project_manager.models import (
    Project,
    Resource,
    SystemCatalogOptionConfig,
    Task,
    TaskAssignee,
    TaskAttachment,
    TaskComment,
    TaskDependency,
    TaskResource,
)
from project_manager.services.task_business_rules import (
    CLOSED_STATUSES,
    has_open_subtasks,
    is_closed_status,
    recalculate_parent_task,
    task_has_subtasks,
    validate_parent_assignment,
)
from project_manager.services.team_business_rules import (
    validate_assignment,
    validate_task_assignment_project_consistency,
)

TASK_ALLOWED_ATTACHMENT_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "png",
    "jpg",
    "jpeg",
    "txt",
}


@bp.before_request
def _authorize_tasks_module():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    is_write = request.method not in {"GET", "HEAD", "OPTIONS"}
    needed_permission = "tasks.edit" if is_write else "tasks.view"
    if is_write and g.user.read_only:
        flash("Tu usuario es de solo lectura.", "danger")
        return redirect(url_for("main.home"))
    if not has_permission(g.user, needed_permission):
        flash("No tienes permisos para acceder al módulo de tareas.", "danger")
        return redirect(url_for("main.home"))


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
        return float(value)
    except ValueError:
        return None


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _load_project_or_404(project_id: int) -> Project:
    if project_id and not g.user.full_access and g.user.username != "admin":
        allowed_ids = allowed_project_ids(g.user)
        if allowed_ids is not None and project_id not in set(allowed_ids):
            abort(403)
    stmt = select(Project).options(selectinload(Project.client)).where(Project.id == project_id)
    project = db.session.execute(stmt).scalar_one_or_none()
    if not project:
        abort(404)
    return project


def _task_list_stmt(project_id: int):
    root_task_id = case(
        (Task.parent_task_id.is_(None), Task.id),
        else_=Task.parent_task_id,
    )


def _task_status_options() -> list[str]:
    if not g.get("user"):
        return []
    return db.session.execute(
        select(SystemCatalogOptionConfig.name)
        .where(
            SystemCatalogOptionConfig.owner_user_id == g.user.id,
            SystemCatalogOptionConfig.module_key == "projects",
            SystemCatalogOptionConfig.catalog_key == "task_statuses",
            SystemCatalogOptionConfig.is_active.is_(True),
        )
        .order_by(SystemCatalogOptionConfig.is_system.asc(), SystemCatalogOptionConfig.name.asc())
    ).scalars().all()
    parent_first = case((Task.parent_task_id.is_(None), 0), else_=1)
    return (
        select(Task)
        .where(Task.project_id == project_id)
        .options(selectinload(Task.parent_task))
        .order_by(
            Task.sort_order.asc(),
            root_task_id.asc(),
            parent_first.asc(),
            Task.id.asc(),
        )
    )


def _task_children_metadata(tasks: list[Task]):
    child_count_by_parent = {}
    for task in tasks:
        if task.parent_task_id:
            child_count_by_parent[task.parent_task_id] = child_count_by_parent.get(task.parent_task_id, 0) + 1
    parent_task_ids = sorted(child_count_by_parent.keys())
    return parent_task_ids, child_count_by_parent


def _ensure_same_project_task_or_none(project_id: int, task_id: int | None):
    if not task_id:
        return None
    task = db.session.get(Task, task_id)
    if not task or task.project_id != project_id:
        return None
    return task


def _validate_task_payload(project_id: int, form, current_task_id: int | None = None, current_task: Task | None = None):
    errors = []
    title = _safe_strip(form.get("title"))
    if len(title) < 3:
        errors.append("El título de la tarea debe tener al menos 3 caracteres.")

    start_date = _parse_date(form.get("start_date"))
    due_date = _parse_date(form.get("due_date"))
    estimated_duration_days = _to_int(form.get("estimated_duration_days"))
    estimated_hours = _to_decimal(form.get("estimated_hours"))
    logged_hours = _to_decimal(form.get("logged_hours"))

    # Duración (calendario) y esfuerzo (horas) son conceptos distintos.
    # Reglas:
    # 1) Si hay inicio + fin -> calcular duración automáticamente.
    # 2) Si hay inicio + duración y no hay fin -> autocompletar fin.
    if start_date and due_date:
        estimated_duration_days = (due_date - start_date).days + 1
    elif start_date and estimated_duration_days and not due_date:
        due_date = start_date + timedelta(days=max(estimated_duration_days, 1) - 1)
    actual_start_date = _parse_date(form.get("actual_start_date"))
    actual_end_date = _parse_date(form.get("actual_end_date"))
    if start_date and due_date and start_date > due_date:
        errors.append("La fecha de inicio no puede ser posterior al vencimiento.")
    if estimated_duration_days is not None and estimated_duration_days <= 0:
        errors.append("La duración debe ser mayor a 0 días.")
    if estimated_hours is not None and estimated_hours < 0:
        errors.append("El esfuerzo estimado no puede ser negativo.")
    if logged_hours is not None and logged_hours < 0:
        errors.append("Las horas imputadas no pueden ser negativas.")
    if actual_start_date and actual_end_date and actual_start_date > actual_end_date:
        errors.append("La fecha real de inicio no puede ser posterior al cierre real.")

    progress_percent = _to_int(form.get("progress_percent"))
    if progress_percent is not None and not 0 <= progress_percent <= 100:
        errors.append("El porcentaje de avance debe estar entre 0 y 100.")

    parent_task_id = _to_int(form.get("parent_task_id"))
    errors.extend(validate_parent_assignment(project_id, parent_task_id, current_task_id))

    status_value = _safe_strip(form.get("status"))
    if current_task and task_has_subtasks(current_task.id):
        # Campos calculados: no pueden editarse manualmente si la tarea es padre.
        if start_date != current_task.start_date or due_date != current_task.due_date:
            errors.append("Las fechas del padre se calculan automáticamente a partir de sus subtareas.")
        if (progress_percent if progress_percent is not None else 0) != (current_task.progress_percent or 0):
            errors.append("El avance del padre se calcula automáticamente a partir de sus subtareas.")
        if logged_hours not in (None, 0):
            errors.append("No se permite imputación directa de horas en tareas padre con subtareas.")
        if is_closed_status(status_value) and has_open_subtasks(current_task.id):
            errors.append("No se puede cerrar una tarea padre con subtareas abiertas.")

    responsible_resource_id = _to_int(form.get("responsible_resource_id"))
    responsible_name = _safe_strip(form.get("responsible"))
    if responsible_resource_id:
        resource = db.session.get(Resource, responsible_resource_id)
        if not resource or not resource.is_active:
            errors.append("El responsable seleccionado no es válido.")
        else:
            responsible_name = resource.full_name

    payload = {
        "title": title,
        "description": _safe_strip(form.get("description")),
        "task_type": _safe_strip(form.get("task_type")),
        "status": status_value,
        "priority": _safe_strip(form.get("priority")),
        "responsible": responsible_name,
        "responsible_resource_id": responsible_resource_id,
        "creator": _safe_strip(form.get("creator")) or (g.user.username if g.user else None),
        "parent_task_id": parent_task_id,
        "start_date": start_date,
        "due_date": due_date,
        "actual_start_date": actual_start_date,
        "actual_end_date": actual_end_date,
        "estimated_duration_days": estimated_duration_days,
        "estimated_hours": estimated_hours,
        "logged_hours": logged_hours,
        "progress_percent": progress_percent if progress_percent is not None else 0,
        "sort_order": _to_int(form.get("sort_order")) or 0,
        "tags": _safe_strip(form.get("tags")),
        "is_milestone": form.get("is_milestone") == "1",
    }
    return payload, errors


def _is_attachment_allowed(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in TASK_ALLOWED_ATTACHMENT_EXTENSIONS


def _save_task_attachment(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None, None

    original_name = secure_filename(file_storage.filename)
    if not original_name or not _is_attachment_allowed(original_name):
        return None, None, "Formato de adjunto no permitido."

    ext = original_name.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid4().hex}.{ext}"
    folder = current_app.config["TASK_ATTACHMENT_UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    file_storage.save(os.path.join(folder, stored_name))
    return stored_name, original_name, None


def _build_adjacency_for_project(project_id: int):
    deps = db.session.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.predecessor_task_id == Task.id)
        .where(Task.project_id == project_id)
    ).scalars().all()
    graph = {}
    for dep in deps:
        graph.setdefault(dep.predecessor_task_id, set()).add(dep.successor_task_id)
    return graph


def _has_path(graph: dict[int, set[int]], start: int, target: int) -> bool:
    stack = [start]
    seen = set()
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(graph.get(current, ()))
    return False


@bp.route("/", methods=["GET", "POST"])
@login_required
def manage_tasks(project_id: int):
    project = _load_project_or_404(project_id)
    page = _to_int(request.args.get("page")) or 1
    edit_task_id = _to_int(request.args.get("edit_id"))
    edit_task = _ensure_same_project_task_or_none(project.id, edit_task_id)

    if request.method == "POST":
        payload, errors = _validate_task_payload(project.id, request.form)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            task = Task(project_id=project.id, **payload)
            db.session.add(task)
            db.session.flush()
            if task.parent_task_id:
                recalculate_parent_task(
                    task.parent_task_id,
                    reason="subtask_created",
                    trigger_task_id=task.id,
                )
            db.session.commit()
            flash("Tarea creada.", "success")
            return redirect(url_for("tasks.manage_tasks", project_id=project.id, page=page))

    tasks_pagination = db.paginate(_task_list_stmt(project.id), page=page, per_page=15, error_out=False)
    parent_task_ids, child_count_by_parent = _task_children_metadata(tasks_pagination.items)
    parent_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id, Task.parent_task_id.is_(None)).order_by(Task.title.asc())
    ).scalars().all()
    active_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    return render_template(
        "tasks/task_list.html",
        project=project,
        tasks=tasks_pagination.items,
        tasks_pagination=tasks_pagination,
        parent_candidates=parent_candidates,
        edit_task=edit_task,
        form_values=request.form if request.method == "POST" else {},
        current_page=page,
        parent_task_ids=parent_task_ids,
        child_count_by_parent=child_count_by_parent,
        edit_task_has_subtasks=task_has_subtasks(edit_task.id) if edit_task else False,
        edit_task_open_subtasks=has_open_subtasks(edit_task.id) if edit_task else False,
        task_statuses=_task_status_options(),
        closed_statuses=sorted(CLOSED_STATUSES),
        active_resources=active_resources,
    )


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
@login_required
def edit_task(project_id: int, task_id: int):
    project = _load_project_or_404(project_id)
    task = _ensure_same_project_task_or_none(project.id, task_id)
    if not task:
        abort(404)

    page = _to_int(request.args.get("page")) or 1
    if request.method == "POST":
        old_parent_id = task.parent_task_id
        payload, errors = _validate_task_payload(project.id, request.form, current_task_id=task.id, current_task=task)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(task, key, value)
            db.session.flush()
            if old_parent_id and old_parent_id != task.parent_task_id:
                recalculate_parent_task(old_parent_id, reason="subtask_moved", trigger_task_id=task.id)
            if task.parent_task_id:
                recalculate_parent_task(task.parent_task_id, reason="subtask_updated", trigger_task_id=task.id)
            db.session.commit()
            flash("Tarea actualizada.", "success")
            return redirect(url_for("tasks.manage_tasks", project_id=project.id, page=page))

    tasks_pagination = db.paginate(_task_list_stmt(project.id), page=page, per_page=15, error_out=False)
    parent_task_ids, child_count_by_parent = _task_children_metadata(tasks_pagination.items)
    parent_candidates = db.session.execute(
        select(Task)
        .where(Task.project_id == project.id, Task.parent_task_id.is_(None), Task.id != task.id)
        .order_by(Task.title.asc())
    ).scalars().all()
    active_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    return render_template(
        "tasks/task_list.html",
        project=project,
        tasks=tasks_pagination.items,
        tasks_pagination=tasks_pagination,
        parent_candidates=parent_candidates,
        edit_task=task,
        form_values=request.form if request.method == "POST" else {},
        current_page=page,
        parent_task_ids=parent_task_ids,
        child_count_by_parent=child_count_by_parent,
        edit_task_has_subtasks=task_has_subtasks(task.id),
        edit_task_open_subtasks=has_open_subtasks(task.id),
        task_statuses=_task_status_options(),
        closed_statuses=sorted(CLOSED_STATUSES),
        active_resources=active_resources,
    )


@bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(project_id: int, task_id: int):
    page = _to_int(request.args.get("page")) or 1
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)
    parent_id = task.parent_task_id
    db.session.delete(task)
    db.session.flush()
    if parent_id:
        recalculate_parent_task(parent_id, reason="subtask_deleted", trigger_task_id=task_id)
    db.session.commit()
    flash("Tarea eliminada.", "info")
    return redirect(url_for("tasks.manage_tasks", project_id=project_id, page=page))


@bp.route("/<int:task_id>/dependencies", methods=["POST"])
@login_required
def add_dependency(project_id: int, task_id: int):
    successor = _ensure_same_project_task_or_none(project_id, task_id)
    predecessor_id = _to_int(request.form.get("predecessor_task_id"))
    dependency_type = _safe_strip(request.form.get("dependency_type"))
    if not successor:
        abort(404)
    predecessor = _ensure_same_project_task_or_none(project_id, predecessor_id)
    if not predecessor:
        flash("La tarea predecesora no es válida.", "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))
    if predecessor.id == successor.id:
        flash("Una tarea no puede depender de sí misma.", "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    exists = db.session.execute(
        select(TaskDependency).where(
            TaskDependency.predecessor_task_id == predecessor.id,
            TaskDependency.successor_task_id == successor.id,
        )
    ).scalar_one_or_none()
    if exists:
        flash("La dependencia ya existe.", "warning")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    graph = _build_adjacency_for_project(project_id)
    if _has_path(graph, successor.id, predecessor.id):
        flash("No se puede crear dependencia circular.", "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    db.session.add(
        TaskDependency(
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
            dependency_type=dependency_type,
        )
    )
    db.session.commit()
    flash("Dependencia agregada.", "success")
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))


@bp.route("/dependencies/<int:dependency_id>/delete", methods=["POST"])
@login_required
def delete_dependency(project_id: int, dependency_id: int):
    dep = db.session.get(TaskDependency, dependency_id)
    if not dep:
        abort(404)
    predecessor = db.session.get(Task, dep.predecessor_task_id)
    successor = db.session.get(Task, dep.successor_task_id)
    if not predecessor or not successor or predecessor.project_id != project_id or successor.project_id != project_id:
        abort(404)
    target_task_id = successor.id
    db.session.delete(dep)
    db.session.commit()
    flash("Dependencia eliminada.", "info")
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=target_task_id))


@bp.route("/<int:task_id>", methods=["GET", "POST"])
@login_required
def task_detail(project_id: int, task_id: int):
    project = _load_project_or_404(project_id)
    task = _ensure_same_project_task_or_none(project.id, task_id)
    if not task:
        abort(404)

    if request.method == "POST":
        comment_body = _safe_strip(request.form.get("comment_body"))
        if comment_body:
            db.session.add(
                TaskComment(
                    task_id=task.id,
                    author=g.user.username if g.user else None,
                    body=comment_body,
                )
            )
            flash("Comentario agregado.", "success")

        file_name, original_name, error = _save_task_attachment(request.files.get("attachment"))
        if error:
            flash(error, "danger")
        elif file_name:
            db.session.add(
                TaskAttachment(
                    task_id=task.id,
                    file_name=file_name,
                    original_name=original_name,
                    uploaded_by=g.user.username if g.user else None,
                )
            )
            flash("Adjunto agregado.", "success")

        db.session.commit()
        return redirect(url_for("tasks.task_detail", project_id=project.id, task_id=task.id))

    predecessor_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id, Task.id != task.id).order_by(Task.title.asc())
    ).scalars().all()

    dependencies = db.session.execute(
        select(TaskDependency)
        .where(
            (TaskDependency.predecessor_task_id == task.id)
            | (TaskDependency.successor_task_id == task.id)
        )
        .options(
            selectinload(TaskDependency.predecessor_task),
            selectinload(TaskDependency.successor_task),
        )
    ).scalars().all()
    collaborators = db.session.execute(
        select(TaskResource)
        .where(TaskResource.task_id == task.id, TaskResource.is_active.is_(True))
        .options(selectinload(TaskResource.resource))
        .order_by(TaskResource.id.desc())
    ).scalars().all()
    available_resources = db.session.execute(
        select(Resource).where(Resource.is_active.is_(True)).order_by(Resource.full_name.asc())
    ).scalars().all()
    return render_template(
        "tasks/task_detail.html",
        project=project,
        task=task,
        predecessor_candidates=predecessor_candidates,
        dependencies=dependencies,
        task_statuses=_task_status_options(),
        closed_statuses=sorted(CLOSED_STATUSES),
        task_has_open_subtasks=has_open_subtasks(task.id),
        collaborators=collaborators,
        available_resources=available_resources,
    )


@bp.route("/<int:task_id>/collaborators/add", methods=["POST"])
@login_required
def add_task_collaborator(project_id: int, task_id: int):
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)

    resource_id = _to_int(request.form.get("resource_id"))
    if not resource_id:
        flash("Selecciona un recurso.", "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    errors = validate_assignment(resource_id, role_id=None)
    errors.extend(validate_task_assignment_project_consistency(task.id, resource_id))
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    exists = db.session.execute(
        select(TaskResource.id).where(
            TaskResource.task_id == task.id,
            TaskResource.resource_id == resource_id,
            TaskResource.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if exists:
        flash("El colaborador ya está asignado.", "warning")
    else:
        db.session.add(TaskResource(task_id=task.id, resource_id=resource_id, is_primary=False, is_active=True))
        db.session.commit()
        flash("Colaborador agregado.", "success")
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))


@bp.route("/collaborators/<int:assignment_id>/delete", methods=["POST"])
@login_required
def delete_task_collaborator(project_id: int, assignment_id: int):
    assignment = db.session.get(TaskResource, assignment_id)
    if not assignment:
        abort(404)
    task = db.session.get(Task, assignment.task_id)
    if not task or task.project_id != project_id:
        abort(404)
    db.session.delete(assignment)
    db.session.commit()
    flash("Colaborador removido.", "info")
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task.id))


@bp.route("/<int:task_id>/status", methods=["POST"])
@login_required
def update_task_status(project_id: int, task_id: int):
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)

    next_status = _safe_strip(request.form.get("status"))
    if not next_status:
        flash("Debes seleccionar un estado.", "warning")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    if task_has_subtasks(task.id) and is_closed_status(next_status) and has_open_subtasks(task.id):
        flash("No se puede cerrar la tarea mientras tenga subtareas abiertas.", "danger")
        return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))

    previous_status = task.status
    task.status = next_status
    db.session.flush()
    if task.parent_task_id and previous_status != next_status:
        recalculate_parent_task(task.parent_task_id, reason="subtask_status_updated", trigger_task_id=task.id)
    db.session.commit()
    flash("Estado actualizado.", "success")
    return redirect(url_for("tasks.task_detail", project_id=project_id, task_id=task_id))


@bp.route("/attachments/<int:attachment_id>/download")
@login_required
def download_attachment(project_id: int, attachment_id: int):
    attachment = db.session.get(TaskAttachment, attachment_id)
    if not attachment:
        abort(404)
    task = db.session.get(Task, attachment.task_id)
    if not task or task.project_id != project_id:
        abort(404)
    return send_from_directory(
        current_app.config["TASK_ATTACHMENT_UPLOAD_FOLDER"],
        attachment.file_name,
        as_attachment=True,
        download_name=attachment.original_name,
    )


@bp.route("/gantt")
@login_required
def gantt(project_id: int):
    project = _load_project_or_404(project_id)
    tasks = db.session.execute(
        select(Task).where(Task.project_id == project.id).order_by(Task.start_date.asc().nullslast(), Task.id.asc())
    ).scalars().all()
    dependencies = db.session.execute(
        select(TaskDependency)
        .join(Task, TaskDependency.successor_task_id == Task.id)
        .where(Task.project_id == project.id)
        .order_by(TaskDependency.id.asc())
    ).scalars().all()
    dependency_by_successor = {}
    for dep in dependencies:
        dependency_by_successor.setdefault(dep.successor_task_id, []).append(dep.predecessor_task_id)

    duration_by_task_id = {}
    for task in tasks:
        if task.start_date and task.due_date:
            duration_by_task_id[task.id] = (task.due_date - task.start_date).days + 1
        else:
            duration_by_task_id[task.id] = task.estimated_duration_days

    return render_template(
        "tasks/gantt.html",
        project=project,
        tasks=tasks,
        dependency_by_successor=dependency_by_successor,
        duration_by_task_id=duration_by_task_id,
    )
