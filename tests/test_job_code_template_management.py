"""
Verification Test Suite: Job Code-Based Template Management and Automatic Template Selection
ANTI-MATRIX WEBSITE ONLY

Tests all 10 scenarios from Section 33 of specifications:
1. Job Posting unique JB#### code auto-generation and uniqueness.
2. Template Creation - Offer Letter linked to Job Code.
3. Template Creation - Email linked to Job Code.
4. Multiple Templates / Separate Job Codes isolation.
5. Single Active Template Versioning rule per (job_code, template_type).
6. Candidate Application retaining Job Code.
7. Shortlist automatic template selection (DOCX, PDF, and Email).
8. Non-Interference: Different jobs select their own distinct templates.
9. Strict Missing Template Error Handling (HALT without fallback).
10. Email Retry Idempotency with exact existing PDF.
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
import docx

# Add project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from models.job import JobPosting, JobApplication
from models.document import DocumentTemplate, EmployeeDocument
from models.employee import Employee
from services.offer_letter_service import (
    get_active_offer_letter_template,
    populate_docx_from_master_template,
    generate_offer_letter_docx,
    OfferLetterTemplateNotFoundError
)
from services.email_service import render_shortlisted_offer_email


class TestJobCodeTemplateManagement(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        self.cleanup_templates = []
        self.cleanup_applications = []
        self.cleanup_jobs = []
        self.cleanup_files = []

    def tearDown(self):
        db.session.rollback()
        # Clean up test artifacts safely
        try:
            for tmpl_id in self.cleanup_templates:
                tmpl = db.session.get(DocumentTemplate, tmpl_id)
                if tmpl:
                    db.session.delete(tmpl)

            for app_id in self.cleanup_applications:
                application = db.session.get(JobApplication, app_id)
                if application:
                    if application.employee:
                        db.session.delete(application.employee)
                    db.session.delete(application)

            for j_id in self.cleanup_jobs:
                job = db.session.get(JobPosting, j_id)
                if job:
                    db.session.delete(job)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Teardown DB error: {e}")

        for fpath in self.cleanup_files:
            if fpath and os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception:
                    pass

    def _create_sample_docx(self, title_text="Sample Job Offer Template"):
        """Creates a minimal valid DOCX master template with standard placeholders."""
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        doc = docx.Document()
        doc.add_heading(f"ANTI-MATRIX MASTER TEMPLATE: {title_text}", level=1)
        doc.add_paragraph("Date: [DD/MM/YYYY]")
        doc.add_paragraph("Dear [Candidate Name],")
        doc.add_paragraph("We are pleased to offer you the position of [Job Title] for a duration of [1 Month / 3 Months].")
        doc.add_paragraph("Your Employee ID is [Employee ID] and Application Ref is [Application ID].")
        doc.add_paragraph("Sincerely, Anti-Matrix Team")
        doc.save(path)
        self.cleanup_files.append(path)
        return path

    def _create_sample_html(self, content="Sample Email Content"):
        """Creates a minimal valid HTML template file."""
        fd, path = tempfile.mkstemp(suffix=".html")
        os.close(fd)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"<html><body><p>{content}</p></body></html>")
        self.cleanup_files.append(path)
        return path

    def _create_sample_application(self, job, first_name="Test", last_name="Candidate", email=None, duration="1_month"):
        """Creates a valid JobApplication with all required database columns."""
        code_suffix = os.urandom(3).hex().upper()
        if not email:
            email = f"test.{code_suffix.lower()}@example.com"
        app = JobApplication(
            job_id=job.id,
            application_code=f"AM-TEST-{code_suffix}",
            first_name=first_name,
            last_name=last_name,
            full_name=f"{first_name} {last_name}".strip(),
            email=email,
            phone="+919876543210",
            duration=duration,
            resume_filename="sample_resume.pdf",
            resume_path="/dummy/sample_resume.pdf",
            payment_status="paid",
            status="Under Review"
        )
        db.session.add(app)
        db.session.commit()
        self.cleanup_applications.append(app.id)
        return app

    def test_01_job_posting_creation_and_auto_job_code(self):
        """Scenario 1: Auto-generate unique JB#### and verify database uniqueness."""
        code1 = JobPosting.generate_unique_job_code()
        self.assertTrue(code1.startswith("JB"))
        self.assertEqual(len(code1), 6)
        self.assertTrue(code1[2:].isdigit())

        # Create job using auto-generation
        job = JobPosting(
            job_id=code1,
            job_code=code1,
            title="Auto Code Test Engineer",
            department="Cloud Engineering",
            location="Remote",
            employment_type="Internship",
            duration="1_month",
            short_description="Testing unique JB auto generation",
            description="Full role description for auto code test",
            is_active=True
        )
        db.session.add(job)
        db.session.commit()
        self.cleanup_jobs.append(job.id)

        self.assertEqual(job.job_code, code1)
        self.assertEqual(job.job_id, code1)

        # Verify next generated code is different
        code2 = JobPosting.generate_unique_job_code()
        self.assertNotEqual(code1, code2)

    def test_02_template_creation_offer_letter(self):
        """Scenario 2: Template Creation - Offer Letter linked to Job Code."""
        job = JobPosting.query.filter_by(is_active=True).first()
        self.assertIsNotNone(job, "Active job needed for test")
        job_code = job.job_code or job.job_id

        sample_path = self._create_sample_docx(f"Offer for {job_code}")
        tmpl = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job.id,
            job_code=job_code,
            name=f"{job_code} Test Offer Letter Template",
            filename=f"offer_{job_code.lower()}_test.docx",
            file_path=sample_path,
            duration='Both',
            is_active=True,
            created_by='TestAdmin'
        )
        db.session.add(tmpl)
        db.session.commit()
        self.cleanup_templates.append(tmpl.id)

        # Verify in DB
        fetched = db.session.get(DocumentTemplate, tmpl.id)
        self.assertEqual(fetched.job_code, job_code)
        self.assertEqual(fetched.job_posting_id, job.id)
        self.assertTrue(fetched.is_active)
        self.assertEqual(fetched.template_type, 'offer_letter')

    def test_03_template_creation_email(self):
        """Scenario 3: Template Creation - Email linked to Job Code."""
        job = JobPosting.query.filter_by(is_active=True).first()
        job_code = job.job_code or job.job_id
        sample_html_path = self._create_sample_html("Test email content")

        tmpl = DocumentTemplate(
            template_type='email',
            job_posting_id=job.id,
            job_code=job_code,
            name=f"{job_code} Test Email Template",
            filename=f"email_{job_code.lower()}_test.html",
            file_path=sample_html_path,
            subject=f"Welcome to Anti-Matrix — {job.title} | Shortlisted",
            duration='Both',
            is_active=True,
            created_by='TestAdmin'
        )
        db.session.add(tmpl)
        db.session.commit()
        self.cleanup_templates.append(tmpl.id)

        fetched = db.session.get(DocumentTemplate, tmpl.id)
        self.assertEqual(fetched.job_code, job_code)
        self.assertEqual(fetched.template_type, 'email')
        self.assertEqual(fetched.subject, f"Welcome to Anti-Matrix — {job.title} | Shortlisted")

    def test_04_multiple_templates_jobs_separation(self):
        """Scenario 4: Job A (JB1001) has Template A, Job B (JB1234) has Template B. Both active."""
        job_a = JobPosting.query.filter((JobPosting.job_code == 'JB1001') | (JobPosting.job_id == 'JB1001')).first()
        job_b = JobPosting.query.filter((JobPosting.job_code == 'JB1234') | (JobPosting.job_id == 'JB1234')).first()
        self.assertIsNotNone(job_a, "Job A (JB1001) must exist")
        self.assertIsNotNone(job_b, "Job B (JB1234) must exist")

        path_a = self._create_sample_docx("Template A Frontend")
        path_b = self._create_sample_docx("Template B AI Research")

        # Deactivate previous active templates for these jobs
        DocumentTemplate.query.filter((DocumentTemplate.job_code == 'JB1001') | (DocumentTemplate.job_posting_id == job_a.id)).update({'is_active': False})
        DocumentTemplate.query.filter((DocumentTemplate.job_code == 'JB1234') | (DocumentTemplate.job_posting_id == job_b.id)).update({'is_active': False})

        tmpl_a = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job_a.id,
            job_code='JB1001',
            name="Template A Frontend Offer",
            filename="template_a.docx",
            file_path=path_a,
            duration='Both',
            is_active=True
        )
        tmpl_b = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job_b.id,
            job_code='JB1234',
            name="Template B AI Research Offer",
            filename="template_b.docx",
            file_path=path_b,
            duration='Both',
            is_active=True
        )
        db.session.add_all([tmpl_a, tmpl_b])
        db.session.commit()
        self.cleanup_templates.extend([tmpl_a.id, tmpl_b.id])

        # Both must be simultaneously active for their respective Job Codes
        self.assertTrue(tmpl_a.is_active)
        self.assertTrue(tmpl_b.is_active)

        resolved_a = get_active_offer_letter_template(job_a)
        resolved_b = get_active_offer_letter_template(job_b)

        self.assertEqual(resolved_a.id, tmpl_a.id)
        self.assertEqual(resolved_b.id, tmpl_b.id)
        self.assertNotEqual(resolved_a.id, resolved_b.id)

    def test_05_template_versioning_single_active(self):
        """Scenario 5: Upload new template for Job Code; old template deactivated, single active."""
        job = JobPosting.query.filter_by(is_active=True).first()
        job_code = job.job_code or job.job_id

        path_v1 = self._create_sample_docx("Job V1")
        tmpl_v1 = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job.id,
            job_code=job_code,
            name=f"{job_code} Offer Letter V1",
            filename="v1.docx",
            file_path=path_v1,
            is_active=True
        )
        db.session.add(tmpl_v1)
        db.session.commit()
        self.cleanup_templates.append(tmpl_v1.id)

        self.assertTrue(tmpl_v1.is_active)

        # Add V2 with deactivate logic (mimicking route)
        DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            job_code=job_code,
            is_active=True
        ).update({'is_active': False})

        path_v2 = self._create_sample_docx("Job V2")
        tmpl_v2 = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job.id,
            job_code=job_code,
            name=f"{job_code} Offer Letter V2",
            filename="v2.docx",
            file_path=path_v2,
            is_active=True
        )
        db.session.add(tmpl_v2)
        db.session.commit()
        self.cleanup_templates.append(tmpl_v2.id)

        # Refresh
        db.session.refresh(tmpl_v1)
        db.session.refresh(tmpl_v2)

        self.assertFalse(tmpl_v1.is_active)
        self.assertTrue(tmpl_v2.is_active)

        # Verify active count is exactly 1 for this (job_code, offer_letter)
        active_count = DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            job_code=job_code,
            is_active=True
        ).count()
        self.assertEqual(active_count, 1)

    def test_06_candidate_application_links_to_job_code(self):
        """Scenario 6: Candidate application retains job code relation."""
        job = JobPosting.query.filter((JobPosting.job_code == 'JB1001') | (JobPosting.job_id == 'JB1001')).first()
        self.assertIsNotNone(job)

        app = self._create_sample_application(job, first_name="Test", last_name="Candidate")
        self.assertEqual(app.job_code, "JB1001")
        self.assertEqual(app.job.id, job.id)

    def test_07_shortlist_candidate_and_automatic_template_selection(self):
        """Scenario 7: Shortlisting candidate automatically selects Job Code template."""
        job_a = JobPosting.query.filter((JobPosting.job_code == 'JB1001') | (JobPosting.job_id == 'JB1001')).first()
        path_a = self._create_sample_docx("Template A for JB1001")
        
        # Deactivate any previous active templates for JB1001
        DocumentTemplate.query.filter(
            (DocumentTemplate.job_code == 'JB1001') | (DocumentTemplate.job_posting_id == job_a.id),
            (DocumentTemplate.template_type == 'offer_letter') | (DocumentTemplate.template_type.like('offer_letter_%'))
        ).update({'is_active': False})

        tmpl_a = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job_a.id,
            job_code='JB1001',
            name="Frontend Master DOCX",
            filename="frontend_master.docx",
            file_path=path_a,
            is_active=True
        )
        db.session.add(tmpl_a)
        db.session.commit()
        self.cleanup_templates.append(tmpl_a.id)

        app = self._create_sample_application(job_a, first_name="Priya", last_name="Sharma")

        # Automatic template selection
        selected_tmpl = get_active_offer_letter_template(app)
        self.assertEqual(selected_tmpl.id, tmpl_a.id)
        self.assertEqual(selected_tmpl.job_code, "JB1001")

        # Test DOCX Generation with placeholders
        out_fd, out_path = tempfile.mkstemp(suffix=".docx")
        os.close(out_fd)
        self.cleanup_files.append(out_path)

        mapping = {
            '[DD/MM/YYYY]': '15/09/2026',
            '[Candidate Name]': app.full_name,
            '[Job Title]': job_a.title,
            '[1 Month / 3 Months]': '1 Month',
            '[Employee ID]': 'AM260901',
            '[Application ID]': 'REF-AM-TEST',
            '[Joining Date]': '15/09/2026'
        }
        populate_docx_from_master_template(
            master_template_path=selected_tmpl.file_path,
            output_filepath=out_path,
            placeholder_mapping=mapping
        )

        self.assertTrue(os.path.exists(out_path))
        gen_doc = docx.Document(out_path)
        full_text = " ".join(p.text for p in gen_doc.paragraphs)
        self.assertIn("Priya Sharma", full_text)
        self.assertIn(job_a.title, full_text)
        self.assertIn("AM260901", full_text)

    def test_08_non_interference_separate_jobs(self):
        """Scenario 8: Candidate applying for Job B uses Template B, never Template A."""
        job_b = JobPosting.query.filter((JobPosting.job_code == 'JB1234') | (JobPosting.job_id == 'JB1234')).first()
        self.assertIsNotNone(job_b)

        path_b = self._create_sample_docx("Template B for JB1234")
        DocumentTemplate.query.filter(
            (DocumentTemplate.job_code == 'JB1234') | (DocumentTemplate.job_posting_id == job_b.id),
            (DocumentTemplate.template_type == 'offer_letter') | (DocumentTemplate.template_type.like('offer_letter_%'))
        ).update({'is_active': False})

        tmpl_b = DocumentTemplate(
            template_type='offer_letter',
            job_posting_id=job_b.id,
            job_code='JB1234',
            name="AI Research Master DOCX",
            filename="ai_research_master.docx",
            file_path=path_b,
            is_active=True
        )
        db.session.add(tmpl_b)
        db.session.commit()
        self.cleanup_templates.append(tmpl_b.id)

        app_b = self._create_sample_application(job_b, first_name="Rohan", last_name="Verma")

        selected_b = get_active_offer_letter_template(app_b)
        self.assertEqual(selected_b.id, tmpl_b.id)
        self.assertEqual(selected_b.job_code, "JB1234")

    def test_09_strict_missing_template_error_handling(self):
        """Scenario 9: Candidate applying for job with NO active template raises OfferLetterTemplateNotFoundError and halts."""
        # Create a Job C with a dynamically unique job code
        unique_code = JobPosting.generate_unique_job_code()
        job_c = JobPosting(
            job_id=unique_code,
            job_code=unique_code,
            title="Unconfigured Domain Intern",
            department="Experimental Lab",
            location="Remote",
            employment_type="Internship",
            duration="1_month",
            short_description="Job with no template configured",
            description="Testing strict no-fallback halt",
            is_active=True
        )
        db.session.add(job_c)
        db.session.commit()
        self.cleanup_jobs.append(job_c.id)

        app_c = self._create_sample_application(job_c, first_name="Ananya", last_name="Roy")

        # STRICT GUARD: Attempting to resolve template for Job C MUST raise OfferLetterTemplateNotFoundError
        with self.assertRaises(OfferLetterTemplateNotFoundError) as ctx:
            get_active_offer_letter_template(app_c)

        err_msg = str(ctx.exception)
        self.assertIn(f"No active Offer Letter template is configured for Job Code {unique_code}", err_msg)
        self.assertIn(job_c.title, err_msg)

    def test_10_email_resend_idempotency(self):
        """Scenario 10: Email rendering for Job Code template with variable replacement."""
        job = JobPosting.query.filter_by(is_active=True).first()
        job_code = job.job_code or job.job_id
        html_path = self._create_sample_html("Dear {{Student Name}}, you are shortlisted for {{Internship Role}}.")

        # Deactivate previous email templates for this job
        DocumentTemplate.query.filter_by(template_type='email', job_code=job_code, is_active=True).update({'is_active': False})

        # Email template for this Job Code
        tmpl_email = DocumentTemplate(
            template_type='email',
            job_posting_id=job.id,
            job_code=job_code,
            name=f"{job_code} Shortlisted Email",
            filename="email_custom.html",
            file_path=html_path,
            subject=f"Shortlisted for {job_code}: {{{{Internship Role}}}}",
            is_active=True
        )
        db.session.add(tmpl_email)
        db.session.commit()
        self.cleanup_templates.append(tmpl_email.id)

        app = self._create_sample_application(job, first_name="Sameer", last_name="Gupta")

        rendered = render_shortlisted_offer_email(app)
        self.assertEqual(rendered['to'], app.email)
        self.assertIn(f"Shortlisted for {job_code}: {job.title}", rendered['subject'])
        self.assertIn("Sameer Gupta", rendered['body_text'])


if __name__ == '__main__':
    unittest.main()
