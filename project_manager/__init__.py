import os

import click
from flask import Flask, g

from project_manager.auth_utils import load_logged_in_user
from project_manager.extensions import db, migrate


def create_app() -> Flask:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder=os.path.join(project_root, "templates"),
        static_folder=os.path.join(project_root, "static"),
    )
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "cambiar-esto-en-produccion"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///project_manager.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CONTRACT_UPLOAD_FOLDER=os.path.join(app.instance_path, "contracts"),
    )

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    from project_manager.models import User  # noqa: F401

    from project_manager.blueprints.auth import bp as auth_bp
    from project_manager.blueprints.main import bp as main_bp
    from project_manager.blueprints.projects import bp as projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(projects_bp)

    app.before_request(load_logged_in_user)

    @app.context_processor
    def inject_current_user():
        return {"current_user": g.get("user")}

    @app.cli.command("create-admin")
    @click.option("--admin-user", default="admin", show_default=True)
    @click.option("--admin-password", default="admin123", show_default=True)
    def create_admin(admin_user: str, admin_password: str) -> None:
        """Crea un usuario admin inicial si no existe."""
        from project_manager.models import User

        existing = User.query.filter_by(username=admin_user).first()
        if existing:
            click.echo(f"Usuario '{admin_user}' ya existe.")
            return

        admin = User(username=admin_user)
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Usuario '{admin_user}' creado.")

    return app
