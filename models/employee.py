import base64
import hashlib
from datetime import datetime, timezone
import string
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from . import db


def _xor_cipher(data: bytes, key: bytes) -> bytes:
    """Symmetric stream cipher for temporary server-side credential retention using SHA-256 key stretching."""
    chunks = []
    needed = len(data)
    i = 0
    while len(b''.join(chunks)) < needed:
        chunks.append(hashlib.sha256(key + str(i).encode()).digest())
        i += 1
    expanded_key = b''.join(chunks)[:needed]
    return bytes(a ^ b for a, b in zip(data, expanded_key))


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    application_id = db.Column(
        db.Integer,
        db.ForeignKey('job_applications.id', ondelete='CASCADE'),
        unique=True,
        nullable=True,
        index=True
    )
    password_hash = db.Column(db.String(256), nullable=False)
    temp_password_encrypted = db.Column(db.String(500), nullable=True)  # Securely retained for Admin Portal display until password reset
    temporary_password_active = db.Column(db.Boolean, default=True, nullable=False)
    account_status = db.Column(db.String(30), default='active', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship to JobApplication (1-to-1)
    application = db.relationship(
        'JobApplication',
        backref=db.backref('employee', uselist=False, cascade='all, delete-orphan')
    )

    # Relationship to EmployeeOnboardingCredential (1-to-1)
    onboarding_credential = db.relationship(
        'EmployeeOnboardingCredential',
        backref=db.backref('employee', uselist=False),
        uselist=False,
        cascade='all, delete-orphan'
    )

    @property
    def is_temporary_password_active(self) -> bool:
        """Indicates whether the employee's temporary password is still active and retrievable."""
        if self.onboarding_credential:
            return self.onboarding_credential.is_active
        return bool(self.temporary_password_active and self.temp_password_encrypted)

    def set_password(self, password: str):
        """Hashes plaintext password with Werkzeug secure password hashing."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verifies candidate password against stored secure hash."""
        return check_password_hash(self.password_hash, password)

    def reset_password(self, new_password: str):
        """
        Securely updates password hash upon successful password reset from the Internship Portal or Admin.
        Permanently invalidates and purges the temporary password and marks temporary_password_active = False.
        """
        self.set_password(new_password)
        self.temporary_password_active = False
        self.temp_password_encrypted = None
        self.updated_at = datetime.now(timezone.utc)
        if self.onboarding_credential:
            self.onboarding_credential.mark_reset()

    def set_temp_password(self, plaintext: str, secret_key: str):
        """Encrypts temporary password into onboarding_credential and marks active."""
        if not plaintext or not secret_key:
            if self.onboarding_credential:
                self.onboarding_credential.mark_reset()
            self.temp_password_encrypted = None
            self.temporary_password_active = False
            return

        from .employee_onboarding_credential import EmployeeOnboardingCredential
        if not self.onboarding_credential:
            self.onboarding_credential = EmployeeOnboardingCredential(
                employee_id=self.employee_id,
                status='ACTIVE'
            )
            db.session.add(self.onboarding_credential)

        self.onboarding_credential.set_password(plaintext, secret_key)
        self.temporary_password_active = True
        try:
            encrypted_bytes = _xor_cipher(plaintext.encode('utf-8'), secret_key.encode('utf-8'))
            self.temp_password_encrypted = base64.b64encode(encrypted_bytes).decode('utf-8')
        except Exception:
            pass

    def get_temp_password(self, secret_key: str) -> str:
        """
        Decrypts temporary password for authorized Admin Portal view and onboarding email.
        Returns empty string if the temporary password has been reset or is unavailable.
        """
        if self.onboarding_credential:
            return self.onboarding_credential.decrypt_password(secret_key)

        if not self.temporary_password_active or not self.temp_password_encrypted or not secret_key:
            return ""
        try:
            raw_bytes = base64.b64decode(self.temp_password_encrypted.encode('utf-8'))
            decrypted = _xor_cipher(raw_bytes, secret_key.encode('utf-8'))
            return decrypted.decode('utf-8')
        except Exception:
            return ""

    def clear_temp_password(self):
        """Purges encrypted temporary password and marks credential as RESET."""
        if self.onboarding_credential:
            self.onboarding_credential.mark_reset()
        self.temp_password_encrypted = None
        self.temporary_password_active = False

    @property
    def job(self):
        return self.application.job if self.application else None

    @property
    def candidate_name(self):
        return self.application.full_name if self.application else ''

    @property
    def candidate_email(self):
        return self.application.email if self.application else ''

    @property
    def candidate_phone(self):
        return self.application.phone if self.application else ''

    @property
    def offer_letter_doc(self):
        """Returns the latest generated Offer Letter document for this employee if any."""
        for doc in self.documents:
            if doc.document_type == 'offer_letter':
                return doc
        return None

    @classmethod
    def generate_unique_employee_id(cls, max_attempts: int = 2000) -> str:
        """
        Generates a non-sequential, cryptographically random Employee ID in the format AM + 4 random digits (e.g. AM4827).
        Enforces uniqueness by checking the database and retrying on collision.
        """
        for _ in range(max_attempts):
            # Generate 4 random digits from 0000 to 9999
            random_digits = f"{secrets.randbelow(10000):04d}"
            emp_id = f"AM{random_digits}"
            if not cls.query.filter_by(employee_id=emp_id).first():
                return emp_id

        raise ValueError("Unable to generate a new Employee ID. Please contact the administrator.")

    @staticmethod
    def generate_secure_password(length: int = 12) -> str:
        """
        Generates a cryptographically strong random password containing uppercase, lowercase,
        digits, and symbols. Prefixed with 'AM' to align with Anti-Matrix credential standards.
        Example output format: AMx7K9@pQ4#
        """
        if length < 8:
            length = 8

        # Guarantee at least 1 uppercase, 1 lowercase, 1 digit, 1 special character
        upper = string.ascii_uppercase
        lower = string.ascii_lowercase
        digits = string.digits
        symbols = "@#$%&*!"

        prefix = "AM"
        remaining_len = length - len(prefix)

        # Ensure mandatory character types
        mandatory = [
            secrets.choice(lower),
            secrets.choice(digits),
            secrets.choice(upper),
            secrets.choice(symbols)
        ]

        all_chars = upper + lower + digits + symbols
        fillers = [secrets.choice(all_chars) for _ in range(remaining_len - len(mandatory))]

        tail = mandatory + fillers
        # Cryptographic shuffle
        shuffled = []
        while tail:
            idx = secrets.randbelow(len(tail))
            shuffled.append(tail.pop(idx))

        return prefix + "".join(shuffled)

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'application_id': self.application_id,
            'application_code': self.application.formatted_code if self.application else None,
            'candidate_name': self.candidate_name,
            'candidate_email': self.candidate_email,
            'job_title': self.job.title if self.job else None,
            'duration': self.application.duration_display if self.application else None,
            'account_status': self.account_status,
            'temporary_password_active': self.is_temporary_password_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f"<Employee id={self.id} employee_id='{self.employee_id}' app_id={self.application_id} status='{self.account_status}'>"
