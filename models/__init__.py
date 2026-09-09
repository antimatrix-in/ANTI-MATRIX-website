from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .user import User
from .contact import ContactInquiry
from .job import JobPosting, JobApplication, Payment
from .employee import Employee
from .employee_onboarding_credential import EmployeeOnboardingCredential
from .document import DocumentTemplate, EmailTemplate, EmployeeDocument, EmailLog
from .money_transaction import MoneyTransaction

# Alias for Offer Letter template management
OfferLetterTemplate = DocumentTemplate

__all__ = [
    'db', 'User', 'ContactInquiry', 'JobPosting', 'JobApplication',
    'Payment', 'Employee', 'EmployeeOnboardingCredential', 'DocumentTemplate', 'OfferLetterTemplate', 'EmailTemplate', 'EmployeeDocument', 'EmailLog',
    'MoneyTransaction'
]


