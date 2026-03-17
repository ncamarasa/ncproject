from project_manager.extensions import db
from project_manager.models.base import TimestampMixin


class Client(TimestampMixin, db.Model):
    __tablename__ = "clients"

    id = db.Column(db.Integer, primary_key=True)
    client_code = db.Column(db.String(40), nullable=True, unique=True, index=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    contact_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    legal_name = db.Column(db.String(180), nullable=True)
    trade_name = db.Column(db.String(180), nullable=True)
    tax_id = db.Column(db.String(32), nullable=True, unique=True)
    client_type = db.Column(db.String(40), nullable=True)
    status = db.Column(db.String(40), nullable=True)
    industry = db.Column(db.String(80), nullable=True)
    company_size = db.Column(db.String(40), nullable=True)
    country = db.Column(db.String(80), nullable=True)
    region = db.Column(db.String(80), nullable=True)
    city = db.Column(db.String(80), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    currency_code = db.Column(db.String(10), nullable=True)
    onboarding_date = db.Column(db.Date, nullable=True)
    observations = db.Column(db.Text, nullable=True)

    lead_source = db.Column(db.String(80), nullable=True)
    segment = db.Column(db.String(80), nullable=True)
    commercial_priority = db.Column(db.String(20), nullable=True)
    sales_executive = db.Column(db.String(120), nullable=True)
    sales_executive_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    account_manager = db.Column(db.String(120), nullable=True)
    account_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    commercial_status = db.Column(db.String(40), nullable=True)
    billing_potential = db.Column(db.Numeric(12, 2), nullable=True)
    health_score = db.Column(db.Integer, nullable=True)
    risk_level = db.Column(db.String(20), nullable=True)
    last_interaction_at = db.Column(db.Date, nullable=True)
    next_action_at = db.Column(db.Date, nullable=True)

    tax_condition = db.Column(db.String(80), nullable=True)
    fiscal_address = db.Column(db.String(255), nullable=True)
    billing_email = db.Column(db.String(120), nullable=True)
    payment_terms = db.Column(db.String(80), nullable=True)
    purchase_order_required = db.Column(db.Boolean, default=False, nullable=False)
    rate_card = db.Column(db.String(120), nullable=True)
    credit_limit = db.Column(db.Numeric(12, 2), nullable=True)

    methodology = db.Column(db.String(80), nullable=True)
    preferred_support_channel = db.Column(db.String(80), nullable=True)
    support_hours = db.Column(db.String(120), nullable=True)
    timezone = db.Column(db.String(60), nullable=True)
    language = db.Column(db.String(40), nullable=True)
    delivery_manager = db.Column(db.String(120), nullable=True)
    delivery_manager_resource_id = db.Column(db.Integer, db.ForeignKey("resources.id"), nullable=True, index=True)
    criticality_level = db.Column(db.String(20), nullable=True)
    service_type = db.Column(db.String(80), nullable=True)
    billing_mode = db.Column(db.String(80), nullable=True)
    default_rate = db.Column(db.Numeric(10, 2), nullable=True)
    contracted_hours = db.Column(db.Numeric(10, 2), nullable=True)
    approval_flow = db.Column(db.Text, nullable=True)

    projects = db.relationship("Project", back_populates="client", lazy="dynamic")
    sales_executive_resource = db.relationship("Resource", foreign_keys=[sales_executive_resource_id], lazy="joined")
    account_manager_resource = db.relationship("Resource", foreign_keys=[account_manager_resource_id], lazy="joined")
    delivery_manager_resource = db.relationship("Resource", foreign_keys=[delivery_manager_resource_id], lazy="joined")
    contacts = db.relationship(
        "ClientContact",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    contracts = db.relationship(
        "ClientContract",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    documents = db.relationship(
        "ClientDocument",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    interactions = db.relationship(
        "ClientInteraction",
        back_populates="client",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ClientContact(TimestampMixin, db.Model):
    __tablename__ = "client_contacts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    job_title = db.Column(db.String(120), nullable=True)
    area = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    phone = db.Column(db.String(40), nullable=True)
    whatsapp = db.Column(db.String(40), nullable=True)
    relationship_role = db.Column(db.String(80), nullable=True)
    influence_level = db.Column(db.String(20), nullable=True)
    interest_level = db.Column(db.String(20), nullable=True)
    is_primary = db.Column(db.Boolean, default=False, nullable=False)
    is_technical = db.Column(db.Boolean, default=False, nullable=False)
    is_administrative = db.Column(db.Boolean, default=False, nullable=False)
    is_billing = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    client = db.relationship("Client", back_populates="contacts")


class ClientContract(TimestampMixin, db.Model):
    __tablename__ = "client_contracts"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    contract_type = db.Column(db.String(80), nullable=False)
    contract_code = db.Column(db.String(80), nullable=True)
    contract_name = db.Column(db.String(180), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    auto_renewal = db.Column(db.Boolean, default=False, nullable=False)
    renewal_date = db.Column(db.Date, nullable=True)
    sla_level = db.Column(db.String(80), nullable=True)
    nda_signed = db.Column(db.Boolean, default=False, nullable=False)
    data_processing_agreement = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(40), nullable=True)
    billing_mode = db.Column(db.String(80), nullable=True)
    currency_code = db.Column(db.String(10), nullable=True)
    amount = db.Column(db.Numeric(14, 2), nullable=True)
    attachment_file_name = db.Column(db.String(255), nullable=True)
    attachment_original_name = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    client = db.relationship("Client", back_populates="contracts")
    projects = db.relationship("Project", back_populates="client_contract", lazy="selectin")


class ClientDocument(TimestampMixin, db.Model):
    __tablename__ = "client_documents"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(80), nullable=True)
    file_name = db.Column(db.String(255), nullable=False)
    original_name = db.Column(db.String(255), nullable=False)
    expires_on = db.Column(db.Date, nullable=True)
    uploaded_by = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    client = db.relationship("Client", back_populates="documents")


class ClientInteraction(TimestampMixin, db.Model):
    __tablename__ = "client_interactions"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    interaction_type = db.Column(db.String(40), nullable=False)
    subject = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=True)
    interaction_date = db.Column(db.Date, nullable=False)
    next_action_date = db.Column(db.Date, nullable=True)
    owner = db.Column(db.String(120), nullable=True)
    risk_level = db.Column(db.String(20), nullable=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)

    client = db.relationship("Client", back_populates="interactions")
