import io
import json
import unittest
from decimal import Decimal
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment, MoneyTransaction
from services.payment_service import calculate_payment_total
from services.cashfree_service import CashfreeService


class DurationMovedToApplicationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Get or create Admin user
        self.admin = User.query.filter_by(role='admin').first()
        if not self.admin:
            self.admin = User(name='Admin Test', email='admin_dur@antimatrix.ai', role='admin', is_active=True)
            self.admin.set_password('AdminPass123!')
            db.session.add(self.admin)
        else:
            self.admin.set_password('AdminPass123!')

        # Candidate user
        self.candidate = User(name='Candidate Test', email='candidate_dur@antimatrix.ai', role='member', is_active=True)
        self.candidate.set_password('CandidatePass123!')
        db.session.add(self.candidate)

        # Internship Job without duration
        self.intern_job = JobPosting(
            job_code='JB1001',
            title='Software Developer Intern',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            duration=None,
            salary='Performance Based',
            short_description='Exciting software developer internship role.',
            description='Build web systems.',
            requirements='Python, Flask, HTML/CSS',
            responsibilities='Write code and review PRs',
            is_active=True
        )
        db.session.add(self.intern_job)

        # Non-internship Full-time Job
        self.fulltime_job = JobPosting(
            job_code='JB1002',
            title='Senior Backend Engineer',
            department='Engineering',
            location='Bengaluru',
            employment_type='Full-time',
            duration=None,
            salary='₹12 - ₹18 LPA',
            short_description='Senior engineering position.',
            description='Architect scalable backend microservices.',
            requirements='Python, PostgreSQL, AWS',
            responsibilities='Lead system design',
            is_active=True
        )
        db.session.add(self.fulltime_job)

        # Historical Job with existing duration (e.g. legacy '1_month')
        self.legacy_job = JobPosting(
            job_code='JB0999',
            title='Legacy Intern',
            department='Design',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            salary='Stipend',
            short_description='Legacy role.',
            description='Historical posting.',
            requirements='Figma',
            responsibilities='UI Design',
            is_active=True
        )
        db.session.add(self.legacy_job)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_admin(self):
        return self.client.post('/login', data={'email': self.admin.email, 'password': 'AdminPass123!'}, follow_redirects=True)

    def login_candidate(self):
        return self.client.post('/login', data={'email': self.candidate.email, 'password': 'CandidatePass123!'}, follow_redirects=True)

    # ----------------------------------------------------------------------
    # 1. Admin Create Job Page: No duration/tier dropdown UI
    # ----------------------------------------------------------------------
    def test_01_admin_create_job_form_no_duration_dropdown(self):
        self.login_admin()
        res = self.client.get('/admin/jobs/create')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Confirm duration dropdown is NOT present
        self.assertNotIn('<select id="duration"', html)
        self.assertNotIn('name="duration"', html)
        self.assertNotIn('Program Tier & Fee', html)
        self.assertNotIn('1 Month Internship (₹199', html)

        # Confirm standard fields ARE present
        self.assertIn('job_code', html)
        self.assertIn('title', html)
        self.assertIn('department', html)
        self.assertIn('location', html)
        self.assertIn('employment_type', html)
        self.assertIn('salary', html)
        self.assertIn('application_deadline', html)

    # ----------------------------------------------------------------------
    # 2. Admin Edit Job Page: No duration dropdown UI
    # ----------------------------------------------------------------------
    def test_02_admin_edit_job_form_no_duration_dropdown(self):
        self.login_admin()
        res = self.client.get(f'/admin/jobs/edit/{self.intern_job.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertNotIn('<select id="duration"', html)
        self.assertNotIn('name="duration"', html)
        self.assertNotIn('Program Tier & Fee', html)

    # ----------------------------------------------------------------------
    # 3. Admin Job Creation creates job with duration=None and valid job_code
    # ----------------------------------------------------------------------
    def test_03_admin_create_job_posting_success(self):
        self.login_admin()
        post_data = {
            'job_code': 'JB2026',
            'title': 'Frontend Developer Intern',
            'department': 'Product',
            'location': 'Remote',
            'employment_type': 'Internship',
            'salary': 'Performance Based',
            'short_description': 'Build React & Flask apps.',
            'description': 'Full description for frontend intern.',
            'requirements': 'HTML, CSS, JS',
            'responsibilities': 'Develop UI components',
            'is_active': 'y'
        }
        res = self.client.post('/admin/jobs/create', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        created = JobPosting.query.filter_by(job_code='JB2026').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.duration, None)
        self.assertEqual(created.job_code, 'JB2026')
        self.assertTrue(created.is_internship)

    # ----------------------------------------------------------------------
    # 4. Admin Job Edit updates job without requiring duration
    # ----------------------------------------------------------------------
    def test_04_admin_edit_job_posting_success(self):
        self.login_admin()
        edit_data = {
            'job_code': 'JB1001',
            'title': 'Senior Software Intern',
            'department': 'Engineering',
            'location': 'Hybrid',
            'employment_type': 'Internship',
            'salary': '₹15,000/mo',
            'short_description': 'Updated short description.',
            'description': 'Updated full description.',
            'requirements': 'Python, PostgreSQL',
            'responsibilities': 'Develop and test',
            'is_active': 'y'
        }
        res = self.client.post(f'/admin/jobs/edit/{self.intern_job.id}', data=edit_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated = JobPosting.query.get(self.intern_job.id)
        self.assertEqual(updated.title, 'Senior Software Intern')
        self.assertEqual(updated.location, 'Hybrid')
        self.assertEqual(updated.duration, None)

    # ----------------------------------------------------------------------
    # 5. Public Careers Page displays flexible duration and both fee tiers
    # ----------------------------------------------------------------------
    def test_05_careers_page_displays_flexible_duration(self):
        res = self.client.get('/careers')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn('1 or 3 Months', html)
        self.assertIn('199', html)
        self.assertIn('399', html)

    # ----------------------------------------------------------------------
    # 6. Job Application Form has duration radios (1 Month and 3 Months)
    # ----------------------------------------------------------------------
    def test_06_application_form_has_duration_selection(self):
        self.login_candidate()
        res = self.client.get(f'/careers/apply/{self.intern_job.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        self.assertIn('name="duration"', html)
        self.assertIn('value="1_month"', html)
        self.assertIn('value="3_months"', html)
        self.assertIn('identity-docs-card', html)

    def _get_base_form_data(self):
        return {
            'first_name': 'Candidate',
            'last_name': 'Test',
            'email': self.candidate.email,
            'phone': '9876543210',
            'address': '123 Innovation Way',
            'state': 'Karnataka',
            'city': 'Bengaluru',
            'pincode': '560001',
            'education_level': "Bachelor's Degree",
            'degree': 'B.Tech',
            'major': 'Computer Science',
            'graduation_year': '2025',
        }

    # ----------------------------------------------------------------------
    # 7. Submitting internship application without duration fails
    # ----------------------------------------------------------------------
    def test_07_internship_application_without_duration_rejected(self):
        self.login_candidate()
        data = self._get_base_form_data()
        data['resume'] = (io.BytesIO(b'%PDF-1.4 test resume'), 'resume.pdf')
        # No 'duration' provided

        res = self.client.post(f'/careers/apply/{self.intern_job.id}', data=data, follow_redirects=True, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Please select a valid Internship Duration', html)

        # Verify no application was created
        app_count = JobApplication.query.filter_by(job_id=self.intern_job.id).count()
        self.assertEqual(app_count, 0)

    # ----------------------------------------------------------------------
    # 8. 1 Month Application succeeds without Aadhaar, stores 199 base fee
    # ----------------------------------------------------------------------
    def test_08_apply_1_month_success_pricing(self):
        self.login_candidate()
        data = self._get_base_form_data()
        data['duration'] = '1_month'
        data['resume'] = (io.BytesIO(b'%PDF-1.4 test resume'), 'resume.pdf')

        res = self.client.post(f'/careers/apply/{self.intern_job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')
        # Expect redirect to review page
        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/review/', res.headers['Location'])

        app_rec = JobApplication.query.filter_by(job_id=self.intern_job.id, email=self.candidate.email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.duration, '1_month')
        self.assertEqual(app_rec.application_fee, 199)
        self.assertEqual(app_rec.base_amount, 199.0)
        self.assertEqual(app_rec.gst_rate, 18.0)
        self.assertEqual(app_rec.gst_amount, 35.82)
        self.assertEqual(app_rec.payment_status, 'pending')

    # ----------------------------------------------------------------------
    # 9. 3 Months Application requires Aadhaar; fails if missing
    # ----------------------------------------------------------------------
    def test_09_apply_3_months_requires_aadhaar(self):
        self.login_candidate()
        data = self._get_base_form_data()
        data['duration'] = '3_months'
        data['resume'] = (io.BytesIO(b'%PDF-1.4 test resume'), 'resume.pdf')
        # No Aadhaar uploaded

        res = self.client.post(f'/careers/apply/{self.intern_job.id}', data=data, follow_redirects=True, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Aadhaar Card', html)
        self.assertIn('File is required', html)

    # ----------------------------------------------------------------------
    # 10. 3 Months Application with Aadhaar succeeds, stores 399 base fee
    # ----------------------------------------------------------------------
    def test_10_apply_3_months_success_pricing(self):
        self.login_candidate()
        data = self._get_base_form_data()
        data['duration'] = '3_months'
        data['resume'] = (io.BytesIO(b'%PDF-1.4 test resume'), 'resume.pdf')
        data['aadhaar'] = (io.BytesIO(b'%PDF-1.4 aadhaar copy'), 'aadhaar.pdf')

        res = self.client.post(f'/careers/apply/{self.intern_job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/review/', res.headers['Location'])

        app_rec = JobApplication.query.filter_by(job_id=self.intern_job.id, email=self.candidate.email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.duration, '3_months')
        self.assertEqual(app_rec.application_fee, 399)
        self.assertEqual(app_rec.base_amount, 399.0)
        self.assertEqual(app_rec.gst_rate, 18.0)
        self.assertEqual(app_rec.gst_amount, 71.82)
        self.assertIsNotNone(app_rec.aadhaar_filename)

    # ----------------------------------------------------------------------
    # 11. Review page calculates authoritative fee strictly from application.duration
    # ----------------------------------------------------------------------
    def test_11_review_page_authoritative_gst_breakdown(self):
        self.login_candidate()
        # Create 1 Month application
        app_1m = JobApplication(
            job_id=self.intern_job.id,
            user_id=self.candidate.id,
            first_name='Test',
            last_name='Candidate',
            full_name='Test Candidate',
            email=self.candidate.email,
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            base_amount=199.0,
            gst_rate=18.0,
            gst_amount=35.82,
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            payment_status='pending'
        )
        db.session.add(app_1m)
        db.session.commit()

        res = self.client.get(f'/careers/apply/review/{app_1m.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('199.00', html)
        self.assertIn('35.82', html)
        self.assertIn('234.82', html)

        # Update to 3 Months
        app_1m.duration = '3_months'
        db.session.commit()

        res2 = self.client.get(f'/careers/apply/review/{app_1m.id}')
        self.assertEqual(res2.status_code, 200)
        html2 = res2.get_data(as_text=True)
        self.assertIn('399.00', html2)
        self.assertIn('71.82', html2)
        self.assertIn('470.82', html2)

    # ----------------------------------------------------------------------
    # 12. Cashfree order creation strictly uses application.duration
    # ----------------------------------------------------------------------
    def test_12_cashfree_order_uses_application_duration(self):
        app_3m = JobApplication(
            job_id=self.intern_job.id,
            user_id=self.candidate.id,
            first_name='Cashfree',
            last_name='Tester',
            full_name='Cashfree Tester',
            email='cashfree_test@antimatrix.ai',
            phone='9876543210',
            duration='3_months',
            application_fee=399,
            base_amount=399.0,
            gst_rate=18.0,
            gst_amount=71.82,
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            payment_status='pending'
        )
        db.session.add(app_3m)
        db.session.commit()

        success, order, err = CashfreeService.create_order(
            application=app_3m,
            job=self.intern_job,
            return_url='http://localhost/payment/cashfree/return?order_id={order_id}'
        )
        self.assertTrue(success)
        self.assertEqual(float(order['order_amount']), 470.82)
        self.assertEqual(float(order['base_amount']), 399.0)
        self.assertEqual(float(order['gst_amount']), 71.82)
        self.assertEqual(float(order['gst_rate']), 18.0)

    # ----------------------------------------------------------------------
    # 13. Test Payment route uses server-side authoritative pricing
    # ----------------------------------------------------------------------
    def test_13_test_payment_route_authoritative_calculation(self):
        self.login_candidate()
        app_1m = JobApplication(
            job_id=self.intern_job.id,
            user_id=self.candidate.id,
            first_name='Candidate',
            last_name='Tester',
            full_name='Candidate Tester',
            email=self.candidate.email,
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_1m)
        db.session.commit()

        res = self.client.post(f'/careers/apply/test-payment/{app_1m.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        updated_app = db.session.get(JobApplication, app_1m.id)
        self.assertEqual(updated_app.payment_status, 'paid')
        self.assertEqual(updated_app.application_status, 'APPLIED')
        self.assertEqual(updated_app.base_amount, 199.0)
        self.assertEqual(updated_app.gst_amount, 35.82)
        self.assertIsNotNone(updated_app.application_code)

        # Check Payment record
        payment = Payment.query.filter_by(application_id=app_1m.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(float(payment.amount), 234.82)
        self.assertEqual(float(payment.base_amount), 199.0)
        self.assertEqual(float(payment.gst_amount), 35.82)
        self.assertEqual(payment.payment_status, 'paid')

    # ----------------------------------------------------------------------
    # 14. Non-internship job (e.g. Full-time) does not require duration or fee
    # ----------------------------------------------------------------------
    def test_14_non_internship_job_application_exempt(self):
        self.login_candidate()
        data = self._get_base_form_data()
        data['resume'] = (io.BytesIO(b'%PDF-1.4 fulltime resume'), 'resume.pdf')

        res = self.client.post(f'/careers/apply/{self.fulltime_job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/success/', res.headers['Location'])

        app_rec = JobApplication.query.filter_by(job_id=self.fulltime_job.id).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.duration, None)
        self.assertEqual(app_rec.payment_status, 'exempt')
        self.assertEqual(app_rec.application_status, 'submitted')
        self.assertIsNotNone(app_rec.application_code)

    # ----------------------------------------------------------------------
    # 15. Admin View Application displays candidate's selected duration
    # ----------------------------------------------------------------------
    def test_15_admin_view_application_displays_duration(self):
        app_rec = JobApplication(
            job_id=self.intern_job.id,
            user_id=self.candidate.id,
            first_name='Pooja',
            last_name='Sharma',
            full_name='Pooja Sharma',
            email='pooja@antimatrix.ai',
            phone='9876543210',
            duration='3_months',
            application_fee=399,
            base_amount=399.0,
            gst_rate=18.0,
            gst_amount=71.82,
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            payment_status='paid',
            application_status='submitted'
        )
        db.session.add(app_rec)
        db.session.commit()

        self.login_admin()
        res = self.client.get(f'/admin/applications/{app_rec.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('3 Months', html)


if __name__ == '__main__':
    unittest.main()
