from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class CompanyTypeConfig(TimestampMixin, db.Model):
    __tablename__ = "company_type_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("owner_user_id", "name", name="uq_company_type_configs_owner_name"),
    )


class PaymentTypeConfig(TimestampMixin, db.Model):
    __tablename__ = "payment_type_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("owner_user_id", "name", name="uq_payment_type_configs_owner_name"),
    )


class ClientCatalogOptionConfig(TimestampMixin, db.Model):
    __tablename__ = "client_catalog_option_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    field_key = db.Column(db.String(40), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "owner_user_id",
            "field_key",
            "name",
            name="uq_client_catalog_option_configs_owner_field_name",
        ),
    )


class SystemCatalogOptionConfig(TimestampMixin, db.Model):
    __tablename__ = "system_catalog_option_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    module_key = db.Column(db.String(40), nullable=False, index=True)
    catalog_key = db.Column(db.String(60), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "owner_user_id",
            "module_key",
            "catalog_key",
            "name",
            name="uq_system_catalog_option_configs_owner_module_catalog_name",
        ),
    )
