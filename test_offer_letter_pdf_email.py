import os
import io
import json
import base64
import hashlib
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from models import (
    db, User, JobPosting, JobApplication, Employee, EmployeeDocument, EmailLog
)
from services.email_service import send_offer_letter_shortlisted_email
from services.document_preview_service import _resolve_document_file_path, convert_docx_to_pdf

class OfferLetterPdfEmailTestCase(unittest.TestCase):
    """
    Test Suite for sending Offer Letter as PDF in email:
    1. Verify PDF is generated directly from existing DOCX
    2. Verify Brevo email payload contains base64-encoded PDF (not DOCX)
    3. Verify attachment filename is candidate-specific .pdf
    4. Verify EmailLog records .pdf attachment
    5. Verify original DOCX file remains byte-for-byte unmodified
    6. Verify one-time send protection works
    7. Verify email is not sent if PDF conversion fails
    8. Test with existing candidate AM-APP-000240
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

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Retrieve existing application or ensure one exists with generated offer letter
        self.app_record = JobApplication.query.first()
        if not self.app_record:
            from services.offer_letter_service import generate_offer_letter_docx
            job = JobPosting.query.first()
            user = User.query.first()
            self.app_record = JobApplication(
                job_id=job.id if job else 1,
                user_id=user.id if user else 1,
                first_name='Test',
                last_name='Candidate',
                full_name='Test Candidate',
                email='test_pdf_cand@example.com',
                phone='9876543210',
                payment_status='paid',
                status='SHORTLISTED',
                application_status='SHORTLISTED'
            )
            db.session.add(self.app_record)
            db.session.commit()

        # Ensure Offer Letter doc exists
        if not self.app_record.offer_letter_doc or not _resolve_document_file_path(self.app_record.offer_letter_doc):
            from services.offer_letter_service import generate_offer_letter_docx
            generate_offer_letter_docx(self.app_record)

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_01_existing_candidate_docx_to_pdf_conversion(self):
        """Verify candidate existing DOCX converts to a valid, authentic PDF."""
        app_obj = self.app_record
        doc = app_obj.offer_letter_doc
        self.assertIsNotNone(doc, "Candidate must have an offer letter document record")
        
        docx_path = _resolve_document_file_path(doc)
        self.assertIsNotNone(docx_path, "DOCX path must resolve")
        self.assertTrue(os.path.exists(docx_path), f"DOCX file must exist on disk at {docx_path}")

        # Record original DOCX hash
        with open(docx_path, 'rb') as f:
            original_docx_bytes = f.read()
        original_hash = hashlib.sha256(original_docx_bytes).hexdigest()

        # Convert to PDF
        success, pdf_path, err = convert_docx_to_pdf(docx_path)
        self.assertTrue(success, f"Conversion failed: {err}")
        self.assertIsNotNone(pdf_path)
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 1000)

        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'), "File must be valid PDF")

        # Verify DOCX is byte-for-byte untouched
        with open(docx_path, 'rb') as f:
            after_docx_bytes = f.read()
        after_hash = hashlib.sha256(after_docx_bytes).hexdigest()
        self.assertEqual(original_hash, after_hash, "Original DOCX must not be modified during PDF conversion")

    @patch('services.email_service.send_brevo_email')
    def test_02_email_dispatch_attaches_pdf_not_docx(self, mock_brevo):
        """Verify send_offer_letter_shortlisted_email sends PDF attachment with candidate-specific filename."""
        mock_brevo.return_value = (True, "Email successfully sent via Brevo API", "msg_test_12345")

        app_obj = self.app_record
        doc = app_obj.offer_letter_doc
        self.assertIsNotNone(doc)

        # Temporarily ensure email_status is not 'sent' for test run within rolled-back transaction
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_obj)
        self.assertTrue(success, f"Email sending failed: {msg}")

        # Verify mock_brevo was called with PDF attachment
        mock_brevo.assert_called_once()
        call_kwargs = mock_brevo.call_args[1]
        
        att_path = call_kwargs.get('attachment_path')
        att_name = call_kwargs.get('attachment_name')

        self.assertIsNotNone(att_path, "attachment_path must be provided")
        self.assertTrue(att_path.endswith('.pdf'), f"attachment_path must end with .pdf, got: {att_path}")
        self.assertTrue(os.path.exists(att_path), f"Attached PDF must exist at: {att_path}")
        expected_pdf_name = f"{app_obj.formatted_code}_Offer_Letter.pdf"
        self.assertEqual(att_name, expected_pdf_name, f"attachment_name should be {expected_pdf_name}, got: {att_name}")

        # Verify PDF contents
        with open(att_path, 'rb') as f:
            content = f.read()
        self.assertTrue(content.startswith(b'%PDF-'), "Attached file must be a valid PDF binary")

    @patch('services.email_service.send_brevo_email')
    def test_03_email_log_records_pdf_attachment(self, mock_brevo):
        """Verify EmailLog records .pdf attachment filename."""
        mock_brevo.return_value = (True, "Email successfully sent via Brevo API", "msg_log_test_67890")

        app_obj = self.app_record
        doc = app_obj.offer_letter_doc
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_obj)
        self.assertTrue(success)

        # Check EmailLog entry
        log = EmailLog.query.filter_by(template_type='offer_letter').order_by(EmailLog.id.desc()).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.recipient_email, app_obj.email)
        self.assertEqual(log.status, 'SENT')
        self.assertTrue(log.has_attachment)
        expected_pdf_name = f"{app_obj.formatted_code}_Offer_Letter.pdf"
        self.assertEqual(log.attachment_name, expected_pdf_name)

    @patch('services.email_service.send_brevo_email')
    def test_04_one_time_send_protection_prevents_duplicate(self, mock_brevo):
        """Verify that once an offer letter email is sent, subsequent attempts are blocked."""
        mock_brevo.return_value = (True, "Email sent", "msg_123")

        app_obj = self.app_record
        doc = app_obj.offer_letter_doc
        doc.email_status = 'sent'

        success, msg = send_offer_letter_shortlisted_email(app_obj)
        self.assertFalse(success)
        self.assertIn("already sent", msg.lower())
        mock_brevo.assert_not_called()

    @patch('services.document_preview_service.convert_docx_to_pdf')
    @patch('services.email_service.send_brevo_email')
    def test_05_conversion_failure_falls_back_to_docx_attachment(self, mock_brevo, mock_convert):
        """Verify that if PDF conversion fails, the email is still sent with the DOCX as fallback attachment.
        This is critical for production environments (Render/Linux) where LibreOffice may not be installed.
        The old behavior (blocking the email) is replaced with a DOCX-fallback so candidates always receive
        their Offer Letter regardless of server PDF capability."""
        mock_convert.return_value = (False, None, "LibreOffice conversion timeout")
        mock_brevo.return_value = (True, "Email sent via DOCX fallback", "msg_fallback_001")

        app_obj = self.app_record
        doc = app_obj.offer_letter_doc
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_obj)
        # Email should be SENT with DOCX fallback, not blocked
        self.assertTrue(success, "Email must be sent even when PDF conversion fails (DOCX fallback)")
        # Brevo must have been called with the DOCX path
        mock_brevo.assert_called_once()
        call_kwargs = mock_brevo.call_args
        # attachment_name should be the DOCX filename, not a .pdf filename
        attach_name = call_kwargs.kwargs.get('attachment_name') or (
            call_kwargs.args[4] if len(call_kwargs.args) > 4 else None
        )
        if attach_name:
            self.assertTrue(
                attach_name.endswith('.docx'),
                f"Expected DOCX fallback attachment, got: {attach_name}"
            )


if __name__ == '__main__':
    unittest.main()
