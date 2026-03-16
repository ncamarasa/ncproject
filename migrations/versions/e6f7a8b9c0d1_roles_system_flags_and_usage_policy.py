"""roles system flags and usage policy

Revision ID: e6f7a8b9c0d1
Revises: d4f1a2b3c4d5
Create Date: 2026-03-16 05:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6f7a8b9c0d1"
down_revision = "d4f1a2b3c4d5"
branch_labels = None
depends_on = None


DEFAULT_TEAM_SYSTEM_ROLES = [
    "PM",
    "Ejecutivo de cuenta",
    "Gerente de cuenta",
    "Responsable técnico",
    "Responsable funcional",
    "Consultor",
    "Analista",
    "Soporte",
]


def upgrade():
    with op.batch_alter_table("roles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_editable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("is_deletable", sa.Boolean(), nullable=False, server_default=sa.true()))

    with op.batch_alter_table("team_roles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("is_editable", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("is_deletable", sa.Boolean(), nullable=False, server_default=sa.true()))

    bind = op.get_bind()
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("is_editable", sa.Boolean),
        sa.column("is_deletable", sa.Boolean),
    )
    team_roles = sa.table(
        "team_roles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("is_editable", sa.Boolean),
        sa.column("is_deletable", sa.Boolean),
    )

    bind.execute(
        roles.update()
        .where(sa.func.lower(roles.c.name) == "administrador")
        .values(
            is_system=True,
            is_editable=False,
            is_deletable=False,
        )
    )

    for name in DEFAULT_TEAM_SYSTEM_ROLES:
        bind.execute(
            team_roles.update()
            .where(sa.func.lower(team_roles.c.name) == name.lower())
            .values(
                is_system=True,
                is_editable=False,
                is_deletable=False,
            )
        )


def downgrade():
    with op.batch_alter_table("team_roles", schema=None) as batch_op:
        batch_op.drop_column("is_deletable")
        batch_op.drop_column("is_editable")
        batch_op.drop_column("is_system")

    with op.batch_alter_table("roles", schema=None) as batch_op:
        batch_op.drop_column("is_deletable")
        batch_op.drop_column("is_editable")
        batch_op.drop_column("is_system")
