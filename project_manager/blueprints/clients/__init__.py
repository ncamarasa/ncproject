from flask import Blueprint

bp = Blueprint("clients", __name__, url_prefix="/clients")

from project_manager.blueprints.clients import routes  # noqa: E402,F401
