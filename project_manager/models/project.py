from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class Stakeholder(TimestampMixin, db.Model):
    __tablename__ = "stakeholders"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    project = db.relationship("Project", back_populates="stakeholders")


class Project(TimestampMixin, db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.String(40), nullable=True, unique=True, index=True)
    name = db.Column(db.String(180), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    client_contract_id = db.Column(db.Integer, db.ForeignKey("client_contracts.id"), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    objective = db.Column(db.Text, nullable=True)
    project_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    business_unit = db.Column(db.String(120), nullable=True)
    product_solution = db.Column(db.String(120), nullable=True)
    service_module = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(80), nullable=True)
    priority = db.Column(db.String(20), nullable=False)
    complexity_level = db.Column(db.String(20), nullable=True)
    criticality_level = db.Column(db.String(20), nullable=True)
    project_origin = db.Column(db.String(80), nullable=True)
    parent_project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)
    project_manager = db.Column(db.String(120), nullable=True)
    project_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    commercial_manager = db.Column(db.String(120), nullable=True)
    commercial_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    functional_manager = db.Column(db.String(120), nullable=True)
    functional_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    technical_manager = db.Column(db.String(120), nullable=True)
    technical_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    client_sponsor = db.Column(db.String(120), nullable=True)
    key_user = db.Column(db.String(120), nullable=True)
    onboarding_date = db.Column(db.Date, nullable=True)
    estimated_start_date = db.Column(db.Date, nullable=True)
    actual_start_date = db.Column(db.Date, nullable=True)
    estimated_end_date = db.Column(db.Date, nullable=True)
    actual_end_date = db.Column(db.Date, nullable=True)
    estimated_duration_days = db.Column(db.Integer, nullable=True)
    kickoff_date = db.Column(db.Date, nullable=True)
    close_date = db.Column(db.Date, nullable=True)
    methodology = db.Column(db.String(80), nullable=True)
    documentation_repo = db.Column(db.String(255), nullable=True)
    external_board_url = db.Column(db.String(255), nullable=True)
    committee_frequency = db.Column(db.String(80), nullable=True)
    communication_channel = db.Column(db.String(80), nullable=True)
    billing_mode = db.Column(db.String(80), nullable=True)
    currency_code = db.Column(db.String(10), nullable=True)
    sold_budget = db.Column(db.Numeric(14, 2), nullable=True)
    estimated_cost = db.Column(db.Numeric(14, 2), nullable=True)
    estimated_margin = db.Column(db.Numeric(8, 2), nullable=True)
    estimated_hours = db.Column(db.Numeric(10, 2), nullable=True)
    average_rate = db.Column(db.Numeric(10, 2), nullable=True)
    cost_center = db.Column(db.String(80), nullable=True)
    erp_psa_code = db.Column(db.String(80), nullable=True)
    owner = db.Column(db.String(120), nullable=False)
    observations = db.Column(db.Text, nullable=True)
    contract_file_name = db.Column(db.String(255), nullable=True)
    contract_original_name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    client = db.relationship("Client", back_populates="projects")
    client_contract = db.relationship("ClientContract", back_populates="projects")
    project_manager_resource = db.relationship("Resource", foreign_keys=[project_manager_resource_id], lazy="joined")
    commercial_manager_resource = db.relationship("Resource", foreign_keys=[commercial_manager_resource_id], lazy="joined")
    functional_manager_resource = db.relationship("Resource", foreign_keys=[functional_manager_resource_id], lazy="joined")
    technical_manager_resource = db.relationship("Resource", foreign_keys=[technical_manager_resource_id], lazy="joined")
    parent_project = db.relationship(
        "Project",
        remote_side=[id],
        backref=db.backref("child_projects", lazy="selectin"),
    )
    resource_assignments = db.relationship(
        "ProjectResource",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    stakeholders = db.relationship(
        "Stakeholder",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    tasks = db.relationship(
        "Task",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Task(TimestampMixin, db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)
    parent_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    task_type = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(40), nullable=True)
    priority = db.Column(db.String(20), nullable=True)
    responsible = db.Column(db.String(120), nullable=True)
    responsible_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    creator = db.Column(db.String(120), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    actual_start_date = db.Column(db.Date, nullable=True)
    actual_end_date = db.Column(db.Date, nullable=True)
    estimated_duration_days = db.Column(db.Integer, nullable=True)
    estimated_hours = db.Column(db.Numeric(10, 2), nullable=True)
    logged_hours = db.Column(db.Numeric(10, 2), nullable=True)
    progress_percent = db.Column(db.Integer, nullable=True, default=0)
    rollup_updated_at = db.Column(db.DateTime, nullable=True)
    sort_order = db.Column(db.Integer, nullable=True, default=0)
    tags = db.Column(db.String(255), nullable=True)
    is_milestone = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    project = db.relationship("Project", back_populates="tasks")
    parent_task = db.relationship(
        "Task",
        remote_side=[id],
        backref=db.backref("subtasks", lazy="selectin"),
    )
    responsible_resource = db.relationship("Resource", foreign_keys=[responsible_resource_id], lazy="joined")
    resource_assignments = db.relationship(
        "TaskResource",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    additional_assignees = db.relationship(
        "TaskAssignee",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    comments = db.relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attachments = db.relationship(
        "TaskAttachment",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    predecessor_links = db.relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.successor_task_id",
        back_populates="successor_task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    successor_links = db.relationship(
        "TaskDependency",
        foreign_keys="TaskDependency.predecessor_task_id",
        back_populates="predecessor_task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TaskAssignee(TimestampMixin, db.Model):
    __tablename__ = "task_assignees"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    assignee_name = db.Column(db.String(120), nullable=False)

    task = db.relationship("Task", back_populates="additional_assignees")

    __table_args__ = (
        db.UniqueConstraint("task_id", "assignee_name", name="uq_task_assignees_task_name"),
    )


class TaskDependency(TimestampMixin, db.Model):
    __tablename__ = "task_dependencies"

    id = db.Column(db.Integer, primary_key=True)
    predecessor_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    successor_task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    dependency_type = db.Column(db.String(40), nullable=True)

    predecessor_task = db.relationship(
        "Task",
        foreign_keys=[predecessor_task_id],
        back_populates="successor_links",
    )
    successor_task = db.relationship(
        "Task",
        foreign_keys=[successor_task_id],
        back_populates="predecessor_links",
    )

    __table_args__ = (
        db.UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_task_dependencies_pair",
        ),
    )


class TaskComment(TimestampMixin, db.Model):
    __tablename__ = "task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    author = db.Column(db.String(120), nullable=True)
    body = db.Column(db.Text, nullable=False)

    task = db.relationship("Task", back_populates="comments")


class TaskAttachment(TimestampMixin, db.Model):
    __tablename__ = "task_attachments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True)
    file_name = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    uploaded_by = db.Column(db.String(120), nullable=True)

    task = db.relationship("Task", back_populates="attachments")
