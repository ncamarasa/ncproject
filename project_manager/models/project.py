from project_manager.extensions import db

class TimestampMixin:
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now(),
        nullable=False,
    )


class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    contact_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    projects = db.relationship("Project", back_populates="client", lazy="dynamic")


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
    name = db.Column(db.String(180), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    description = db.Column(db.Text, nullable=True)
    project_type = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(40), nullable=False)
    priority = db.Column(db.String(20), nullable=False)
    estimated_start_date = db.Column(db.Date, nullable=True)
    estimated_end_date = db.Column(db.Date, nullable=True)
    owner = db.Column(db.String(120), nullable=False)
    observations = db.Column(db.Text, nullable=True)
    contract_file_name = db.Column(db.String(255), nullable=True)
    contract_original_name = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    client = db.relationship("Client", back_populates="projects")
    stakeholders = db.relationship(
        "Stakeholder",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
