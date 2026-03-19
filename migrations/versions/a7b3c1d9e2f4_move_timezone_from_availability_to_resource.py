"""move timezone from availability to resource

Revision ID: a7b3c1d9e2f4
Revises: 9c1d4e7a2b6f
Create Date: 2026-03-19 00:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a7b3c1d9e2f4"
down_revision = "9c1d4e7a2b6f"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {col["name"] for col in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    if "timezone" not in _column_names(bind, "resources"):
        with op.batch_alter_table("resources", schema=None) as batch_op:
            batch_op.add_column(sa.Column("timezone", sa.String(length=60), nullable=True))

    if "timezone" in _column_names(bind, "resource_availability"):
        rows = bind.execute(
            sa.text(
                """
                SELECT resource_id, timezone
                FROM resource_availability
                WHERE timezone IS NOT NULL
                  AND TRIM(timezone) <> ''
                ORDER BY resource_id ASC, valid_from DESC, id DESC
                """
            )
        ).fetchall()
        seen_resources: set[int] = set()
        for row in rows:
            resource_id = int(row.resource_id)
            if resource_id in seen_resources:
                continue
            seen_resources.add(resource_id)
            bind.execute(
                sa.text(
                    """
                    UPDATE resources
                    SET timezone = :timezone
                    WHERE id = :resource_id
                      AND (timezone IS NULL OR TRIM(timezone) = '')
                    """
                ),
                {"resource_id": resource_id, "timezone": row.timezone},
            )

        with op.batch_alter_table("resource_availability", schema=None) as batch_op:
            batch_op.drop_column("timezone")


def downgrade() -> None:
    bind = op.get_bind()

    if "timezone" not in _column_names(bind, "resource_availability"):
        with op.batch_alter_table("resource_availability", schema=None) as batch_op:
            batch_op.add_column(sa.Column("timezone", sa.String(length=60), nullable=True))

    if "timezone" in _column_names(bind, "resources"):
        bind.execute(
            sa.text(
                """
                UPDATE resource_availability
                SET timezone = (
                    SELECT resources.timezone
                    FROM resources
                    WHERE resources.id = resource_availability.resource_id
                )
                WHERE timezone IS NULL
                """
            )
        )

        with op.batch_alter_table("resources", schema=None) as batch_op:
            batch_op.drop_column("timezone")
