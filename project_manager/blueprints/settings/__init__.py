from flask import Blueprint

bp = Blueprint("settings", __name__, url_prefix="/settings")

from project_manager.blueprints.settings import routes  # noqa: E402,F401
