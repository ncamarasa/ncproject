from flask import g, redirect, render_template, url_for

from project_manager.auth_utils import login_required
from project_manager.blueprints.main import bp


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("main.home"))
    return redirect(url_for("auth.login"))


@bp.route("/home")
@login_required
def home():
    return render_template("dashboard/home.html", username=g.user.username)
