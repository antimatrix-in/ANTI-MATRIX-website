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

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_01_existing_candidate_240_docx_to_pdf_conversion(self):
        """Verify AM-APP-000240 existing DOCX converts to a valid, authentic PDF."""
        app_240 = JobApplication.query.filter_by(application_code='AM-APP-000240').first()
        self.assertIsNotNone(app_240, "AM-APP-000240 must exist in database")
        
        doc = app_240.offer_letter_doc
        self.assertIsNotNone(doc, "AM-APP-000240 must have an offer letter document record")
        
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

        app_240 = JobApplication.query.filter_by(application_code='AM-APP-000240').first()
        self.assertIsNotNone(app_240)
        doc = app_240.offer_letter_doc
        self.assertIsNotNone(doc)

        # Temporarily ensure email_status is not 'sent' for test run within rolled-back transaction
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_240)
        self.assertTrue(success, f"Email sending failed: {msg}")

        # Verify mock_brevo was called with PDF attachment
        mock_brevo.assert_called_once()
        call_kwargs = mock_brevo.call_args[1]
        
        att_path = call_kwargs.get('attachment_path')
        att_name = call_kwargs.get('attachment_name')

        self.assertIsNotNone(att_path, "attachment_path must be provided")
        self.assertTrue(att_path.endswith('.pdf'), f"attachment_path must end with .pdf, got: {att_path}")
        self.assertTrue(os.path.exists(att_path), f"Attached PDF must exist at: {att_path}")
        self.assertEqual(att_name, "AM-APP-000240_Offer_Letter.pdf", f"attachment_name should be AM-APP-000240_Offer_Letter.pdf, got: {att_name}")

        # Verify PDF contents
        with open(att_path, 'rb') as f:
            content = f.read()
        self.assertTrue(content.startswith(b'%PDF-'), "Attached file must be a valid PDF binary")

    @patch('services.email_service.send_brevo_email')
    def test_03_email_log_records_pdf_attachment(self, mock_brevo):
        """Verify EmailLog records .pdf attachment filename."""
        mock_brevo.return_value = (True, "Email successfully sent via Brevo API", "msg_log_test_67890")

        app_240 = JobApplication.query.filter_by(application_code='AM-APP-000240').first()
        doc = app_240.offer_letter_doc
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_240)
        self.assertTrue(success)

        # Check EmailLog entry
        log = EmailLog.query.filter_by(template_type='offer_letter').order_by(EmailLog.id.desc()).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.recipient_email, app_240.email)
        self.assertEqual(log.status, 'SENT')
        self.assertTrue(log.has_attachment)
        self.assertEqual(log.attachment_name, "AM-APP-000240_Offer_Letter.pdf")

    @patch('services.email_service.send_brevo_email')
    def test_04_one_time_send_protection_prevents_duplicate(self, mock_brevo):
        """Verify that once an offer letter email is sent, subsequent attempts are blocked."""
        mock_brevo.return_value = (True, "Email sent", "msg_123")

        app_240 = JobApplication.query.filter_by(application_code='AM-APP-000240').first()
        doc = app_240.offer_letter_doc
        doc.email_status = 'sent'

        success, msg = send_offer_letter_shortlisted_email(app_240)
        self.assertFalse(success)
        self.assertIn("already sent", msg.lower())
        mock_brevo.assert_not_called()

    @patch('services.document_preview_service.convert_docx_to_pdf')
    @patch('services.email_service.send_brevo_email')
    def test_05_conversion_failure_prevents_email_dispatch(self, mock_brevo, mock_convert):
        """Verify that if PDF conversion fails, no email is sent and error is reported."""
        mock_convert.return_value = (False, None, "LibreOffice conversion timeout")

        app_240 = JobApplication.query.filter_by(application_code='AM-APP-000240').first()
        doc = app_240.offer_letter_doc
        doc.email_status = 'not_sent'

        success, msg = send_offer_letter_shortlisted_email(app_240)
        self.assertFalse(success)
        self.assertIn("Offer Letter PDF could not be generated", msg)
        mock_brevo.assert_not_called()


if __name__ == '__main__':
    unittest.main()
