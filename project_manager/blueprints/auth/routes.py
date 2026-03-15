from datetime import datetime

from flask import flash, redirect, render_template, request, session, url_for

from project_manager.blueprints.auth import bp
from project_manager.extensions import db
from project_manager.models import AccessAuditLog, User


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            user.last_login_at = datetime.utcnow()
            db.session.add(
                AccessAuditLog(
                    user_id=user.id,
                    username=user.username,
                    event="login",
                    outcome="success",
                    ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                    user_agent=(request.user_agent.string or "")[:255],
                )
            )
            db.session.commit()
            flash("Bienvenido al panel.", "success")
            return redirect(url_for("main.home"))

        db.session.add(
            AccessAuditLog(
                user_id=user.id if user else None,
                username=username or None,
                event="login",
                outcome="failure",
                reason="Credenciales inválidas o usuario inactivo",
                ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
                user_agent=(request.user_agent.string or "")[:255],
            )
        )
        db.session.commit()
        flash("Usuario o contraseña inválidos.", "danger")

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("user_id")
    username = None
    if user_id:
        user = db.session.get(User, user_id)
        username = user.username if user else None
    db.session.add(
        AccessAuditLog(
            user_id=user_id,
            username=username,
            event="logout",
            outcome="success",
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=(request.user_agent.string or "")[:255],
        )
    )
    db.session.commit()
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))
