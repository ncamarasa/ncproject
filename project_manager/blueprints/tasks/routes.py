import os
from datetime import date, timedelta
from uuid import uuid4

from flask import abort, current_app, flash, g, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from project_manager.auth_utils import login_required
from project_manager.blueprints.tasks import bp
from project_manager.extensions import db
from project_manager.models import Project, Task, TaskAssignee, TaskAttachment, TaskComment, TaskDependency

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
    stmt = select(Project).options(selectinload(Project.client)).where(Project.id == project_id)
    project = db.session.execute(stmt).scalar_one_or_none()
    if not project:
        abort(404)
    return project


def _ensure_same_project_task_or_none(project_id: int, task_id: int | None):
    if not task_id:
        return None
    task = db.session.get(Task, task_id)
    if not task or task.project_id != project_id:
        return None
    return task


def _validate_task_payload(project_id: int, form, current_task_id: int | None = None):
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
    parent_task = _ensure_same_project_task_or_none(project_id, parent_task_id)
    if parent_task_id and not parent_task:
        errors.append("La tarea padre no pertenece al proyecto.")
    if current_task_id and parent_task_id == current_task_id:
        errors.append("Una tarea no puede ser padre de sí misma.")

    payload = {
        "title": title,
        "description": _safe_strip(form.get("description")),
        "task_type": _safe_strip(form.get("task_type")),
        "status": _safe_strip(form.get("status")),
        "priority": _safe_strip(form.get("priority")),
        "responsible": _safe_strip(form.get("responsible")),
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
            db.session.commit()
            flash("Tarea creada.", "success")
            return redirect(url_for("tasks.manage_tasks", project_id=project.id, page=page))

    tasks_pagination = db.paginate(
        select(Task).where(Task.project_id == project.id).order_by(Task.sort_order.asc(), Task.created_at.desc()),
        page=page,
        per_page=15,
        error_out=False,
    )
    parent_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id).order_by(Task.title.asc())
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
        payload, errors = _validate_task_payload(project.id, request.form, current_task_id=task.id)
        if errors:
            for err in errors:
                flash(err, "danger")
        else:
            for key, value in payload.items():
                setattr(task, key, value)
            db.session.commit()
            flash("Tarea actualizada.", "success")
            return redirect(url_for("tasks.manage_tasks", project_id=project.id, page=page))

    tasks_pagination = db.paginate(
        select(Task).where(Task.project_id == project.id).order_by(Task.sort_order.asc(), Task.created_at.desc()),
        page=page,
        per_page=15,
        error_out=False,
    )
    parent_candidates = db.session.execute(
        select(Task).where(Task.project_id == project.id, Task.id != task.id).order_by(Task.title.asc())
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
    )


@bp.route("/<int:task_id>/delete", methods=["POST"])
@login_required
def delete_task(project_id: int, task_id: int):
    page = _to_int(request.args.get("page")) or 1
    task = _ensure_same_project_task_or_none(project_id, task_id)
    if not task:
        abort(404)
    db.session.delete(task)
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
    return render_template(
        "tasks/task_detail.html",
        project=project,
        task=task,
        predecessor_candidates=predecessor_candidates,
        dependencies=dependencies,
    )


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
