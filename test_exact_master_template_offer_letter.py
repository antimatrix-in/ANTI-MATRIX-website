import os
import zipfile
import unittest
from unittest.mock import patch
import docx

from app import create_app
from models import db, User, JobApplication, JobPosting, Employee, DocumentTemplate, EmployeeDocument
from services.offer_letter_service import generate_offer_letter_docx, get_active_offer_letter_template


class ExactMasterTemplateOfferLetterTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Admin user
        self.admin = User.query.filter_by(role='admin').first()
        if not self.admin:
            self.admin = User(
                username='test_admin_exact',
                email='admin_exact@example.com',
                role='admin'
            )
            self.admin.set_password('Admin@1234')
            db.session.add(self.admin)
            db.session.commit()

        self.job = JobPosting.query.first()
        if not self.job:
            self.job = JobPosting(
                title='AI & ML Intern',
                department='Engineering',
                location='Chennai',
                duration='1_month',
                short_description='AI & ML Internship',
                description='Artificial Intelligence and Machine Learning Internship',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

        self.candidate_418 = JobApplication.query.get(418)
        if not self.candidate_418:
            self.candidate_418 = JobApplication.query.filter_by(formatted_code='AM-APP-000418').first()

    def tearDown(self):
        self.app_context.pop()

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

    def test_01_master_template_exact_file_and_elements_preserved(self):
        """Verify the active master template file has all official design elements (watermark, seal, MSME, border)."""
        tmpl = get_active_offer_letter_template('AI_ML')
        self.assertTrue(os.path.exists(tmpl.file_path), f"Template file does not exist at {tmpl.file_path}")

        with zipfile.ZipFile(tmpl.file_path, 'r') as z:
            names = z.namelist()
            # Media files must exist (images, seals, logos)
            media = [n for n in names if n.startswith('word/media/')]
            self.assertGreaterEqual(len(media), 8, "Master template must contain header logo, seal, MSME, and icons")
            # Headers and footers
            self.assertTrue(any('header' in n for n in names), "Master must contain header")
            self.assertTrue(any('footer' in n for n in names), "Master must contain footer")

    def test_02_generation_for_am_app_000418_replaces_only_dynamic_fields(self):
        """Generate Offer Letter for AM-APP-000418 and verify all dynamic fields are correctly populated."""
        emp_doc, docx_path = generate_offer_letter_docx(self.candidate_418, force_regenerate=True)
        self.assertTrue(os.path.exists(docx_path))
        self.assertEqual(emp_doc.file_name, 'AM-APP-000418_Offer_Letter.docx')

        doc = docx.Document(docx_path)
        body_text = "\n".join(p.text for p in doc.paragraphs)

        # Dynamic fields replaced
        self.assertIn("Dear Praveen R,", body_text)
        self.assertIn("Ref.: AM-APP-000418", body_text)
        self.assertIn("position of AI & ML Intern at Anti-Matrix.", body_text)
        self.assertIn("1 Month", body_text)
        self.assertIn("Immediate / As mutually agreed", body_text)

        # Placeholders MUST NOT be present
        self.assertNotIn("[Candidate Name]", body_text)
        self.assertNotIn("[Reference Number]", body_text)
        self.assertNotIn("[1 Month / 3 Months]", body_text)
        self.assertNotIn("[Joining Date]", body_text)
        self.assertNotIn("[DD/MM/YYYY]", body_text)

        # Static master text preserved
        self.assertIn("Congratulations!", body_text)
        self.assertIn("real-time project", body_text)
        self.assertIn("stipend during the internship period.", body_text)
        self.assertIn("portal login credentials.", body_text)
        self.assertIn("Best Regards,", body_text)

        # Footer preserved
        footer_text = ""
        for s in doc.sections:
            for fp in s.footer.paragraphs:
                footer_text += fp.text
        self.assertIn("info@antimatrix.co.in", footer_text)
        self.assertIn("www.antimatrix.co.in", footer_text)

    def test_03_preview_endpoint_serves_pdf_not_html_mode(self):
        """Verify the preview endpoint serves the actual PDF and NEVER returns HTML Preview Mode."""
        generate_offer_letter_docx(self.candidate_418, force_regenerate=True)
        self.login_admin()

        res = self.client.get(f'/admin/applications/{self.candidate_418.id}/offer-letter/preview/pdf')
        # Either 200 (PDF served) or 503 (LibreOffice unavailable), but NEVER 200 with HTML preview mode!
        if res.status_code == 200:
            self.assertEqual(res.mimetype, 'application/pdf')
            self.assertTrue(res.data.startswith(b'%PDF-'))
        else:
            self.assertEqual(res.status_code, 503)

        # Crucially: "HTML Preview Mode" must NEVER appear anywhere in response
        self.assertNotIn(b'HTML Preview Mode', res.data)
        self.assertNotIn(b'Showing HTML approximation', res.data)
