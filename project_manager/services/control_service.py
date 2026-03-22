from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, select

from project_manager.extensions import db
from project_manager.models import (
    Project,
    ProjectBaseline,
    ProjectHealthSnapshot,
    Task,
    TimesheetHeader,
    TimesheetPeriod,
)
from project_manager.services.team_business_rules import calculate_resource_net_availability


def week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end


def period_for_date(day: date) -> TimesheetPeriod | None:
    return db.session.execute(
        select(TimesheetPeriod).where(
            TimesheetPeriod.start_date <= day,
            TimesheetPeriod.end_date >= day,
        )
    ).scalar_one_or_none()


def is_day_in_closed_period(day: date) -> bool:
    period = period_for_date(day)
    return bool(period and period.is_closed)


def ensure_timesheet_header(resource_id: int, user_id: int | None, day: date) -> TimesheetHeader:
    week_start, week_end = week_bounds(day)
    header = db.session.execute(
        select(TimesheetHeader).where(
            TimesheetHeader.resource_id == resource_id,
            TimesheetHeader.week_start == week_start,
        )
    ).scalar_one_or_none()
    period = period_for_date(day)
    if header:
        if not header.period_id and period:
            header.period_id = period.id
        return header

    header = TimesheetHeader(
        resource_id=resource_id,
        user_id=user_id,
        week_start=week_start,
        week_end=week_end,
        status="draft",
        period_id=period.id if period else None,
    )
    db.session.add(header)
    db.session.flush()
    return header


def _project_snapshot_payload(project: Project) -> dict:
    tasks = db.session.execute(
        select(Task).where(Task.project_id == project.id, Task.is_active.is_(True)).order_by(Task.project_task_id.asc())
    ).scalars().all()
    task_rows: list[dict] = []
    total_hours = Decimal("0.00")
    for t in tasks:
        est = Decimal(t.estimated_hours or 0)
        total_hours += est
        task_rows.append(
            {
                "id": t.id,
                "project_task_id": t.project_task_id,
                "title": t.title,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "estimated_hours": float(est),
                "progress_percent": int(t.progress_percent or 0),
            }
        )
    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "estimated_start_date": project.estimated_start_date.isoformat() if project.estimated_start_date else None,
            "estimated_end_date": project.estimated_end_date.isoformat() if project.estimated_end_date else None,
            "estimated_cost": float(project.estimated_cost or 0),
            "estimated_hours": float(project.estimated_hours or 0),
            "task_estimated_hours_total": float(total_hours),
        },
        "tasks": task_rows,
    }


def create_project_baseline(project: Project, *, created_by_user_id: int | None, label: str | None = None, notes: str | None = None) -> ProjectBaseline:
    next_version = (
        db.session.execute(
            select(ProjectBaseline.version)
            .where(ProjectBaseline.project_id == project.id)
            .order_by(ProjectBaseline.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    ) + 1
    payload = _project_snapshot_payload(project)
    baseline = ProjectBaseline(
        project_id=project.id,
        version=next_version,
        label=(label or "").strip() or f"Baseline v{next_version}",
        snapshot_json=json.dumps(payload, ensure_ascii=True),
        notes=(notes or "").strip() or None,
        created_by_user_id=created_by_user_id,
        approved_by_user_id=created_by_user_id,
        is_active=True,
    )
    db.session.add(baseline)
    db.session.flush()
    return baseline


def _project_current_schedule_end(project: Project) -> date | None:
    if project.estimated_end_date:
        return project.estimated_end_date
    max_due = db.session.execute(
        select(Task.due_date)
        .where(Task.project_id == project.id, Task.is_active.is_(True), Task.due_date.is_not(None))
        .order_by(Task.due_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    return max_due


def calculate_project_health(project: Project, baseline: ProjectBaseline | None) -> dict:
    if not baseline:
        return {
            "schedule_variance_days": None,
            "effort_variance_hours": None,
            "cost_variance_pct": None,
            "health_status": "gray",
            "notes": "Sin baseline aprobada.",
        }
    payload = json.loads(baseline.snapshot_json or "{}")
    base_project = payload.get("project", {})
    base_end = base_project.get("estimated_end_date")
    base_end_date = date.fromisoformat(base_end) if base_end else None
    current_end = _project_current_schedule_end(project)
    schedule_variance = None
    if base_end_date and current_end:
        schedule_variance = (current_end - base_end_date).days

    base_hours = Decimal(str(base_project.get("task_estimated_hours_total", 0) or 0))
    current_hours = (
        db.session.execute(
            select(db.func.coalesce(db.func.sum(Task.estimated_hours), 0))
            .where(Task.project_id == project.id, Task.is_active.is_(True))
        ).scalar_one()
        or 0
    )
    effort_variance = Decimal(current_hours) - base_hours

    base_cost = Decimal(str(base_project.get("estimated_cost", 0) or 0))
    current_cost = Decimal(project.estimated_cost or 0)
    cost_variance_pct = None
    if base_cost > 0:
        cost_variance_pct = ((current_cost - base_cost) / base_cost) * Decimal("100")

    status = "green"
    if schedule_variance is not None and schedule_variance > 10:
        status = "red"
    elif schedule_variance is not None and schedule_variance > 3:
        status = "amber"
    if abs(effort_variance) > Decimal("120"):
        status = "red"
    elif status == "green" and abs(effort_variance) > Decimal("40"):
        status = "amber"
    if cost_variance_pct is not None and cost_variance_pct > Decimal("20"):
        status = "red"
    elif status == "green" and cost_variance_pct is not None and cost_variance_pct > Decimal("8"):
        status = "amber"

    return {
        "schedule_variance_days": schedule_variance,
        "effort_variance_hours": effort_variance,
        "cost_variance_pct": cost_variance_pct,
        "health_status": status,
        "notes": None,
    }


def snapshot_project_health(project: Project, baseline: ProjectBaseline | None) -> ProjectHealthSnapshot:
    data = calculate_project_health(project, baseline)
    snap = ProjectHealthSnapshot(
        project_id=project.id,
        baseline_id=baseline.id if baseline else None,
        snapshot_date=date.today(),
        schedule_variance_days=data["schedule_variance_days"],
        effort_variance_hours=data["effort_variance_hours"],
        cost_variance_pct=data["cost_variance_pct"],
        health_status=data["health_status"],
        notes=data["notes"],
    )
    db.session.add(snap)
    db.session.flush()
    return snap


def can_edit_timesheet_header(header: TimesheetHeader) -> bool:
    if header.status not in {"draft", "rejected"}:
        return False
    if header.period and header.period.is_closed:
        return False
    return True


def submit_timesheet(header: TimesheetHeader) -> None:
    if header.status == "approved":
        return
    if header.period and header.period.is_closed:
        return
    header.status = "submitted"
    header.submitted_at = datetime.utcnow()
    header.rejection_comment = None


def approve_timesheet(header: TimesheetHeader, *, approver_user_id: int) -> None:
    header.status = "approved"
    header.approved_at = datetime.utcnow()
    header.approved_by_user_id = approver_user_id
    header.rejection_comment = None


def reject_timesheet(header: TimesheetHeader, *, approver_user_id: int, comment: str) -> None:
    header.status = "rejected"
    header.approved_at = datetime.utcnow()
    header.approved_by_user_id = approver_user_id
    header.rejection_comment = (comment or "").strip() or "Rechazado sin detalle."


def timesheet_capacity_summary(header: TimesheetHeader, *, owner_user_id: int | None = None) -> dict:
    payload = calculate_resource_net_availability(
        header.resource_id,
        header.week_start,
        header.week_end,
        owner_user_id=owner_user_id,
    )
    capacity_hours = max(
        Decimal("0.00"),
        Decimal(str(payload.get("totals", {}).get("base_hours", 0) or 0))
        - Decimal(str(payload.get("totals", {}).get("exception_hours", 0) or 0)),
    )
    total_hours = sum((Decimal(line.hours or 0) for line in (header.lines or [])), Decimal("0.00"))
    overage_hours = max(Decimal("0.00"), total_hours - capacity_hours)
    remaining_hours = max(Decimal("0.00"), capacity_hours - total_hours)
    return {
        "capacity_hours": capacity_hours,
        "total_hours": total_hours,
        "overage_hours": overage_hours,
        "remaining_hours": remaining_hours,
    }
