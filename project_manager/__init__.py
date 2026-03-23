import os
import secrets

import click
from flask import Flask, flash, g, redirect, request, session, url_for
from sqlalchemy import select

from project_manager.auth_utils import has_permission, load_logged_in_user
from project_manager.extensions import db, migrate
from project_manager.security import register_audit_listeners
from project_manager.utils.numbers import format_decimal_input, format_decimal_local


def create_app() -> Flask:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )
    default_sqlite_path = os.path.join(app.instance_path, "project_manager.db")
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "cambiar-esto-en-produccion"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", f"sqlite:///{default_sqlite_path}"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CONTRACT_UPLOAD_FOLDER=os.path.join(app.instance_path, "contracts"),
        CLIENT_CONTRACT_UPLOAD_FOLDER=os.path.join(app.instance_path, "client_contracts"),
        CLIENT_DOCUMENT_UPLOAD_FOLDER=os.path.join(app.instance_path, "client_documents"),
        TASK_ATTACHMENT_UPLOAD_FOLDER=os.path.join(app.instance_path, "task_attachments"),
    )

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    from project_manager.models import User  # noqa: F401

    from project_manager.blueprints.auth import bp as auth_bp
    from project_manager.blueprints.clients import bp as clients_bp
    from project_manager.blueprints.control import bp as control_bp
    from project_manager.blueprints.main import bp as main_bp
    from project_manager.blueprints.projects import bp as projects_bp
    from project_manager.blueprints.reports import bp as reports_bp
    from project_manager.blueprints.settings import bp as settings_bp
    from project_manager.blueprints.team import bp as team_bp
    from project_manager.blueprints.tasks import bp as tasks_bp
    from project_manager.blueprints.work import bp as work_bp
    from project_manager.blueprints.administration import bp as administration_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(control_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(work_bp)
    app.register_blueprint(administration_bp)

    app.before_request(load_logged_in_user)

    @app.template_filter("money")
    def money_filter(value, currency_code: str | None = None):
        if value in (None, ""):
            return "-"

        code = (currency_code or "").strip().upper()
        symbols = {
            "ARS": "$",
            "USD": "US$",
            "EUR": "EUR",
            "GBP": "GBP",
            "BRL": "R$",
            "CLP": "CLP$",
            "UYU": "UYU$",
        }
        symbol = symbols.get(code, code if code else "")

        rendered = format_decimal_local(value, 2)
        if rendered == "-":
            return "-"
        if symbol:
            return f"{symbol} {rendered}" if not rendered.startswith("-") else f"-{symbol} {rendered[1:]}"
        return rendered

    @app.template_filter("number")
    def number_filter(value, places: int = 2):
        try:
            places_int = int(places)
        except (TypeError, ValueError):
            places_int = 2
        return format_decimal_local(value, places_int)

    @app.template_filter("decimal_input")
    def decimal_input_filter(value, places: int = 2):
        try:
            places_int = int(places)
        except (TypeError, ValueError):
            places_int = 2
        return format_decimal_input(value, places_int)
    @app.before_request
    def enforce_csrf():
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        if request.endpoint and request.endpoint.startswith("static"):
            return None
        token = session.get("csrf_token")
        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if token and sent_token == token:
            return None
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return ("CSRF token inválido.", 400)
        flash("La sesión del formulario expiró. Intenta nuevamente.", "warning")
        if request.referrer:
            return redirect(request.referrer)
        return redirect(url_for("auth.login"))

    register_audit_listeners()

    @app.context_processor
    def inject_current_user():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {
            "current_user": g.get("user"),
            "user_can": lambda permission: has_permission(g.get("user"), permission),
            "csrf_token": lambda: session["csrf_token"],
        }

    @app.cli.command("create-admin")
    @click.option("--admin-user", default="admin", show_default=True)
    @click.option("--admin-password", default="admin123", show_default=True)
    def create_admin(admin_user: str, admin_password: str) -> None:
        """Crea un usuario admin inicial si no existe."""
        from project_manager.models import Permission, Role, RolePermission, User
        from project_manager.services.permission_catalog import ensure_permission_catalog

        existing = User.query.filter_by(username=admin_user).first()
        if existing:
            click.echo(f"Usuario '{admin_user}' ya existe.")
            return

        role = db.session.execute(select(Role).where(Role.name == "Administrador")).scalar_one_or_none()
        if not role:
            role = Role(
                name="Administrador",
                description="Acceso completo al sistema",
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
            db.session.add(role)
            db.session.flush()

        ensure_permission_catalog()
        permissions = db.session.execute(select(Permission).where(Permission.is_active.is_(True))).scalars().all()
        for perm in permissions:
            link = db.session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == perm.id,
                )
            ).scalar_one_or_none()
            if not link:
                db.session.add(RolePermission(role_id=role.id, permission_id=perm.id))

        admin = User(username=admin_user)
        admin.set_password(admin_password)
        admin.role_id = role.id
        admin.full_access = True
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Usuario '{admin_user}' creado.")

    return app
