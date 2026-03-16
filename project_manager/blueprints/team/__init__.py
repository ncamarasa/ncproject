from flask import Blueprint

bp = Blueprint("team", __name__, url_prefix="/team")

from project_manager.blueprints.team import routes  # noqa: E402,F401
