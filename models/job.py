from datetime import datetime, timezone, timedelta
from . import db
from config import INTERNSHIP_FEES, INTERNSHIP_PRICING


class JobPosting(db.Model):
    __tablename__ = 'job_postings'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(20), unique=True, nullable=True, index=True)
    title = db.Column(db.String(150), nullable=False)
    department = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    employment_type = db.Column(db.String(50), nullable=False, default='Full-time')
    duration = db.Column(db.String(50), nullable=True)  # '1_month', '3_months', or None
    short_description = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=True)
    qualifications = db.Column(db.Text, nullable=True)
    experience = db.Column(db.String(100), nullable=True)
    responsibilities = db.Column(db.Text, nullable=True)
    skills = db.Column(db.Text, nullable=True)
    salary = db.Column(db.String(100), nullable=True)
    application_deadline = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    applications = db.relationship('JobApplication', backref='job', lazy=True, cascade='all, delete-orphan')

    @classmethod
    def generate_unique_job_id(cls, preferred_id=None):
        """
        Generate a unique Job ID in the format JB#### (e.g., JB1001, JB1002, JB1234).
        If preferred_id is provided, matches format, and is not already assigned, it is returned.
        Otherwise finds the first available unique JB#### starting from JB1001.
        """
        import re
        if preferred_id:
            cand = str(preferred_id).strip().upper()
            if re.match(r'^JB\d{4}$', cand):
                exists = cls.query.filter_by(job_id=cand).first()
                if not exists:
                    return cand

        all_records = cls.query.with_entities(cls.job_id).all()
        used = {r[0].upper() for r in all_records if r[0]}

        num = 1001
        while True:
            candidate = f"JB{num:04d}"
            if candidate not in used:
                return candidate
            num += 1

    @property
    def is_updated(self):
        """
        Indicates whether the job posting has been marked as updated by an administrator.
        Returns True when updated_at is ahead of created_at (> 10 seconds difference).
        """
        if not self.updated_at or not self.created_at:
            return False
        try:
            up = self.updated_at
            cr = self.created_at
            if up.tzinfo is not None and cr.tzinfo is None:
                cr = cr.replace(tzinfo=up.tzinfo)
            elif cr.tzinfo is not None and up.tzinfo is None:
                up = up.replace(tzinfo=cr.tzinfo)
            return (up - cr).total_seconds() > 10
        except Exception:
            return False

    @property
    def is_internship(self):
        return (self.employment_type and self.employment_type.lower() == 'internship') or bool(self.duration)

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        pricing = INTERNSHIP_PRICING.get(self.duration)
        if pricing:
            return pricing['label']
        if self.duration == '1_month':
            return '1 Month'
        elif self.duration == '3_months':
            return '3 Months'
        return self.duration

    @property
    def fee_inr(self):
        if not self.is_internship or not self.duration:
            return 0
        return INTERNSHIP_FEES.get(self.duration, 0)

    @property
    def fee_breakdown(self):
        from services.payment_service import calculate_payment_total
        return calculate_payment_total(self.fee_inr)

    @property
    def total_fee(self):
        return self.fee_breakdown['total_amount']

    @property
    def fee_display(self):
        fee = self.fee_inr
        if fee <= 0:
            return None
        return f"₹{fee}"

    @property
    def total_fee_display(self):
        fee = self.fee_inr
        if fee <= 0:
            return None
        b = self.fee_breakdown
        return f"₹{fee} + 18% GST (Total ₹{b['total_amount']:.2f})"

    def get_skills_list(self):
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(',') if s.strip()]

    def get_requirements_list(self):
        if not self.requirements:
            return []
        lines = [line.strip().lstrip('•-*').strip() for line in self.requirements.splitlines() if line.strip()]
        return lines if lines else [self.requirements.strip()]

    def get_responsibilities_list(self):
        if not self.responsibilities:
            return []
        lines = [line.strip().lstrip('•-*').strip() for line in self.responsibilities.splitlines() if line.strip()]
        return lines if lines else [self.responsibilities.strip()]

    @property
    def application_count(self):
        return len(self.applications)

    @property
    def new_application_count(self):
        return sum(1 for app in self.applications if app.status == 'New')

    def __repr__(self):
        return f"<JobPosting id={self.id} title='{self.title}' dept='{self.department}' duration='{self.duration}' active={self.is_active}>"


class JobApplication(db.Model):
    __tablename__ = 'job_applications'

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job_postings.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    application_code = db.Column(db.String(50), unique=True, nullable=True, index=True)
    
    # Personal Details
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(50), nullable=False)
    address = db.Column(db.Text, nullable=True)
    state = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    pincode = db.Column(db.String(20), nullable=True)
    
    # College & Academic Details
    education_level = db.Column(db.String(100), nullable=True)
    college = db.Column(db.String(150), nullable=True, default='')
    department = db.Column(db.String(100), nullable=True, default='')
    degree = db.Column(db.String(100), nullable=True, default='')
    major = db.Column(db.String(100), nullable=True, default='')
    year_of_study = db.Column(db.String(50), nullable=True)
    graduation_year = db.Column(db.String(20), nullable=True, default='')
    current_cgpa = db.Column(db.Float, nullable=True)
    
    # Professional & Statement Information
    experience = db.Column(db.String(100), nullable=True)
    skills = db.Column(db.Text, nullable=True, default='')
    portfolio_url = db.Column(db.String(255), nullable=True)
    linkedin_url = db.Column(db.String(255), nullable=True)
    github_url = db.Column(db.String(255), nullable=True)
    cover_letter = db.Column(db.Text, nullable=True, default='')
    why_join = db.Column(db.Text, nullable=True)
    
    # Identity Documents & Resume
    aadhaar_filename = db.Column(db.String(255), nullable=True)
    aadhaar_path = db.Column(db.String(255), nullable=True)
    pan_filename = db.Column(db.String(255), nullable=True)
    pan_path = db.Column(db.String(255), nullable=True)
    college_id_filename = db.Column(db.String(255), nullable=True)
    college_id_path = db.Column(db.String(255), nullable=True)
    resume_filename = db.Column(db.String(255), nullable=False)
    resume_path = db.Column(db.String(255), nullable=False)
    
    # Internship & Payment Info
    duration = db.Column(db.String(50), nullable=True)  # '1_month', '3_months', or None
    application_fee = db.Column(db.Integer, nullable=True, default=0)  # Amount in INR
    base_amount = db.Column(db.Float, nullable=True)  # Base Fee before GST (e.g. 199.00 or 399.00)
    gst_rate = db.Column(db.Float, nullable=True, default=18.0)  # 18.0
    gst_amount = db.Column(db.Float, nullable=True)  # GST 18% Amount (e.g. 35.82 or 71.82)
    
    # Distinct Payment & Application States
    payment_status = db.Column(db.String(30), default='pending', nullable=False)  # pending, processing, paid, failed, cancelled, exempt
    application_status = db.Column(db.String(30), default='pending_payment', nullable=False)  # pending_payment, submitted, reviewed, shortlisted, rejected, hired
    status = db.Column(db.String(30), default='New', nullable=False)  # Recruitment Pipeline Stage: New, Reviewed, Shortlisted, Rejected, Hired
    
    # Application Success Email Tracking
    application_success_email_status = db.Column(db.String(30), default='PENDING', nullable=False)  # PENDING, SENT, FAILED
    application_success_email_sent_at = db.Column(db.DateTime, nullable=True)

    # Offer Completion & Joining Tracking
    joining_date = db.Column(db.String(100), nullable=True)
    joining_email_status = db.Column(db.String(30), default='NOT_SENT', nullable=False)  # NOT_SENT, SENDING, SENT, FAILED
    joining_email_sent_at = db.Column(db.DateTime, nullable=True)
    offer_completed_at = db.Column(db.DateTime, nullable=True)
    hired_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    payments = db.relationship('Payment', backref='application', lazy=True, cascade='all, delete-orphan', order_by='Payment.created_at.desc()')

    @property
    def formatted_code(self):
        if self.application_code:
            return self.application_code
        if self.payment_status in ['paid', 'exempt']:
            return f"AM-APP-{self.id:06d}"
        return ""

    @property
    def duration_display(self):
        if not self.duration:
            return ''
        pricing = INTERNSHIP_PRICING.get(self.duration)
        if pricing:
            return pricing['label']
        d_lower = str(self.duration).strip().lower()
        if d_lower in ['1_month', '1 month', '1']:
            return '1 Month'
        elif d_lower in ['3_months', '3 months', '3']:
            return '3 Months'
        return str(self.duration)

    @property
    def fee_breakdown(self):
        from services.payment_service import calculate_payment_total
        base = self.base_amount or INTERNSHIP_FEES.get(self.duration) or (self.job.fee_inr if self.job else None) or 199
        return calculate_payment_total(base)

    @property
    def latest_payment(self):
        if self.payments:
            return self.payments[0]
        return None

    @property
    def payment(self):
        return self.latest_payment

    @property
    def offer_letter_doc(self):
        """Returns the generated Offer Letter EmployeeDocument for this application if any."""
        if hasattr(self, 'employee_documents') and self.employee_documents:
            for doc in self.employee_documents:
                if doc.document_type == 'offer_letter':
                    return doc
        if self.employee and hasattr(self.employee, 'documents'):
            for doc in self.employee.documents:
                if doc.document_type == 'offer_letter':
                    return doc
        try:
            from models.document import EmployeeDocument
            doc = EmployeeDocument.query.filter_by(application_id=self.id, document_type='offer_letter').first()
            if doc:
                return doc
            if self.formatted_code:
                doc = EmployeeDocument.query.filter(
                    EmployeeDocument.document_type == 'offer_letter',
                    EmployeeDocument.file_name.ilike(f"%{self.formatted_code}%")
                ).first()
                if doc:
                    return doc
        except Exception:
            pass
        return None

    @property
    def status_display(self):
        """Map internal database recruitment status to clean human-friendly label (Applied, Under Review, Shortlisted, Offer Completed, Hired)."""
        st = (self.status or self.application_status or 'APPLIED').strip()
        mapping = {
            'APPLIED': 'Applied',
            'applied': 'Applied',
            'New': 'Applied',
            'SUBMITTED': 'Applied',
            'submitted': 'Applied',
            'Reviewed': 'Under Review',
            'UNDER_REVIEW': 'Under Review',
            'reviewed': 'Under Review',
            'under_review': 'Under Review',
            'Shortlisted': 'Shortlisted',
            'SHORTLISTED': 'Shortlisted',
            'shortlisted': 'Shortlisted',
            'OFFER_COMPLETED': 'Offer Completed',
            'offer_completed': 'Offer Completed',
            'COMPLETED': 'Offer Completed',
            'completed': 'Offer Completed',
            'Rejected': 'Not Selected',
            'REJECTED': 'Not Selected',
            'rejected': 'Not Selected',
            'Hired': 'Hired',
            'HIRED': 'Hired',
            'hired': 'Hired',
            'pending_payment': 'Pending Payment',
            'PENDING_PAYMENT': 'Pending Payment'
        }
        return mapping.get(st, st)

    @property
    def status_badge_class(self):
        st = (self.status or self.application_status or 'APPLIED').strip().lower()
        if st in ['hired']:
            return 'hired'
        elif st in ['shortlisted', 'offer_completed', 'completed']:
            return 'shortlisted'
        elif st in ['reviewed', 'under_review']:
            return 'reviewed'
        elif st in ['rejected', 'not selected']:
            return 'rejected'
        elif st in ['new', 'submitted', 'applied']:
            return 'new'
        return 'new'

    def get_skills_list(self):
        if not self.skills:
            return []
        return [s.strip() for s in self.skills.split(',') if s.strip()]

    def __repr__(self):
        return f"<JobApplication id={self.id} code='{self.formatted_code}' name='{self.full_name}' user_id={self.user_id} payment='{self.payment_status}' app_status='{self.application_status}'>"


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('job_applications.id'), nullable=False)
    cashfree_order_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    cashfree_payment_session_id = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Float, nullable=False)  # Total Payable Amount in INR (including 18% GST)
    base_amount = db.Column(db.Float, nullable=True)  # Base Fee before GST (e.g. 199.00 or 399.00)
    gst_rate = db.Column(db.Float, nullable=True, default=18.0)  # 18.0
    gst_amount = db.Column(db.Float, nullable=True)  # GST 18% Amount (e.g. 35.82 or 71.82)
    currency = db.Column(db.String(10), default='INR', nullable=False)
    payment_status = db.Column(db.String(30), default='pending', nullable=False)  # pending, processing, paid, failed, cancelled
    gateway = db.Column(db.String(50), default='cashfree', nullable=False)
    cf_payment_id = db.Column(db.String(150), nullable=True)
    gateway_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    @property
    def fee_breakdown(self):
        from services.payment_service import calculate_payment_total
        if self.base_amount is not None:
            return calculate_payment_total(self.base_amount)
        return {
            'base_amount': float(self.amount or 0),
            'gst_rate': 0.0,
            'gst_amount': 0.0,
            'total_amount': float(self.amount or 0),
            'formatted_base': f"₹{float(self.amount or 0):.2f}",
            'formatted_gst': "₹0.00",
            'formatted_total': f"₹{float(self.amount or 0):.2f}"
        }

    def __repr__(self):
        return f"<Payment id={self.id} order='{self.cashfree_order_id}' amount={self.amount} status='{self.payment_status}'>"

