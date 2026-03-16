from werkzeug.security import check_password_hash, generate_password_hash

from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class Role(TimestampMixin, db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_editable = db.Column(db.Boolean, default=True, nullable=False)
    is_deletable = db.Column(db.Boolean, default=True, nullable=False)

    users = db.relationship("User", back_populates="role", lazy="selectin")
    permissions = db.relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Permission(TimestampMixin, db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    module = db.Column(db.String(40), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    roles = db.relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class RolePermission(TimestampMixin, db.Model):
    __tablename__ = "role_permissions"

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False, index=True)
    permission_id = db.Column(db.Integer, db.ForeignKey("permissions.id"), nullable=False, index=True)

    role = db.relationship("Role", back_populates="permissions")
    permission = db.relationship("Permission", back_populates="roles")

    __table_args__ = (
        db.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )


class UserClientAssignment(TimestampMixin, db.Model):
    __tablename__ = "user_client_assignments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "client_id", name="uq_user_client_assignment"),
    )


class UserProjectAssignment(TimestampMixin, db.Model):
    __tablename__ = "user_project_assignments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "project_id", name="uq_user_project_assignment"),
    )


class AccessAuditLog(TimestampMixin, db.Model):
    __tablename__ = "access_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    username = db.Column(db.String(80), nullable=True)
    event = db.Column(db.String(20), nullable=False)  # login/logout
    outcome = db.Column(db.String(20), nullable=False)  # success/failure
    reason = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(120), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)


class AuditTrailLog(TimestampMixin, db.Model):
    __tablename__ = "audit_trail_logs"

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(80), nullable=False, index=True)
    record_id = db.Column(db.String(80), nullable=False, index=True)
    action = db.Column(db.String(20), nullable=False)  # insert/update/delete
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    old_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=True)


class User(TimestampMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    read_only = db.Column(db.Boolean, default=False, nullable=False)
    full_access = db.Column(db.Boolean, default=True, nullable=False)
    last_login_at = db.Column(db.DateTime, nullable=True)
    onboarding_date = db.Column(db.Date, nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=True, index=True)

    role = db.relationship("Role", back_populates="users", lazy="joined")
    clients = db.relationship(
        "UserClientAssignment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    projects = db.relationship(
        "UserProjectAssignment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def display_name(self) -> str:
        full = f"{(self.first_name or '').strip()} {(self.last_name or '').strip()}".strip()
        return full or self.username
