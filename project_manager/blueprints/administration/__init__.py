from flask import Blueprint

bp = Blueprint("administration", __name__, url_prefix="/administration")

from project_manager.blueprints.administration import routes  # noqa: E402,F401
