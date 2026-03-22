from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class ProjectBaseline(TimestampMixin, db.Model):
    __tablename__ = "project_baselines"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    label = db.Column(db.String(180), nullable=True)
    snapshot_json = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    project = db.relationship("Project", backref=db.backref("baselines", lazy="selectin"))
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id], lazy="joined")
    approved_by_user = db.relationship("User", foreign_keys=[approved_by_user_id], lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("project_id", "version", name="uq_project_baselines_project_version"),
    )


class ProjectHealthSnapshot(TimestampMixin, db.Model):
    __tablename__ = "project_health_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    baseline_id = db.Column(db.Integer, db.ForeignKey("project_baselines.id"), nullable=True, index=True)
    snapshot_date = db.Column(db.Date, nullable=False, index=True)
    schedule_variance_days = db.Column(db.Integer, nullable=True)
    effort_variance_hours = db.Column(db.Numeric(10, 2), nullable=True)
    cost_variance_pct = db.Column(db.Numeric(8, 2), nullable=True)
    health_status = db.Column(db.String(20), nullable=False, default="green")
    notes = db.Column(db.Text, nullable=True)

    project = db.relationship("Project", backref=db.backref("health_snapshots", lazy="selectin"))
    baseline = db.relationship("ProjectBaseline", lazy="joined")


class TimesheetPeriod(TimestampMixin, db.Model):
    __tablename__ = "timesheet_periods"

    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    is_closed = db.Column(db.Boolean, nullable=False, default=False)
    closed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    closed_by_user = db.relationship("User", lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("start_date", "end_date", name="uq_timesheet_period_dates"),
    )


class TimesheetHeader(TimestampMixin, db.Model):
    __tablename__ = "timesheet_headers"

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    week_start = db.Column(db.Date, nullable=False, index=True)
    week_end = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    rejection_comment = db.Column(db.Text, nullable=True)
    period_id = db.Column(db.Integer, db.ForeignKey("timesheet_periods.id"), nullable=True, index=True)

    resource = db.relationship("Resource", lazy="joined")
    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")
    approved_by_user = db.relationship("User", foreign_keys=[approved_by_user_id], lazy="joined")
    period = db.relationship("TimesheetPeriod", lazy="joined")
    lines = db.relationship(
        "TimesheetLine",
        back_populates="header",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("resource_id", "week_start", name="uq_timesheet_headers_resource_week"),
    )


class TimesheetLine(TimestampMixin, db.Model):
    __tablename__ = "timesheet_lines"

    id = db.Column(db.Integer, primary_key=True)
    header_id = db.Column(db.Integer, db.ForeignKey("timesheet_headers.id"), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    worklog_id = db.Column(db.Integer, db.ForeignKey("task_worklogs.id"), nullable=True, index=True, unique=True)
    work_date = db.Column(db.Date, nullable=False, index=True)
    hours = db.Column(db.Numeric(8, 2), nullable=False)
    note = db.Column(db.Text, nullable=True)
    progress_percent_after = db.Column(db.Integer, nullable=True)

    header = db.relationship("TimesheetHeader", back_populates="lines")
    task = db.relationship("Task", lazy="joined")
    worklog = db.relationship("TaskWorklog", lazy="joined")
