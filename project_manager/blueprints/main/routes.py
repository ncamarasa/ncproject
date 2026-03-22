from flask import g, redirect, render_template, url_for
from sqlalchemy import func, select

from project_manager.auth_utils import (
    allowed_client_ids,
    allowed_project_ids,
    has_permission,
    login_required,
)
from project_manager.blueprints.main import bp
from project_manager.extensions import db
from project_manager.models import Client, Project, Stakeholder


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("main.home"))
    return redirect(url_for("auth.login"))


@bp.route("/home")
@login_required
def home():
    if not has_permission(g.user, "main.view"):
        if has_permission(g.user, "work.view"):
            return redirect(url_for("work.my_tasks"))
        if has_permission(g.user, "projects.view"):
            return redirect(url_for("projects.list_projects"))
        if has_permission(g.user, "clients.view"):
            return redirect(url_for("clients.list_clients"))
        if has_permission(g.user, "control.view"):
            return redirect(url_for("control.dashboard"))
        return redirect(url_for("auth.login"))

    active_projects = 0
    active_clients = 0
    active_stakeholders = 0

    if has_permission(g.user, "projects.view"):
        projects_stmt = select(func.count(Project.id)).where(Project.is_active.is_(True))
        project_scope = allowed_project_ids(g.user)
        if project_scope is not None:
            projects_stmt = projects_stmt.where(Project.id.in_(project_scope))
        active_projects = db.session.execute(projects_stmt).scalar_one()

        stakeholders_stmt = (
            select(func.count(Stakeholder.id))
            .join(Project, Stakeholder.project_id == Project.id)
            .where(Stakeholder.is_active.is_(True), Project.is_active.is_(True))
        )
        if project_scope is not None:
            stakeholders_stmt = stakeholders_stmt.where(Project.id.in_(project_scope))
        active_stakeholders = db.session.execute(stakeholders_stmt).scalar_one()

    if has_permission(g.user, "clients.view"):
        clients_stmt = select(func.count(Client.id)).where(Client.is_active.is_(True))
        client_scope = allowed_client_ids(g.user)
        if client_scope is not None:
            clients_stmt = clients_stmt.where(Client.id.in_(client_scope))
        active_clients = db.session.execute(clients_stmt).scalar_one()

    return render_template(
        "dashboard/home.html",
        username=g.user.username,
        active_projects=active_projects,
        active_clients=active_clients,
        active_stakeholders=active_stakeholders,
    )
