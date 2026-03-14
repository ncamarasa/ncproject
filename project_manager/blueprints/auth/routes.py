from flask import flash, redirect, render_template, request, session, url_for

from project_manager.blueprints.auth import bp
from project_manager.models import User


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            flash("Bienvenido al panel.", "success")
            return redirect(url_for("main.home"))

        flash("Usuario o contraseña inválidos.", "danger")

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))
