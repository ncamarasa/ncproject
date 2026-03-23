from flask import Blueprint

bp = Blueprint("reports", __name__, url_prefix="/reports")

from project_manager.blueprints.reports import routes  # noqa: E402,F401
