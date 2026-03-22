from flask import Blueprint


bp = Blueprint("work", __name__, url_prefix="/work")

from project_manager.blueprints.work import routes  # noqa: E402,F401
