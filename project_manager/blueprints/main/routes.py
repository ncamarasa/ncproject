from flask import g, redirect, render_template, url_for
from sqlalchemy import func, select

from project_manager.auth_utils import login_required
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
    active_projects = db.session.execute(
        select(func.count(Project.id)).where(Project.is_active.is_(True))
    ).scalar_one()
    active_clients = db.session.execute(
        select(func.count(Client.id)).where(Client.is_active.is_(True))
    ).scalar_one()
    active_stakeholders = db.session.execute(
        select(func.count(Stakeholder.id))
        .join(Project, Stakeholder.project_id == Project.id)
        .where(Stakeholder.is_active.is_(True), Project.is_active.is_(True))
    ).scalar_one()

    return render_template(
        "dashboard/home.html",
        username=g.user.username,
        active_projects=active_projects,
        active_clients=active_clients,
        active_stakeholders=active_stakeholders,
    )
