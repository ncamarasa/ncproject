"""add control pmo baselines health timesheets

Revision ID: c1d2e3f4a5b6
Revises: a4b5c6d7e8f9, a9c8b7d6e5f4
Create Date: 2026-03-21 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4a5b6"
down_revision = ("a4b5c6d7e8f9", "a9c8b7d6e5f4")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_baselines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="uq_project_baselines_project_version"),
    )
    op.create_index("ix_project_baselines_project_id", "project_baselines", ["project_id"], unique=False)
    op.create_index("ix_project_baselines_created_by_user_id", "project_baselines", ["created_by_user_id"], unique=False)
    op.create_index("ix_project_baselines_approved_by_user_id", "project_baselines", ["approved_by_user_id"], unique=False)

    op.create_table(
        "project_health_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("baseline_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("schedule_variance_days", sa.Integer(), nullable=True),
        sa.Column("effort_variance_hours", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("cost_variance_pct", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("health_status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["baseline_id"], ["project_baselines.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_health_snapshots_project_id", "project_health_snapshots", ["project_id"], unique=False)
    op.create_index("ix_project_health_snapshots_baseline_id", "project_health_snapshots", ["baseline_id"], unique=False)
    op.create_index("ix_project_health_snapshots_snapshot_date", "project_health_snapshots", ["snapshot_date"], unique=False)

    op.create_table(
        "timesheet_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("closed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("start_date", "end_date", name="uq_timesheet_period_dates"),
    )
    op.create_index("ix_timesheet_periods_start_date", "timesheet_periods", ["start_date"], unique=False)
    op.create_index("ix_timesheet_periods_end_date", "timesheet_periods", ["end_date"], unique=False)
    op.create_index("ix_timesheet_periods_closed_by_user_id", "timesheet_periods", ["closed_by_user_id"], unique=False)

    op.create_table(
        "timesheet_headers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_user_id", sa.Integer(), nullable=True),
        sa.Column("rejection_comment", sa.Text(), nullable=True),
        sa.Column("period_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["period_id"], ["timesheet_periods.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "week_start", name="uq_timesheet_headers_resource_week"),
    )
    op.create_index("ix_timesheet_headers_resource_id", "timesheet_headers", ["resource_id"], unique=False)
    op.create_index("ix_timesheet_headers_user_id", "timesheet_headers", ["user_id"], unique=False)
    op.create_index("ix_timesheet_headers_week_start", "timesheet_headers", ["week_start"], unique=False)
    op.create_index("ix_timesheet_headers_status", "timesheet_headers", ["status"], unique=False)
    op.create_index("ix_timesheet_headers_approved_by_user_id", "timesheet_headers", ["approved_by_user_id"], unique=False)
    op.create_index("ix_timesheet_headers_period_id", "timesheet_headers", ["period_id"], unique=False)

    with op.batch_alter_table("task_worklogs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("timesheet_header_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_task_worklogs_timesheet_header_id", "timesheet_headers", ["timesheet_header_id"], ["id"])
        batch_op.create_index("ix_task_worklogs_timesheet_header_id", ["timesheet_header_id"], unique=False)

    op.create_table(
        "timesheet_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("header_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("worklog_id", sa.Integer(), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("progress_percent_after", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["header_id"], ["timesheet_headers.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["worklog_id"], ["task_worklogs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("worklog_id"),
    )
    op.create_index("ix_timesheet_lines_header_id", "timesheet_lines", ["header_id"], unique=False)
    op.create_index("ix_timesheet_lines_task_id", "timesheet_lines", ["task_id"], unique=False)
    op.create_index("ix_timesheet_lines_worklog_id", "timesheet_lines", ["worklog_id"], unique=False)
    op.create_index("ix_timesheet_lines_work_date", "timesheet_lines", ["work_date"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_timesheet_lines_work_date", table_name="timesheet_lines")
    op.drop_index("ix_timesheet_lines_worklog_id", table_name="timesheet_lines")
    op.drop_index("ix_timesheet_lines_task_id", table_name="timesheet_lines")
    op.drop_index("ix_timesheet_lines_header_id", table_name="timesheet_lines")
    op.drop_table("timesheet_lines")

    with op.batch_alter_table("task_worklogs", schema=None) as batch_op:
        batch_op.drop_index("ix_task_worklogs_timesheet_header_id")
        batch_op.drop_constraint("fk_task_worklogs_timesheet_header_id", type_="foreignkey")
        batch_op.drop_column("timesheet_header_id")

    op.drop_index("ix_timesheet_headers_period_id", table_name="timesheet_headers")
    op.drop_index("ix_timesheet_headers_approved_by_user_id", table_name="timesheet_headers")
    op.drop_index("ix_timesheet_headers_status", table_name="timesheet_headers")
    op.drop_index("ix_timesheet_headers_week_start", table_name="timesheet_headers")
    op.drop_index("ix_timesheet_headers_user_id", table_name="timesheet_headers")
    op.drop_index("ix_timesheet_headers_resource_id", table_name="timesheet_headers")
    op.drop_table("timesheet_headers")

    op.drop_index("ix_timesheet_periods_closed_by_user_id", table_name="timesheet_periods")
    op.drop_index("ix_timesheet_periods_end_date", table_name="timesheet_periods")
    op.drop_index("ix_timesheet_periods_start_date", table_name="timesheet_periods")
    op.drop_table("timesheet_periods")

    op.drop_index("ix_project_health_snapshots_snapshot_date", table_name="project_health_snapshots")
    op.drop_index("ix_project_health_snapshots_baseline_id", table_name="project_health_snapshots")
    op.drop_index("ix_project_health_snapshots_project_id", table_name="project_health_snapshots")
    op.drop_table("project_health_snapshots")

    op.drop_index("ix_project_baselines_approved_by_user_id", table_name="project_baselines")
    op.drop_index("ix_project_baselines_created_by_user_id", table_name="project_baselines")
    op.drop_index("ix_project_baselines_project_id", table_name="project_baselines")
    op.drop_table("project_baselines")
