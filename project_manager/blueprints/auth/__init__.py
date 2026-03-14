from flask import Blueprint

bp = Blueprint("auth", __name__)

from project_manager.blueprints.auth import routes  # noqa: E402,F401
