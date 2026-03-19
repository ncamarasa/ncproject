from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class Resource(TimestampMixin, db.Model):
    __tablename__ = "resources"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    full_name = db.Column(db.String(255), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True, unique=True, index=True)
    phone = db.Column(db.String(40), nullable=True)
    position = db.Column(db.String(120), nullable=True)
    area = db.Column(db.String(120), nullable=True)
    resource_type = db.Column(db.String(20), nullable=False, default="internal")
    calendar_name = db.Column(db.String(120), nullable=True)
    timezone = db.Column(db.String(60), nullable=True)
    vendor_name = db.Column(db.String(180), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    role_links = db.relationship(
        "ResourceRole",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    availabilities = db.relationship(
        "ResourceAvailability",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    availability_exceptions = db.relationship(
        "ResourceAvailabilityException",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    costs = db.relationship(
        "ResourceCost",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    project_assignments = db.relationship(
        "ProjectResource",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    task_assignments = db.relationship(
        "TaskResource",
        back_populates="resource",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TeamRole(TimestampMixin, db.Model):
    __tablename__ = "team_roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True, index=True)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    is_editable = db.Column(db.Boolean, nullable=False, default=True)
    is_deletable = db.Column(db.Boolean, nullable=False, default=True)

    resource_links = db.relationship(
        "ResourceRole",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sale_prices = db.relationship(
        "RoleSalePrice",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ResourceRole(TimestampMixin, db.Model):
    __tablename__ = "resource_role"

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("team_roles.id"), nullable=False, index=True)

    resource = db.relationship("Resource", back_populates="role_links")
    role = db.relationship("TeamRole", back_populates="resource_links")

    __table_args__ = (
        db.UniqueConstraint("resource_id", "role_id", name="uq_resource_role_resource_role"),
    )


class ResourceAvailability(TimestampMixin, db.Model):
    __tablename__ = "resource_availability"

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    availability_type = db.Column(db.String(20), nullable=False, default="full_time")
    weekly_hours = db.Column(db.Numeric(8, 2), nullable=False)
    daily_hours = db.Column(db.Numeric(8, 2), nullable=True)
    working_days = db.Column(db.String(40), nullable=False, default="mon,tue,wed,thu,fri")
    valid_from = db.Column(db.Date, nullable=False, index=True)
    valid_to = db.Column(db.Date, nullable=True, index=True)
    observations = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    resource = db.relationship("Resource", back_populates="availabilities")


class ResourceAvailabilityException(TimestampMixin, db.Model):
    __tablename__ = "resource_availability_exception"

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    exception_type = db.Column(db.String(30), nullable=False, default="time_off")
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=True, index=True)
    hours_lost = db.Column(db.Numeric(8, 2), nullable=True)
    observations = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    resource = db.relationship("Resource", back_populates="availability_exceptions")


class ResourceCost(TimestampMixin, db.Model):
    __tablename__ = "resource_cost"

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    valid_from = db.Column(db.Date, nullable=False, index=True)
    valid_to = db.Column(db.Date, nullable=True, index=True)
    hourly_cost = db.Column(db.Numeric(12, 2), nullable=True)
    monthly_cost = db.Column(db.Numeric(14, 2), nullable=True)
    currency = db.Column(db.String(10), nullable=False)
    observations = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    resource = db.relationship("Resource", back_populates="costs")


class RoleSalePrice(TimestampMixin, db.Model):
    __tablename__ = "role_sale_price"

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("team_roles.id"), nullable=False, index=True)
    valid_from = db.Column(db.Date, nullable=False, index=True)
    valid_to = db.Column(db.Date, nullable=True, index=True)
    hourly_price = db.Column(db.Numeric(12, 2), nullable=True)
    monthly_price = db.Column(db.Numeric(14, 2), nullable=True)
    currency = db.Column(db.String(10), nullable=False)
    observations = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    role = db.relationship("TeamRole", back_populates="sale_prices")


class ProjectResource(TimestampMixin, db.Model):
    __tablename__ = "project_resource"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("team_roles.id"), nullable=True, index=True)
    resource_cost_id = db.Column(db.Integer, db.ForeignKey("resource_cost.id"), nullable=True, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    allocation_percent = db.Column(db.Numeric(6, 2), nullable=True)
    planned_hours = db.Column(db.Numeric(10, 2), nullable=True)
    planned_daily_hours = db.Column(db.Numeric(8, 2), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    project = db.relationship("Project", back_populates="resource_assignments")
    resource = db.relationship("Resource", back_populates="project_assignments")
    role = db.relationship("TeamRole")
    resource_cost = db.relationship("ResourceCost")


class TaskResource(TimestampMixin, db.Model):
    __tablename__ = "task_resource"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("team_roles.id"), nullable=True, index=True)
    resource_cost_id = db.Column(db.Integer, db.ForeignKey("resource_cost.id"), nullable=True, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False)
    allocation_percent = db.Column(db.Numeric(6, 2), nullable=True)
    planned_hours = db.Column(db.Numeric(10, 2), nullable=True)
    planned_daily_hours = db.Column(db.Numeric(8, 2), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    task = db.relationship("Task", back_populates="resource_assignments")
    resource = db.relationship("Resource", back_populates="task_assignments")
    role = db.relationship("TeamRole")
    resource_cost = db.relationship("ResourceCost")
