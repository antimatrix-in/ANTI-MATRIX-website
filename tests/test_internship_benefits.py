import os
import io
import unittest
from datetime import datetime, timezone
from app import create_app, db
from models import User, JobPosting, JobApplication, InternshipBenefit
from services.internship_benefit_service import (
    ensure_default_internship_benefits,
    get_active_internship_benefits,
    save_or_update_internship_benefit,
    DEFAULT_1_MONTH_BENEFITS,
    DEFAULT_3_MONTH_BENEFITS
)


class TestInternshipBenefitsFeature(unittest.TestCase):
    """
    Test Suite for the Admin-Managed Internship Benefits / Description feature.
    Verifies:
    1. Model JSON serialization and list parsing.
    2. Default seeding safety (only seeds if table is empty, never overwrites).
    3. Duplicate prevention when saving benefits for same duration.
    4. Admin authorization (unauthenticated redirected, candidate forbidden, admin allowed).
    5. Admin CRUD (Add, Edit, Delete, Reset).
    6. Public application page rendering (1-Month & 3-Month cards displayed above form).
    7. XSS sanitization (benefit text is escaped properly).
    8. Existing application submission flow remains 100% intact.
    """

    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = True
        self.app.config['APPLICATION_PAYMENT_MODE'] = 'MANUAL'
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-internship-benefits'

        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # 1. Create Admin Account
        self.admin = User(
            name='Test Admin',
            email='admin@antimatrix.test',
            role='admin',
            is_active=True
        )
        self.admin.set_password('AdminSecure123!')
        db.session.add(self.admin)

        # 2. Create Candidate Account
        self.candidate = User(
            name='Candidate User',
            email='candidate@antimatrix.test',
            role='candidate',
            is_active=True
        )
        self.candidate.set_password('Candidate123!')
        db.session.add(self.candidate)

        # 3. Create Active Internship Job Posting
        self.job = JobPosting(
            title='AI & ML Research Intern',
            job_code='JB8801',
            job_id='JB8801',
            department='Artificial Intelligence',
            location='Bengaluru, India (Remote Available)',
            employment_type='Internship',
            duration='1_month',
            short_description='Hands-on AI & ML internship opportunity.',
            description='Detailed research and development on agentic frameworks.',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _login_admin(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.admin.id)
            sess['_fresh'] = True

    def _login_candidate(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.candidate.id)
            sess['_fresh'] = True

    # -------------------------------------------------------------------------
    # Test 1: Model JSON serialization and helper properties
    # -------------------------------------------------------------------------
    def test_01_model_json_serialization(self):
        benefit = InternshipBenefit(
            duration='1_month',
            title='1-Month Internship',
            subtitle='Accelerated learning',
            badge_text='Fast-Track',
            is_active=True
        )
        raw_items = ['Offer Letter', 'Intern ID', 'Certificate']
        benefit.set_benefits_list(raw_items)
        db.session.add(benefit)
        db.session.commit()

        loaded = db.session.get(InternshipBenefit, benefit.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.duration_label, '1 Month')
        self.assertEqual(loaded.duration_clean, '1_month')
        self.assertEqual(loaded.items_count, 3)
        self.assertEqual(loaded.get_benefits_list(), raw_items)

    # -------------------------------------------------------------------------
    # Test 2: Safe Default Seeding
    # -------------------------------------------------------------------------
    def test_02_default_seeding_safety(self):
        ensure_default_internship_benefits()
        b1 = InternshipBenefit.query.filter_by(duration='1_month').first()
        b3 = InternshipBenefit.query.filter_by(duration='3_months').first()

        self.assertIsNotNone(b1)
        self.assertIsNotNone(b3)
        self.assertEqual(b1.items_count, len(DEFAULT_1_MONTH_BENEFITS))
        self.assertEqual(b3.items_count, len(DEFAULT_3_MONTH_BENEFITS))

        # Re-running ensure_default_internship_benefits must NOT overwrite or duplicate
        count_before = InternshipBenefit.query.count()
        ensure_default_internship_benefits()
        count_after = InternshipBenefit.query.count()
        self.assertEqual(count_before, count_after)

    # -------------------------------------------------------------------------
    # Test 3: Duplicate Prevention on Save
    # -------------------------------------------------------------------------
    def test_03_duplicate_prevention_on_save(self):
        # 1. Update existing 1_month
        b_first, is_new1 = save_or_update_internship_benefit(
            duration='1_month',
            title='Initial 1-Month',
            benefits_items=['Item Alpha', 'Item Beta']
        )
        self.assertFalse(is_new1)

        # 2. Saving again must update the same record and NOT create duplicate
        b_second, is_new2 = save_or_update_internship_benefit(
            duration='1_month',
            title='Updated 1-Month',
            benefits_items=['Item Alpha Updated', 'Item Gamma']
        )
        self.assertFalse(is_new2)
        self.assertEqual(b_first.id, b_second.id)
        self.assertEqual(b_second.title, 'Updated 1-Month')
        self.assertEqual(b_second.get_benefits_list(), ['Item Alpha Updated', 'Item Gamma'])

        # Total 1_month records in database must still be exactly 1 (no duplicates!)
        count_1m = InternshipBenefit.query.filter_by(duration='1_month').count()
        self.assertEqual(count_1m, 1)

    # -------------------------------------------------------------------------
    # Test 4: Authorization: Unauthenticated access redirects to login
    # -------------------------------------------------------------------------
    def test_04_unauthorized_access_redirects(self):
        resp = self.client.get('/admin/internship-benefits')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    # -------------------------------------------------------------------------
    # Test 5: Authorization: Regular user receives 403 Forbidden
    # -------------------------------------------------------------------------
    def test_05_regular_user_forbidden(self):
        self._login_candidate()
        resp = self.client.get('/admin/internship-benefits')
        self.assertEqual(resp.status_code, 403)

    # -------------------------------------------------------------------------
    # Test 6: Admin can view Internship Benefits listing
    # -------------------------------------------------------------------------
    def test_06_admin_can_view_listing(self):
        self._login_admin()
        resp = self.client.get('/admin/internship-benefits')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Internship Benefits Management', resp.data)
        self.assertIn(b'Add Description', resp.data)

    # -------------------------------------------------------------------------
    # Test 7: Admin Add & Edit Flow
    # -------------------------------------------------------------------------
    def test_07_admin_add_and_edit_flow(self):
        self._login_admin()

        # GET Add form
        resp_get = self.client.get('/admin/internship-benefits/add')
        self.assertEqual(resp_get.status_code, 200)
        self.assertIn(b'Internship Duration', resp_get.data)
        self.assertIn(b'Live Public Preview', resp_get.data)

        # POST Add
        post_data = {
            'duration': '3_months',
            'title': '3-Month Advanced Cohort',
            'subtitle': 'Structured project roadmap.',
            'badge_text': 'Flagship',
            'is_active': 'on',
            'benefit_items[]': [
                'Production Deployment Training',
                'Weekly Code Review',
                'Verified Experience Credential'
            ]
        }
        resp_post = self.client.post('/admin/internship-benefits/add', data=post_data, follow_redirects=True)
        self.assertEqual(resp_post.status_code, 200)
        self.assertIn(b'3-Month Advanced Cohort', resp_post.data)

        # Verify DB
        rec = InternshipBenefit.query.filter_by(duration='3_months').first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.title, '3-Month Advanced Cohort')
        self.assertIn('Production Deployment Training', rec.get_benefits_list())

        # POST Edit
        edit_data = {
            'duration': '3_months',
            'title': '3-Month Advanced Cohort (Updated)',
            'subtitle': 'Updated roadmap.',
            'badge_text': 'Flagship',
            'is_active': 'on',
            'benefit_items[]': [
                'Production Deployment Training',
                'Direct Founder Mentorship'
            ]
        }
        resp_edit = self.client.post(f'/admin/internship-benefits/{rec.id}/edit', data=edit_data, follow_redirects=True)
        self.assertEqual(resp_edit.status_code, 200)

        # Check updated
        db.session.refresh(rec)
        self.assertEqual(rec.title, '3-Month Advanced Cohort (Updated)')
        self.assertEqual(rec.items_count, 2)

    # -------------------------------------------------------------------------
    # Test 8: Public application page displays 1-Month & 3-Month cards above form
    # -------------------------------------------------------------------------
    def test_08_public_application_page_renders_benefits(self):
        ensure_default_internship_benefits()

        resp = self.client.get(f'/careers/apply/{self.job.id}')
        self.assertEqual(resp.status_code, 200)

        # 1. Benefits Section exists
        self.assertIn(b'Internship Benefits', resp.data)
        self.assertIn(b'Choose the internship duration that fits your goals', resp.data)
        self.assertIn(b'1-MONTH INTERNSHIP', resp.data)
        self.assertIn(b'3-MONTH INTERNSHIP', resp.data)

        # 2. Both cards contain benefits items
        self.assertIn(b'Digital internship offer letter', resp.data)
        self.assertIn(b'Intern employee ID', resp.data)

        # 3. Full-width responsive layout & two-column grid assertions
        self.assertIn(b'max-width: 1040px', resp.data)
        self.assertIn(b'grid-template-columns: repeat(2, minmax(0, 1fr))', resp.data)
        self.assertIn(b'gap: 24px', resp.data)
        self.assertIn(b'align-items: stretch', resp.data)
        self.assertIn(b'benefit-item-text', resp.data)

        # 4. Application form card exists below benefits
        self.assertIn(b'Internship Application Form', resp.data)
        self.assertIn(b'Full Name', resp.data)

    # -------------------------------------------------------------------------
    # Test 9: Public Security / XSS Sanitization
    # -------------------------------------------------------------------------
    def test_09_xss_protection_in_benefits(self):
        save_or_update_internship_benefit(
            duration='1_month',
            title='1-Month Safe Test',
            benefits_items=['<script>alert("XSS")</script>', '<b>Bold Item</b>']
        )

        resp = self.client.get(f'/careers/apply/{self.job.id}')
        self.assertEqual(resp.status_code, 200)

        # Must not contain unescaped executable script tags
        self.assertNotIn(b'<script>alert("XSS")</script>', resp.data)
        self.assertTrue(b'&lt;script&gt;' in resp.data or b'&quot;' in resp.data or b'&#34;' in resp.data)

    # -------------------------------------------------------------------------
    # Test 10: Existing application flow submission remains 100% intact
    # -------------------------------------------------------------------------
    def test_10_existing_manual_application_submission_still_works(self):
        fake_resume = (io.BytesIO(b"%PDF-1.4 sample resume content"), "candidate_resume.pdf")

        form_data = {
            'full_name': 'Praveen R',
            'email': 'praveen.candidate@example.com',
            'phone': '9876543210',
            'duration': '1_month',
            'college': 'Anna University',
            'resume': fake_resume
        }

        resp = self.client.post(
            f'/careers/apply/{self.job.id}',
            data=form_data,
            content_type='multipart/form-data',
            follow_redirects=False
        )

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/careers/apply/success/', resp.headers['Location'])

        created_app = JobApplication.query.filter_by(email='praveen.candidate@example.com').first()
        self.assertIsNotNone(created_app)
        self.assertEqual(created_app.full_name, 'Praveen R')
        self.assertEqual(created_app.duration, '1_month')
        self.assertEqual(created_app.college, 'Anna University')
        self.assertTrue(created_app.application_code.startswith('AM-APP-'))


if __name__ == '__main__':
    unittest.main()
