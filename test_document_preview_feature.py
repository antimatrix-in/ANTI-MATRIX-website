import os
import sys
import io
import uuid
import hashlib
import unittest

from app import create_app
from models import (
    db, User, JobPosting, JobApplication, Employee, EmployeeDocument, DocumentTemplate
)
from services.offer_letter_service import generate_offer_letter_docx
from services.document_preview_service import get_application_offer_letter_preview, convert_docx_to_pdf

class DocumentPreviewFeatureTestCase(unittest.TestCase):
    """
    Comprehensive test suite for the High-Fidelity DOCX -> PDF Preview feature:
    TEST 1: Show Preview button visible when generated Offer Letter exists
    TEST 2: Preview PDF endpoint converts and serves valid application/pdf binary inline
    TEST 3: Preview JSON endpoint returns metadata and valid pdf_url
    TEST 4: Download endpoint still returns authentic DOCX as attachment
    TEST 5: Admin access is strictly enforced (unauthorized / non-admin receives 302/403)
    TEST 6: Original DOCX file remains byte-for-byte untouched after multiple preview calls
    TEST 7: Non-existent application / missing document returns clean error / 404
    TEST 8: PDF cache is created and subsequent requests reuse cached PDF
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
            from services.offer_letter_service import ensure_default_templates_initialized
            ensure_default_templates_initialized()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Admin user
        self.admin = User.query.filter_by(email='admin_preview_test@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(
                name='Preview Admin',
                email='admin_preview_test@antimatrix.ai',
                role='admin',
                is_active=True
            )
            self.admin.set_password('AdminPass123!')
            db.session.add(self.admin)
            db.session.commit()

        # Normal candidate user
        self.candidate = User.query.filter_by(email='regular_cand_preview@example.com').first()
        if not self.candidate:
            self.candidate = User(
                name='Regular Candidate',
                email='regular_cand_preview@example.com',
                role='candidate',
                is_active=True
            )
            self.candidate.set_password('CandPass123!')
            db.session.add(self.candidate)
            db.session.commit()

        # Job posting
        self.job = JobPosting.query.filter_by(title='AI Preview Test Intern').first()
        if not self.job:
            self.job = JobPosting(
                title='AI Preview Test Intern',
                department='Artificial Intelligence',
                location='Remote',
                employment_type='Internship',
                duration='3_months',
                short_description='AI preview test role',
                description='Full description for AI preview test',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def login_admin(self):
        return self.client.post('/login', data={'email': 'admin_preview_test@antimatrix.ai', 'password': 'AdminPass123!'}, follow_redirects=True)

    def login_candidate(self):
        return self.client.post('/login', data={'email': 'regular_cand_preview@example.com', 'password': 'CandPass123!'}, follow_redirects=True)

    def logout_user(self):
        return self.client.get('/logout', follow_redirects=True)

    def _create_test_app_with_offer_letter(self):
        uid = uuid.uuid4().hex[:6]
        app_rec = JobApplication(
            job_id=self.job.id,
            full_name=f'Aarav Sharma {uid}',
            first_name='Aarav',
            last_name='Sharma',
            email=f'aarav_{uid}@example.com',
            phone='+91 98765 00001',
            payment_status='paid',
            status='SHORTLISTED',
            duration='3_months',
            resume_filename='test_resume.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], f'res_{uid}.pdf')
        )
        db.session.add(app_rec)
        db.session.flush()
        app_rec.application_code = f"AM-APP-{app_rec.id:06d}"

        # Generate offer letter
        doc_record, err = generate_offer_letter_docx(app_rec)
        db.session.commit()
        return app_rec, doc_record

    def test_01_preview_button_rendered_when_offer_letter_exists(self):
        """TEST 1: Verify Show Preview button appears in application detail page when offer letter exists."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()
        self.assertIsNotNone(doc_record)

        self.login_admin()
        res = self.client.get(f'/admin/applications/{app_rec.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Show Preview', res.data)
        self.assertIn(b'Download DOCX', res.data)
        self.assertIn(b'openOfferLetterPreview', res.data)
        self.logout_user()

    def test_02_preview_pdf_endpoint_serves_valid_pdf(self):
        """TEST 2: Verify /preview/pdf endpoint serves valid application/pdf binary without forcing attachment."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()

        self.login_admin()

        # Fetch PDF file
        res_pdf = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview/pdf')
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf.mimetype, 'application/pdf')

        # Must NOT force attachment download header
        cd_header = res_pdf.headers.get('Content-Disposition', '')
        self.assertNotIn('attachment', cd_header)

        # PDF magic bytes %PDF-
        self.assertTrue(res_pdf.data.startswith(b'%PDF-'))
        self.assertGreater(len(res_pdf.data), 1000)

        self.logout_user()

    def test_03_preview_json_metadata_endpoint(self):
        """TEST 3: Verify preview endpoint returns JSON metadata with pdf_url and candidate details."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()

        self.login_admin()
        res_json = self.client.get(
            f'/admin/applications/{app_rec.id}/offer-letter/preview?format=json',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(res_json.status_code, 200)
        data = res_json.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('Aarav Sharma', data.get('candidate_name', ''))
        self.assertIn(app_rec.application_code, data.get('application_code', ''))
        self.assertEqual(data.get('pdf_url'), f"/admin/applications/{app_rec.id}/offer-letter/preview/pdf")
        self.logout_user()

    def test_04_download_endpoint_continues_to_work_as_attachment(self):
        """TEST 4: Verify existing download endpoint still returns DOCX file as attachment."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()

        self.login_admin()
        res_dl = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/download')
        self.assertEqual(res_dl.status_code, 200)
        self.assertIn('attachment', res_dl.headers.get('Content-Disposition', ''))
        self.assertTrue(len(res_dl.data) > 0)
        self.logout_user()

    def test_05_admin_authorization_enforced(self):
        """TEST 5: Verify unauthenticated users and non-admin candidates cannot access preview or PDF."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()

        # 1. Unauthenticated request to preview page and PDF
        res_unauth1 = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview')
        self.assertEqual(res_unauth1.status_code, 302)  # Redirects to login

        res_unauth2 = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview/pdf')
        self.assertEqual(res_unauth2.status_code, 302)

        # 2. Candidate role (non-admin) request
        self.login_candidate()
        res_cand1 = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview')
        self.assertEqual(res_cand1.status_code, 403)  # Forbidden

        res_cand2 = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview/pdf')
        self.assertEqual(res_cand2.status_code, 403)
        self.logout_user()

    def test_06_original_docx_byte_for_byte_untouched(self):
        """TEST 6: Verify PDF conversion is strictly read-only and does not modify the DOCX file."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()
        docx_path = doc_record.file_path
        self.assertTrue(os.path.exists(docx_path))

        with open(docx_path, 'rb') as f:
            original_bytes = f.read()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        original_size = os.path.getsize(docx_path)

        self.login_admin()
        # Request PDF preview multiple times
        for _ in range(3):
            res1 = self.client.get(f'/admin/applications/{app_rec.id}/offer-letter/preview/pdf')
            self.assertEqual(res1.status_code, 200)
            self.assertEqual(res1.mimetype, 'application/pdf')

        # Re-verify DOCX bytes
        with open(docx_path, 'rb') as f:
            after_bytes = f.read()
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        after_size = os.path.getsize(docx_path)

        self.assertEqual(original_size, after_size)
        self.assertEqual(original_hash, after_hash)
        self.assertEqual(original_bytes, after_bytes)
        self.logout_user()

    def test_07_error_handling_when_no_document_exists(self):
        """TEST 7: Verify clean error message when document does not exist."""
        uid = uuid.uuid4().hex[:6]
        app_no_doc = JobApplication(
            job_id=self.job.id,
            full_name=f'No Doc Cand {uid}',
            email=f'nodoc_{uid}@example.com',
            phone='+91 99999 88888',
            payment_status='paid',
            status='APPLIED',
            resume_filename='res.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'res.pdf')
        )
        db.session.add(app_no_doc)
        db.session.flush()
        app_no_doc.application_code = f"AM-APP-{app_no_doc.id:06d}"
        db.session.commit()

        self.login_admin()
        res_err = self.client.get(
            f'/admin/applications/{app_no_doc.id}/offer-letter/preview?format=json',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(res_err.status_code, 400)
        data = res_err.get_json()
        self.assertEqual(data.get('status'), 'error')
        self.assertIn('not been generated', data.get('message', ''))

        res_pdf_err = self.client.get(f'/admin/applications/{app_no_doc.id}/offer-letter/preview/pdf')
        self.assertEqual(res_pdf_err.status_code, 404)
        self.logout_user()

    def test_08_pdf_cache_reuse(self):
        """TEST 8: Verify cached PDF is reused on subsequent requests."""
        app_rec, doc_record = self._create_test_app_with_offer_letter()
        docx_path = doc_record.file_path

        with self.app.app_context():
            success1, pdf_path1, err1 = convert_docx_to_pdf(docx_path)
            self.assertTrue(success1)
            self.assertTrue(os.path.exists(pdf_path1))

            # Second call should return identical path immediately from cache
            success2, pdf_path2, err2 = convert_docx_to_pdf(docx_path)
            self.assertTrue(success2)
            self.assertEqual(pdf_path1, pdf_path2)


if __name__ == '__main__':
    unittest.main()
