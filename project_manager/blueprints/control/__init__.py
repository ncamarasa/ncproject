from flask import Blueprint

bp = Blueprint("control", __name__, url_prefix="/control")

from project_manager.blueprints.control import routes  # noqa: E402,F401
