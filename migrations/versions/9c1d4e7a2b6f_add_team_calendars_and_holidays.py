"""add team calendars and holidays

Revision ID: 9c1d4e7a2b6f
Revises: 8a4c2e1f9b7d
Create Date: 2026-03-19 00:35:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c1d4e7a2b6f"
down_revision = "8a4c2e1f9b7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("resources", schema=None) as batch_op:
        batch_op.add_column(sa.Column("calendar_name", sa.String(length=120), nullable=True))

    op.create_table(
        "team_calendar_holiday_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("calendar_name", sa.String(length=120), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "calendar_name",
            "holiday_date",
            name="uq_team_calendar_holiday_owner_calendar_date",
        ),
    )
    op.create_index(op.f("ix_team_calendar_holiday_configs_owner_user_id"), "team_calendar_holiday_configs", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_team_calendar_holiday_configs_calendar_name"), "team_calendar_holiday_configs", ["calendar_name"], unique=False)
    op.create_index(op.f("ix_team_calendar_holiday_configs_holiday_date"), "team_calendar_holiday_configs", ["holiday_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_team_calendar_holiday_configs_holiday_date"), table_name="team_calendar_holiday_configs")
    op.drop_index(op.f("ix_team_calendar_holiday_configs_calendar_name"), table_name="team_calendar_holiday_configs")
    op.drop_index(op.f("ix_team_calendar_holiday_configs_owner_user_id"), table_name="team_calendar_holiday_configs")
    op.drop_table("team_calendar_holiday_configs")

    with op.batch_alter_table("resources", schema=None) as batch_op:
        batch_op.drop_column("calendar_name")
