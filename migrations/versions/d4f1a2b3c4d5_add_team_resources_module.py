"""add team resources module

Revision ID: d4f1a2b3c4d5
Revises: c9d8e7f6a5b4
Create Date: 2026-03-16 03:30:00.000000
"""

from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4f1a2b3c4d5"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


DEFAULT_TEAM_ROLES = [
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
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    # Recuperación segura de corridas parciales: si ya existe `resources`,
    # se asume que el bloque de creación de tablas de equipo fue ejecutado.
    if "resources" not in existing_tables:
        op.create_table(
            "resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("position", sa.String(length=120), nullable=True),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("resource_type", sa.String(length=20), nullable=False, server_default="internal"),
        sa.Column("vendor_name", sa.String(length=180), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("resource_type IN ('internal', 'external')", name="ck_resources_resource_type"),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_resources_email"), "resources", ["email"], unique=True)
        op.create_index(op.f("ix_resources_full_name"), "resources", ["full_name"], unique=False)

        op.create_table(
            "team_roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
        op.create_index(op.f("ix_team_roles_name"), "team_roles", ["name"], unique=True)

        op.create_table(
            "resource_role",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "role_id", name="uq_resource_role_resource_role"),
    )
        op.create_index(op.f("ix_resource_role_resource_id"), "resource_role", ["resource_id"], unique=False)
        op.create_index(op.f("ix_resource_role_role_id"), "resource_role", ["role_id"], unique=False)

        op.create_table(
            "resource_availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("availability_type", sa.String(length=20), nullable=False, server_default="full_time"),
        sa.Column("weekly_hours", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("daily_hours", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("availability_type IN ('full_time', 'part_time', 'custom')", name="ck_resource_availability_type"),
        sa.CheckConstraint("weekly_hours > 0", name="ck_resource_availability_weekly_hours_positive"),
        sa.CheckConstraint("daily_hours IS NULL OR daily_hours > 0", name="ck_resource_availability_daily_hours_positive"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_resource_availability_date_range"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_resource_availability_resource_id"), "resource_availability", ["resource_id"], unique=False)
        op.create_index(op.f("ix_resource_availability_valid_from"), "resource_availability", ["valid_from"], unique=False)
        op.create_index(op.f("ix_resource_availability_valid_to"), "resource_availability", ["valid_to"], unique=False)

        op.create_table(
            "resource_cost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("hourly_cost", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("monthly_cost", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("hourly_cost > 0", name="ck_resource_cost_hourly_positive"),
        sa.CheckConstraint("monthly_cost IS NULL OR monthly_cost >= 0", name="ck_resource_cost_monthly_non_negative"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="ck_resource_cost_date_range"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_resource_cost_resource_id"), "resource_cost", ["resource_id"], unique=False)
        op.create_index(op.f("ix_resource_cost_valid_from"), "resource_cost", ["valid_from"], unique=False)
        op.create_index(op.f("ix_resource_cost_valid_to"), "resource_cost", ["valid_to"], unique=False)

        op.create_table(
            "client_resource",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allocation_percent", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("planned_hours", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("allocation_percent IS NULL OR (allocation_percent >= 0 AND allocation_percent <= 100)", name="ck_client_resource_allocation"),
        sa.CheckConstraint("planned_hours IS NULL OR planned_hours >= 0", name="ck_client_resource_planned_hours"),
        sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_client_resource_date_range"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_client_resource_client_id"), "client_resource", ["client_id"], unique=False)
        op.create_index(op.f("ix_client_resource_resource_id"), "client_resource", ["resource_id"], unique=False)
        op.create_index(op.f("ix_client_resource_role_id"), "client_resource", ["role_id"], unique=False)

        op.create_table(
            "project_resource",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allocation_percent", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("planned_hours", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("allocation_percent IS NULL OR (allocation_percent >= 0 AND allocation_percent <= 100)", name="ck_project_resource_allocation"),
        sa.CheckConstraint("planned_hours IS NULL OR planned_hours >= 0", name="ck_project_resource_planned_hours"),
        sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_project_resource_date_range"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_project_resource_project_id"), "project_resource", ["project_id"], unique=False)
        op.create_index(op.f("ix_project_resource_resource_id"), "project_resource", ["resource_id"], unique=False)
        op.create_index(op.f("ix_project_resource_role_id"), "project_resource", ["role_id"], unique=False)

        op.create_table(
            "task_resource",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allocation_percent", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("planned_hours", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("allocation_percent IS NULL OR (allocation_percent >= 0 AND allocation_percent <= 100)", name="ck_task_resource_allocation"),
        sa.CheckConstraint("planned_hours IS NULL OR planned_hours >= 0", name="ck_task_resource_planned_hours"),
        sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="ck_task_resource_date_range"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"]),
        sa.ForeignKeyConstraint(["role_id"], ["team_roles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
        op.create_index(op.f("ix_task_resource_task_id"), "task_resource", ["task_id"], unique=False)
        op.create_index(op.f("ix_task_resource_resource_id"), "task_resource", ["resource_id"], unique=False)
        op.create_index(op.f("ix_task_resource_role_id"), "task_resource", ["role_id"], unique=False)

    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sales_executive_resource_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("account_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("delivery_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_clients_sales_executive_resource_id"), ["sales_executive_resource_id"], unique=False)
        batch_op.create_index(op.f("ix_clients_account_manager_resource_id"), ["account_manager_resource_id"], unique=False)
        batch_op.create_index(op.f("ix_clients_delivery_manager_resource_id"), ["delivery_manager_resource_id"], unique=False)
        batch_op.create_foreign_key("fk_clients_sales_exec_resource", "resources", ["sales_executive_resource_id"], ["id"])
        batch_op.create_foreign_key("fk_clients_account_manager_resource", "resources", ["account_manager_resource_id"], ["id"])
        batch_op.create_foreign_key("fk_clients_delivery_manager_resource", "resources", ["delivery_manager_resource_id"], ["id"])

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("commercial_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("functional_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("technical_manager_resource_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_projects_project_manager_resource_id"), ["project_manager_resource_id"], unique=False)
        batch_op.create_index(op.f("ix_projects_commercial_manager_resource_id"), ["commercial_manager_resource_id"], unique=False)
        batch_op.create_index(op.f("ix_projects_functional_manager_resource_id"), ["functional_manager_resource_id"], unique=False)
        batch_op.create_index(op.f("ix_projects_technical_manager_resource_id"), ["technical_manager_resource_id"], unique=False)
        batch_op.create_foreign_key("fk_projects_project_manager_resource", "resources", ["project_manager_resource_id"], ["id"])
        batch_op.create_foreign_key("fk_projects_commercial_manager_resource", "resources", ["commercial_manager_resource_id"], ["id"])
        batch_op.create_foreign_key("fk_projects_functional_manager_resource", "resources", ["functional_manager_resource_id"], ["id"])
        batch_op.create_foreign_key("fk_projects_technical_manager_resource", "resources", ["technical_manager_resource_id"], ["id"])

    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.add_column(sa.Column("responsible_resource_id", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_tasks_responsible_resource_id"), ["responsible_resource_id"], unique=False)
        batch_op.create_foreign_key("fk_tasks_responsible_resource", "resources", ["responsible_resource_id"], ["id"])

    now = datetime.utcnow()

    team_roles = sa.table(
        "team_roles",
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    for role_name in DEFAULT_TEAM_ROLES:
        exists = bind.execute(sa.select(team_roles.c.name).where(sa.func.lower(team_roles.c.name) == role_name.lower())).first()
        if not exists:
            bind.execute(
                team_roles.insert().values(
                    name=role_name,
                    description=None,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )

    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("label", sa.String),
        sa.column("module", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("name", sa.String))

    permission_defs = [
        ("team.view", "Ver equipo", "team"),
        ("team.edit", "Editar equipo", "team"),
    ]

    admin_role_id = bind.execute(sa.select(roles.c.id).where(sa.func.lower(roles.c.name) == "administrador")).scalar()

    for key, label, module in permission_defs:
        permission_id = bind.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if not permission_id:
            bind.execute(
                permissions.insert().values(
                    key=key,
                    label=label,
                    module=module,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            permission_id = bind.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()

        if admin_role_id:
            link_exists = bind.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == admin_role_id,
                    role_permissions.c.permission_id == permission_id,
                )
            ).first()
            if not link_exists:
                bind.execute(
                    role_permissions.insert().values(
                        role_id=admin_role_id,
                        permission_id=permission_id,
                        created_at=now,
                        updated_at=now,
                    )
                )


def downgrade():
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_constraint("fk_tasks_responsible_resource", type_="foreignkey")
        batch_op.drop_index(op.f("ix_tasks_responsible_resource_id"))
        batch_op.drop_column("responsible_resource_id")

    with op.batch_alter_table("projects", schema=None) as batch_op:
        batch_op.drop_constraint("fk_projects_technical_manager_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_projects_functional_manager_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_projects_commercial_manager_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_projects_project_manager_resource", type_="foreignkey")
        batch_op.drop_index(op.f("ix_projects_technical_manager_resource_id"))
        batch_op.drop_index(op.f("ix_projects_functional_manager_resource_id"))
        batch_op.drop_index(op.f("ix_projects_commercial_manager_resource_id"))
        batch_op.drop_index(op.f("ix_projects_project_manager_resource_id"))
        batch_op.drop_column("technical_manager_resource_id")
        batch_op.drop_column("functional_manager_resource_id")
        batch_op.drop_column("commercial_manager_resource_id")
        batch_op.drop_column("project_manager_resource_id")

    with op.batch_alter_table("clients", schema=None) as batch_op:
        batch_op.drop_constraint("fk_clients_delivery_manager_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_clients_account_manager_resource", type_="foreignkey")
        batch_op.drop_constraint("fk_clients_sales_exec_resource", type_="foreignkey")
        batch_op.drop_index(op.f("ix_clients_delivery_manager_resource_id"))
        batch_op.drop_index(op.f("ix_clients_account_manager_resource_id"))
        batch_op.drop_index(op.f("ix_clients_sales_executive_resource_id"))
        batch_op.drop_column("delivery_manager_resource_id")
        batch_op.drop_column("account_manager_resource_id")
        batch_op.drop_column("sales_executive_resource_id")

    op.drop_index(op.f("ix_task_resource_role_id"), table_name="task_resource")
    op.drop_index(op.f("ix_task_resource_resource_id"), table_name="task_resource")
    op.drop_index(op.f("ix_task_resource_task_id"), table_name="task_resource")
    op.drop_table("task_resource")

    op.drop_index(op.f("ix_project_resource_role_id"), table_name="project_resource")
    op.drop_index(op.f("ix_project_resource_resource_id"), table_name="project_resource")
    op.drop_index(op.f("ix_project_resource_project_id"), table_name="project_resource")
    op.drop_table("project_resource")

    op.drop_index(op.f("ix_client_resource_role_id"), table_name="client_resource")
    op.drop_index(op.f("ix_client_resource_resource_id"), table_name="client_resource")
    op.drop_index(op.f("ix_client_resource_client_id"), table_name="client_resource")
    op.drop_table("client_resource")

    op.drop_index(op.f("ix_resource_cost_valid_to"), table_name="resource_cost")
    op.drop_index(op.f("ix_resource_cost_valid_from"), table_name="resource_cost")
    op.drop_index(op.f("ix_resource_cost_resource_id"), table_name="resource_cost")
    op.drop_table("resource_cost")

    op.drop_index(op.f("ix_resource_availability_valid_to"), table_name="resource_availability")
    op.drop_index(op.f("ix_resource_availability_valid_from"), table_name="resource_availability")
    op.drop_index(op.f("ix_resource_availability_resource_id"), table_name="resource_availability")
    op.drop_table("resource_availability")

    op.drop_index(op.f("ix_resource_role_role_id"), table_name="resource_role")
    op.drop_index(op.f("ix_resource_role_resource_id"), table_name="resource_role")
    op.drop_table("resource_role")

    op.drop_index(op.f("ix_team_roles_name"), table_name="team_roles")
    op.drop_table("team_roles")

    op.drop_index(op.f("ix_resources_full_name"), table_name="resources")
    op.drop_index(op.f("ix_resources_email"), table_name="resources")
    op.drop_table("resources")
