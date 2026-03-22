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
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_editable = db.Column(db.Boolean, default=True, nullable=False)
    is_deletable = db.Column(db.Boolean, default=True, nullable=False)
    exclude_from_default_list = db.Column(db.Boolean, default=False, nullable=False)

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
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_editable = db.Column(db.Boolean, default=True, nullable=False)
    is_deletable = db.Column(db.Boolean, default=True, nullable=False)
    exclude_from_default_list = db.Column(db.Boolean, default=False, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "owner_user_id",
            "module_key",
            "catalog_key",
            "name",
            name="uq_system_catalog_option_configs_owner_module_catalog_name",
        ),
    )


class TeamCalendarHolidayConfig(TimestampMixin, db.Model):
    __tablename__ = "team_calendar_holiday_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    calendar_name = db.Column(db.String(120), nullable=False, index=True)
    holiday_date = db.Column(db.Date, nullable=False, index=True)
    label = db.Column(db.String(180), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "owner_user_id",
            "calendar_name",
            "holiday_date",
            name="uq_team_calendar_holiday_owner_calendar_date",
        ),
    )


class ProjectCurrencyRateConfig(TimestampMixin, db.Model):
    __tablename__ = "project_currency_rate_configs"

    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    from_currency = db.Column(db.String(10), nullable=False, index=True)
    to_currency = db.Column(db.String(10), nullable=False, index=True)
    valid_from = db.Column(db.Date, nullable=False, index=True)
    valid_to = db.Column(db.Date, nullable=True, index=True)
    rate = db.Column(db.Numeric(18, 6), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "owner_user_id",
            "from_currency",
            "to_currency",
            "valid_from",
            name="uq_project_currency_rate_owner_pair_from",
        ),
    )
