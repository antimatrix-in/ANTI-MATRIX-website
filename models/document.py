from datetime import datetime, timezone
from . import db


class DocumentTemplate(db.Model):
    __tablename__ = 'document_templates'

    id = db.Column(db.Integer, primary_key=True)
    template_type = db.Column(db.String(50), nullable=False, index=True)  # 'offer_letter', 'experience_letter', 'certificate'
    name = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(255), nullable=False)  # Original display filename
    file_path = db.Column(db.String(500), nullable=False)  # Stored absolute/relative filesystem path
    is_active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    job_domain = db.Column(db.String(100), nullable=True, index=True)  # e.g. 'AI & ML', 'Application Development', 'Data Analytics', 'Full Stack Development'
    duration = db.Column(db.String(50), nullable=True, default='Both', index=True)  # 'Both', '1 Month', '3 Months'
    created_by = db.Column(db.String(100), nullable=True, default='Admin')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    @property
    def template_name(self):
        return self.name

    @template_name.setter
    def template_name(self, value):
        self.name = value

    @property
    def original_filename(self):
        return self.filename

    @property
    def is_used_in_generated_documents(self):
        """Checks if any EmployeeDocument references this template ID."""
        return len(self.generated_documents) > 0

    def __repr__(self):
        return f"<DocumentTemplate id={self.id} type='{self.template_type}' domain='{self.job_domain}' duration='{self.duration}' active={self.is_active} name='{self.name}'>"


class EmailTemplate(db.Model):
    __tablename__ = 'email_templates'

    id = db.Column(db.Integer, primary_key=True)
    template_type = db.Column(db.String(50), unique=True, nullable=False, index=True)  # 'application_successful', 'offer_letter'
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self):
        return f"<EmailTemplate id={self.id} type='{self.template_type}' subject='{self.subject[:30]}'>"


class EmployeeDocument(db.Model):
    __tablename__ = 'employee_documents'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey('job_applications.id', ondelete='CASCADE'),
        nullable=True,
        index=True
    )
    employee_id = db.Column(
        db.Integer,
        db.ForeignKey('employees.id', ondelete='CASCADE'),
        nullable=True,
        index=True
    )
    template_id = db.Column(
        db.Integer,
        db.ForeignKey('document_templates.id', ondelete='SET NULL'),
        nullable=True,
        index=True
    )
    document_type = db.Column(db.String(50), default='offer_letter', nullable=False)  # 'offer_letter', 'experience_letter', 'certificate'
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    
    # Status progression: NOT_GENERATED -> GENERATED -> VERIFIED -> SENT
    status = db.Column(db.String(30), default='GENERATED', nullable=False)
    
    # Email tracking: not_sent, sent, failed
    email_status = db.Column(db.String(30), default='not_sent', nullable=False)
    email_error = db.Column(db.Text, nullable=True)
    
    generated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    employee = db.relationship(
        'Employee',
        backref=db.backref('documents', cascade='all, delete-orphan', lazy=True)
    )
    application = db.relationship(
        'JobApplication',
        backref=db.backref('employee_documents', cascade='all, delete-orphan', lazy=True)
    )

    # Relationship to DocumentTemplate
    template = db.relationship('DocumentTemplate', backref=db.backref('generated_documents', lazy=True))

    def __repr__(self):
        return f"<EmployeeDocument id={self.id} app_id={self.application_id} emp_id={self.employee_id} type='{self.document_type}' status='{self.status}' email='{self.email_status}'>"


class EmailLog(db.Model):
    __tablename__ = 'email_logs'

    id = db.Column(db.Integer, primary_key=True)
    recipient_email = db.Column(db.String(120), nullable=False, index=True)
    template_type = db.Column(db.String(50), nullable=False, index=True)  # 'application_successful', 'offer_letter', 'test'
    reference_id = db.Column(db.String(100), nullable=True, index=True)  # e.g. 'AM-APP-000123' or 'AM4827'
    subject = db.Column(db.String(255), nullable=False)
    body_preview = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False)  # 'SENT', 'FAILED'
    provider_message_id = db.Column(db.String(255), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    has_attachment = db.Column(db.Boolean, default=False, nullable=False)
    attachment_name = db.Column(db.String(255), nullable=True)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def __repr__(self):
        return f"<EmailLog id={self.id} to='{self.recipient_email}' type='{self.template_type}' status='{self.status}'>"
