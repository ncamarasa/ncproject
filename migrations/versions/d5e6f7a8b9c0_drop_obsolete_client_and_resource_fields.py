"""drop obsolete client and resource fields

Revision ID: d5e6f7a8b9c0
Revises: c4d7e8f9a1b2
Create Date: 2026-03-19 22:05:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d7e8f9a1b2"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    client_columns = _column_names(bind, "clients")
    client_indexes = _index_names(bind, "clients")

    if "ix_clients_segment" in client_indexes:
        op.drop_index("ix_clients_segment", table_name="clients")

    drop_client_columns = [
        "segment",
        "timezone",
        "service_type",
        "billing_mode",
        "default_rate",
        "contracted_hours",
        "approval_flow",
    ]
    with op.batch_alter_table("clients") as batch_op:
        for column_name in drop_client_columns:
            if column_name in client_columns:
                batch_op.drop_column(column_name)

    resource_columns = _column_names(bind, "resources")
    with op.batch_alter_table("resources") as batch_op:
        if "timezone" in resource_columns:
            batch_op.drop_column("timezone")


def downgrade() -> None:
    bind = op.get_bind()
    client_columns = _column_names(bind, "clients")
    with op.batch_alter_table("clients") as batch_op:
        if "segment" not in client_columns:
            batch_op.add_column(sa.Column("segment", sa.String(length=80), nullable=True))
        if "timezone" not in client_columns:
            batch_op.add_column(sa.Column("timezone", sa.String(length=60), nullable=True))
        if "service_type" not in client_columns:
            batch_op.add_column(sa.Column("service_type", sa.String(length=80), nullable=True))
        if "billing_mode" not in client_columns:
            batch_op.add_column(sa.Column("billing_mode", sa.String(length=80), nullable=True))
        if "default_rate" not in client_columns:
            batch_op.add_column(sa.Column("default_rate", sa.Numeric(10, 2), nullable=True))
        if "contracted_hours" not in client_columns:
            batch_op.add_column(sa.Column("contracted_hours", sa.Numeric(10, 2), nullable=True))
        if "approval_flow" not in client_columns:
            batch_op.add_column(sa.Column("approval_flow", sa.Text(), nullable=True))

    client_indexes = _index_names(bind, "clients")
    if "ix_clients_segment" not in client_indexes:
        op.create_index("ix_clients_segment", "clients", ["segment"], unique=False)

    resource_columns = _column_names(bind, "resources")
    with op.batch_alter_table("resources") as batch_op:
        if "timezone" not in resource_columns:
            batch_op.add_column(sa.Column("timezone", sa.String(length=60), nullable=True))

