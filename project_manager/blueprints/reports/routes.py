from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from project_manager.auth_utils import allowed_project_ids, has_permission, login_required
from project_manager.blueprints.reports import bp
from project_manager.extensions import db
from project_manager.models import Project, ProjectCurrencyRateConfig, ResourceCost, Task, TaskWorklog
from project_manager.services.team_business_rules import find_applicable_cost_id

INTERNAL_PROJECT_CODE = "SYS-INTERNAL"
INTERNAL_PROJECT_NAME = "Proyecto Interno"


def _safe_strip(value: str | None) -> str:
    return (value or "").strip()


def _parse_month(value: str | None) -> tuple[int, int]:
    raw = _safe_strip(value)
    if not raw:
        today = date.today()
        return today.year, today.month
    try:
        dt = datetime.strptime(raw, "%Y-%m")
        return dt.year, dt.month
    except ValueError:
        today = date.today()
        return today.year, today.month


def _hourly_cost(cost: ResourceCost | None) -> Decimal | None:
    if not cost:
        return None
    if cost.hourly_cost is not None:
        return Decimal(cost.hourly_cost)
    if cost.monthly_cost is not None:
        return Decimal(cost.monthly_cost) / Decimal("160")
    return None


def _convert_currency_amount(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    *,
    owner_user_id: int | None,
    reference_date: date,
) -> tuple[Decimal | None, str | None]:
    source = _safe_strip(from_currency).upper()
    target = _safe_strip(to_currency).upper()
    if not source or not target:
        return None, "Moneda de origen/destino inválida."
    if source == target:
        return amount, None
    if not owner_user_id:
        return None, f"No hay usuario de configuración para convertir {source}->{target}."

    direct = db.session.execute(
        select(ProjectCurrencyRateConfig)
        .where(
            ProjectCurrencyRateConfig.owner_user_id == owner_user_id,
            ProjectCurrencyRateConfig.is_active.is_(True),
            ProjectCurrencyRateConfig.from_currency == source,
            ProjectCurrencyRateConfig.to_currency == target,
            ProjectCurrencyRateConfig.valid_from <= reference_date,
            (ProjectCurrencyRateConfig.valid_to.is_(None) | (ProjectCurrencyRateConfig.valid_to >= reference_date)),
        )
        .order_by(ProjectCurrencyRateConfig.valid_from.desc(), ProjectCurrencyRateConfig.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if direct:
        return amount * Decimal(direct.rate), None

    reverse = db.session.execute(
        select(ProjectCurrencyRateConfig)
        .where(
            ProjectCurrencyRateConfig.owner_user_id == owner_user_id,
            ProjectCurrencyRateConfig.is_active.is_(True),
            ProjectCurrencyRateConfig.from_currency == target,
            ProjectCurrencyRateConfig.to_currency == source,
            ProjectCurrencyRateConfig.valid_from <= reference_date,
            (ProjectCurrencyRateConfig.valid_to.is_(None) | (ProjectCurrencyRateConfig.valid_to >= reference_date)),
        )
        .order_by(ProjectCurrencyRateConfig.valid_from.desc(), ProjectCurrencyRateConfig.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if reverse and Decimal(reverse.rate) != 0:
        return amount / Decimal(reverse.rate), None

    return None, f"Falta cotización activa para convertir {source}->{target} al {reference_date}."


@bp.before_request
def _authorize_reports():
    if g.get("user") is None:
        flash("Debes iniciar sesión para continuar.", "warning")
        return redirect(url_for("auth.login"))
    if not has_permission(g.user, "reports.view"):
        flash("No tienes permisos para acceder a Reportes.", "danger")
        return redirect(url_for("main.home"))


@bp.route("/")
@login_required
def project_monthly():
    selected_month = _safe_strip(request.args.get("month"))
    year, month = _parse_month(selected_month)
    start_date = date(year, month, 1)
    end_date = date(year, month, monthrange(year, month)[1])

    scope = allowed_project_ids(g.user)
    projects_stmt = select(Project).order_by(Project.name.asc())
    if scope is not None:
        if not scope:
            projects_stmt = projects_stmt.where(Project.id == -1)
        else:
            projects_stmt = projects_stmt.where(Project.id.in_(scope))
    projects = db.session.execute(projects_stmt.options(selectinload(Project.client))).scalars().all()
    projects_by_id = {item.id: item for item in projects}

    selected_project_id = None
    raw_project_id = _safe_strip(request.args.get("project_id"))
    if raw_project_id.isdigit():
        selected_project_id = int(raw_project_id)

    logs_stmt = (
        select(TaskWorklog, Task)
        .join(Task, Task.id == TaskWorklog.task_id)
        .join(Project, Project.id == Task.project_id)
        .where(
            TaskWorklog.is_active.is_(True),
            TaskWorklog.work_date >= start_date,
            TaskWorklog.work_date <= end_date,
        )
        .order_by(TaskWorklog.work_date.asc(), TaskWorklog.id.asc())
    )
    if scope is not None:
        if not scope:
            logs_stmt = logs_stmt.where(Task.id == -1)
        else:
            logs_stmt = logs_stmt.where(Task.project_id.in_(scope))
    if selected_project_id:
        logs_stmt = logs_stmt.where(Task.project_id == selected_project_id)

    logs = db.session.execute(logs_stmt).all()

    report_rows: dict[int, dict] = {}
    global_hours = Decimal("0")
    cost_by_currency: dict[str, Decimal] = {}
    global_valued_logs = 0
    global_logs = 0

    for log, task in logs:
        project = projects_by_id.get(task.project_id)
        if not project:
            project = db.session.execute(
                select(Project).where(Project.id == task.project_id).options(selectinload(Project.client))
            ).scalar_one_or_none()
            if not project:
                continue
            projects_by_id[project.id] = project

        row = report_rows.setdefault(
            project.id,
            {
                "project": project,
                "logs": 0,
                "hours": Decimal("0"),
                "cost": Decimal("0"),
                "valued_logs": 0,
                "warnings": 0,
            },
        )

        hours = Decimal(log.hours or 0)
        row["logs"] += 1
        row["hours"] += hours
        global_logs += 1
        global_hours += hours

        target_currency = _safe_strip(project.currency_code).upper()
        if not target_currency:
            row["warnings"] += 1
            continue

        cost_id = find_applicable_cost_id(log.resource_id, log.work_date)
        cost = db.session.get(ResourceCost, cost_id) if cost_id else None
        hourly_cost = _hourly_cost(cost)
        if hourly_cost is None:
            row["warnings"] += 1
            continue

        source_currency = _safe_strip(cost.currency if cost else "").upper()
        if not source_currency:
            row["warnings"] += 1
            continue

        raw_amount = hours * hourly_cost
        converted, error = _convert_currency_amount(
            raw_amount,
            source_currency,
            target_currency,
            owner_user_id=g.user.id if g.get("user") else None,
            reference_date=log.work_date,
        )
        if error or converted is None:
            row["warnings"] += 1
            continue

        row["cost"] += converted
        row["valued_logs"] += 1
        cost_by_currency[target_currency] = cost_by_currency.get(target_currency, Decimal("0")) + converted
        global_valued_logs += 1

    for project in projects:
        if selected_project_id and project.id != selected_project_id:
            continue
        report_rows.setdefault(
            project.id,
            {
                "project": project,
                "logs": 0,
                "hours": Decimal("0"),
                "cost": Decimal("0"),
                "valued_logs": 0,
                "warnings": 0,
            },
        )

    ordered_rows = sorted(
        report_rows.values(),
        key=lambda row: (
            row["hours"] == Decimal("0"),
            row["project"].name.lower(),
        ),
    )

    internal_hours = sum(
        (row["hours"] for row in ordered_rows if row["project"].project_code == INTERNAL_PROJECT_CODE or row["project"].name == INTERNAL_PROJECT_NAME),
        Decimal("0"),
    )

    return render_template(
        "reports/project_monthly.html",
        selected_month=f"{year:04d}-{month:02d}",
        start_date=start_date,
        end_date=end_date,
        projects=projects,
        selected_project_id=selected_project_id,
        rows=ordered_rows,
        total_projects=len(ordered_rows),
        total_logs=global_logs,
        total_hours=global_hours,
        cost_by_currency=sorted(cost_by_currency.items()),
        total_valued_logs=global_valued_logs,
        internal_hours=internal_hours,
    )
