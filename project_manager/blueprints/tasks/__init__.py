from flask import Blueprint


bp = Blueprint("tasks", __name__, url_prefix="/projects/<int:project_id>/tasks")

from project_manager.blueprints.tasks import routes  # noqa: E402,F401
