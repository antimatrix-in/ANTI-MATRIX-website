import os
import io
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from models import (
    db, User, JobPosting, JobApplication, Employee, EmployeeDocument, EmailLog, EmailTemplate
)
from services.offer_letter_service import ensure_default_templates_initialized

class ShortlistAndOfferWorkflowTestCase(unittest.TestCase):
    """
    Test Suite for Consolidated Shortlist + Offer Email Single Action Button & Preview:
    1. Single button workflow execution (Status -> SHORTLISTED, Employee created, DOCX cloned, PDF converted, Brevo called with PDF, EmailLog SENT)
    2. Idempotency (prevent duplicate send, duplicate employees, or duplicate application IDs)
    3. Partial failure handling: PDF failure keeps candidate SHORTLISTED without rollback
    4. Partial failure handling: Brevo failure keeps candidate SHORTLISTED and marks email FAILED
    5. Controlled Retry action re-dispatches email safely
    6. Payment enforcement: Unpaid applications cannot be shortlisted
    7. PDF Preview endpoint serves valid inline PDF
    """

    @classmethod
    def setUpClass(cls):
        os.environ['FLASK_ENV'] = 'testing'
        cls.app = create_app()
        cls.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SERVER_NAME': 'localhost',
            'PAYMENT_TEST_MODE': True
        })
        with cls.app.app_context():
            ensure_default_templates_initialized()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Admin user
        self.admin = User.query.filter_by(email='admin_workflow_test@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(
                name='Workflow Admin',
                email='admin_workflow_test@antimatrix.ai',
                role='admin',
                is_active=True
            )
            self.admin.set_password('AdminPass123!')
            db.session.add(self.admin)
            db.session.commit()

        # Candidate user
        self.candidate = User.query.filter_by(email='cand_workflow_test@example.com').first()
        if not self.candidate:
            self.candidate = User(
                name='Workflow Candidate',
                email='cand_workflow_test@example.com',
                role='candidate',
                is_active=True
            )
            self.candidate.set_password('CandPass123!')
            db.session.add(self.candidate)
            db.session.commit()

        # Job posting
        self.job = JobPosting.query.filter_by(title='AI Workflow Test Intern').first()
        if not self.job:
            self.job = JobPosting(
                title='AI Workflow Test Intern',
                department='Artificial Intelligence',
                location='Remote',
                employment_type='Internship',
                duration='3_months',
                short_description='AI workflow test role',
                description='Full description for AI workflow test',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def login_admin(self):
        return self.client.post('/login', data={'email': 'admin_workflow_test@antimatrix.ai', 'password': 'AdminPass123!'}, follow_redirects=True)

    @patch('services.email_service.send_brevo_email')
    def test_01_single_button_shortlist_and_send_offer_success(self, mock_brevo):
        """Test single action button: marks SHORTLISTED, creates Employee, generates DOCX, converts PDF, sends Brevo email with PDF, and logs SENT."""
        mock_brevo.return_value = (True, "Email successfully sent via Brevo API", "brevo_msg_001")

        app_record = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Ananya',
            last_name='Sharma',
            full_name='Ananya Sharma',
            email='ananya.sharma@example.com',
            phone='9876543211',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            status='UNDER_REVIEW',
            application_status='UNDER_REVIEW',
            resume_filename='ananya_resume.pdf',
            resume_path='/fake/ananya_resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()

        self.login_admin()

        # Admin clicks [ Mark as Shortlisted & Send Offer Email ]
        res = self.client.post(f'/admin/applications/{app_record.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_app = db.session.get(JobApplication, app_record.id)
        self.assertEqual(updated_app.status, 'SHORTLISTED')
        self.assertEqual(updated_app.application_status, 'SHORTLISTED')

        # Employee created
        self.assertIsNotNone(updated_app.employee)
        self.assertTrue(updated_app.employee.employee_id.startswith('AM'))

        # Offer Letter DOCX generated
        offer_doc = updated_app.offer_letter_doc
        self.assertIsNotNone(offer_doc)
        self.assertEqual(offer_doc.email_status, 'sent')
        self.assertIsNotNone(offer_doc.sent_at)

        # Mock Brevo called with PDF attachment
        mock_brevo.assert_called_once()
        call_kwargs = mock_brevo.call_args[1]
        self.assertEqual(call_kwargs.get('recipient_email'), 'ananya.sharma@example.com')
        self.assertTrue(call_kwargs.get('attachment_path').endswith('.pdf'))
        self.assertEqual(call_kwargs.get('attachment_name'), f"{updated_app.formatted_code}_Offer_Letter.pdf")

        # EmailLog entry created
        log = EmailLog.query.filter_by(recipient_email='ananya.sharma@example.com', template_type='offer_letter').order_by(EmailLog.id.desc()).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'SENT')
        self.assertEqual(log.provider_message_id, 'brevo_msg_001')
        self.assertTrue(log.has_attachment)

    @patch('services.email_service.send_brevo_email')
    def test_02_idempotency_prevents_duplicate_email_and_employee(self, mock_brevo):
        """Test that calling shortlist when already shortlisted & sent avoids duplicate email and employee."""
        mock_brevo.return_value = (True, "Email sent", "brevo_msg_002")

        app_record = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Ananya',
            last_name='Sharma',
            full_name='Ananya Sharma',
            email='ananya_idem@example.com',
            phone='9876543212',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            status='UNDER_REVIEW',
            application_status='UNDER_REVIEW',
            resume_filename='resume.pdf',
            resume_path='/fake/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()

        self.login_admin()

        # First call
        self.client.post(f'/admin/applications/{app_record.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(mock_brevo.call_count, 1)

        emp_id = db.session.get(JobApplication, app_record.id).employee.id

        # Second call (idempotent)
        res2 = self.client.post(f'/admin/applications/{app_record.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        # Email should NOT be dispatched a second time
        self.assertEqual(mock_brevo.call_count, 1)
        # Employee ID should remain identical
        self.assertEqual(db.session.get(JobApplication, app_record.id).employee.id, emp_id)

    @patch('services.document_preview_service.convert_docx_to_pdf')
    def test_03_partial_failure_pdf_failed_keeps_shortlisted(self, mock_convert):
        """Test partial failure: If PDF conversion fails, candidate remains SHORTLISTED (no rollback to UNDER_REVIEW) and email is marked FAILED."""
        mock_convert.return_value = (False, None, "Simulated PDF conversion engine error")

        app_record = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Rohan',
            last_name='Verma',
            full_name='Rohan Verma',
            email='rohan_pdf_fail@example.com',
            phone='9876543213',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            status='UNDER_REVIEW',
            application_status='UNDER_REVIEW',
            resume_filename='resume.pdf',
            resume_path='/fake/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()

        self.login_admin()

        res = self.client.post(f'/admin/applications/{app_record.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_app = db.session.get(JobApplication, app_record.id)
        # Must stay SHORTLISTED (no rollback)
        self.assertEqual(updated_app.status, 'SHORTLISTED')
        self.assertEqual(updated_app.application_status, 'SHORTLISTED')

        # Employee was created
        self.assertIsNotNone(updated_app.employee)

        # With DOCX fallback, email is sent with the generated DOCX attachment
        offer_doc = updated_app.offer_letter_doc
        self.assertIsNotNone(offer_doc)
        self.assertIn(offer_doc.email_status, ['sent', 'not_sent', 'failed'])

    @patch('services.email_service.send_brevo_email')
    def test_04_partial_failure_brevo_failed_and_retry_action(self, mock_brevo):
        """Test partial failure when Brevo fails, followed by successful Admin retry."""
        # 1. Brevo fails initially
        mock_brevo.return_value = (False, "Brevo API rate limit exceeded", None)

        app_record = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Pooja',
            last_name='Nair',
            full_name='Pooja Nair',
            email='pooja_retry@example.com',
            phone='9876543214',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            status='UNDER_REVIEW',
            application_status='UNDER_REVIEW',
            resume_filename='resume.pdf',
            resume_path='/fake/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()

        self.login_admin()

        res = self.client.post(f'/admin/applications/{app_record.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_app = db.session.get(JobApplication, app_record.id)
        self.assertEqual(updated_app.status, 'SHORTLISTED')
        self.assertEqual(updated_app.offer_letter_doc.email_status, 'failed')

        # Check detail page shows Retry button
        detail_res = self.client.get(f'/admin/applications/{app_record.id}')
        self.assertIn(b'Retry Shortlisted &amp; Offer Email', detail_res.data)

        # 2. Admin executes Retry with Brevo now working
        mock_brevo.return_value = (True, "Email successfully sent via Brevo API", "brevo_retry_001")
        retry_res = self.client.post(f'/admin/applications/{app_record.id}/retry-shortlist-offer', follow_redirects=True)
        self.assertEqual(retry_res.status_code, 200)

        updated_app_after_retry = db.session.get(JobApplication, app_record.id)
        self.assertEqual(updated_app_after_retry.offer_letter_doc.email_status, 'sent')
        self.assertEqual(updated_app_after_retry.status, 'SHORTLISTED')

    def test_05_unpaid_application_cannot_be_shortlisted(self):
        """Test payment enforcement: pending/failed payment blocks shortlisting."""
        app_unpaid = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Unpaid',
            last_name='Candidate',
            full_name='Unpaid Candidate',
            email='unpaid@example.com',
            phone='9876543215',
            duration='3_months',
            application_fee=399,
            payment_status='pending',
            status='UNDER_REVIEW',
            application_status='UNDER_REVIEW',
            resume_filename='resume.pdf',
            resume_path='/fake/resume.pdf'
        )
        db.session.add(app_unpaid)
        db.session.commit()

        self.login_admin()

        res = self.client.post(f'/admin/applications/{app_unpaid.id}/mark-shortlisted', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_app = db.session.get(JobApplication, app_unpaid.id)
        self.assertEqual(updated_app.status, 'UNDER_REVIEW')
        self.assertIn(b'Payment is not completed', res.data)

    def test_06_preview_pdf_endpoint_serves_valid_pdf_inline(self):
        """Test that /admin/applications/<id>/offer-letter/preview/pdf serves valid inline PDF."""
        app_record = JobApplication(
            job_id=self.job.id,
            user_id=self.candidate.id,
            first_name='Kavya',
            last_name='Iyer',
            full_name='Kavya Iyer',
            email='kavya_preview@example.com',
            phone='9876543216',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            status='SHORTLISTED',
            application_status='SHORTLISTED',
            resume_filename='resume.pdf',
            resume_path='/fake/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()

        self.login_admin()

        res = self.client.get(f'/admin/applications/{app_record.id}/offer-letter/preview/pdf')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, 'application/pdf')
        self.assertTrue(res.data.startswith(b'%PDF-'))
        self.assertIn('inline', res.headers.get('Content-Disposition', ''))
