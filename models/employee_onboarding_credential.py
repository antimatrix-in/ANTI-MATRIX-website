import base64
import hashlib
from datetime import datetime, timezone
from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import generate_password_hash, check_password_hash
from . import db


def _derive_fernet_key(secret: str) -> bytes:
    """Derives a deterministic 32-byte URL-safe base64 Fernet key using SHA-256."""
    key_digest = hashlib.sha256(secret.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(key_digest)


def encrypt_temporary_password(plaintext: str, secret_key: str) -> str:
    """Encrypts temporary password string at rest using server-side secret key."""
    if not plaintext or not secret_key:
        return ""
    fernet = Fernet(_derive_fernet_key(secret_key))
    token = fernet.encrypt(plaintext.encode('utf-8'))
    return token.decode('utf-8')


def decrypt_temporary_password(ciphertext: str, secret_key: str) -> str:
    """Decrypts temporary password string at rest using server-side secret key."""
    if not ciphertext or not secret_key:
        return ""
    try:
        fernet = Fernet(_derive_fernet_key(secret_key))
        plaintext_bytes = fernet.decrypt(ciphertext.encode('utf-8'))
        return plaintext_bytes.decode('utf-8')
    except (InvalidToken, Exception):
        return ""


class EmployeeOnboardingCredential(db.Model):
    """
    Dedicated table for the temporary employee onboarding credential lifecycle.
    Stores temporary password encrypted at rest and one-way password hash for verification.
    Shared with the Internship Portal via Supabase.
    """
    __tablename__ = 'employee_onboarding_credentials'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(
        db.String(20),
        db.ForeignKey('employees.employee_id', ondelete='CASCADE'),
        unique=True,
        nullable=False,
        index=True
    )
    temporary_password_encrypted = db.Column(db.Text, nullable=True)
    temporary_password_hash = db.Column(db.String(256), nullable=False)
    status = db.Column(db.String(20), default='ACTIVE', nullable=False, index=True)  # 'ACTIVE', 'RESET', 'EXPIRED'
    password_reset_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    @property
    def is_active(self) -> bool:
        """Returns True if the temporary credential is still active and decryptable."""
        return self.status == 'ACTIVE' and bool(self.temporary_password_encrypted)

    def set_password(self, plaintext: str, secret_key: str):
        """Encrypts temporary password at rest and generates a secure one-way hash."""
        self.temporary_password_hash = generate_password_hash(plaintext)
        self.temporary_password_encrypted = encrypt_temporary_password(plaintext, secret_key)
        self.status = 'ACTIVE'
        self.password_reset_at = None
        self.updated_at = datetime.now(timezone.utc)

    def decrypt_password(self, secret_key: str) -> str:
        """
        Decrypts temporary password for authorized Joining Email and Admin Portal display.
        Strictly returns empty string if status is not ACTIVE or after password reset.
        """
        if self.status != 'ACTIVE' or not self.temporary_password_encrypted:
            return ""
        return decrypt_temporary_password(self.temporary_password_encrypted, secret_key)

    def verify_password(self, candidate_password: str) -> bool:
        """
        Verifies candidate password against temporary_password_hash for initial portal activation.
        Strictly returns False if credential status is not ACTIVE.
        """
        if self.status != 'ACTIVE' or not self.temporary_password_hash:
            return False
        return check_password_hash(self.temporary_password_hash, candidate_password)

    def mark_reset(self):
        """
        Transitions temporary credential status to RESET upon successful password change.
        Permanently invalidates and purges the encrypted temporary password.
        """
        self.status = 'RESET'
        self.password_reset_at = datetime.now(timezone.utc)
        self.temporary_password_encrypted = None
        self.updated_at = datetime.now(timezone.utc)

    @classmethod
    def create_for_employee(cls, employee_id: str, plaintext_password: str, secret_key: str):
        """Factory method to instantiate a secure active onboarding credential record."""
        cred = cls(employee_id=employee_id, status='ACTIVE')
        cred.set_password(plaintext_password, secret_key)
        return cred

    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'status': self.status,
            'password_reset_at': self.password_reset_at.isoformat() if self.password_reset_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<EmployeeOnboardingCredential id={self.id} employee_id='{self.employee_id}' status='{self.status}'>"
