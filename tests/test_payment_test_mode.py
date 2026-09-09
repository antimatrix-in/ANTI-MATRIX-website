import os
import io
import json
import unittest
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment, EmailLog
from config import INTERNSHIP_FEES


class PaymentTestModeTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['PAYMENT_TEST_MODE'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        EmailLog.query.delete()
        Payment.query.delete()
        JobApplication.query.delete()
        JobPosting.query.delete()
        db.session.commit()

        # Create Admin
        self.admin = User.query.filter_by(email='admin@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(name='Test Admin', email='admin@antimatrix.ai', role='admin', is_active=True)
            self.admin.set_password('Admin@AntiMatrix2026!')
            db.session.add(self.admin)
            db.session.commit()

        # Create Candidate User
        self.candidate = User.query.filter_by(email='candidate@example.com').first()
        if not self.candidate:
            self.candidate = User(name='Test Candidate', email='candidate@example.com', role='member', is_active=True)
            self.candidate.set_password('Candidate@2026!')
            db.session.add(self.candidate)
            db.session.commit()

        # Create 1 Month Job
        self.job_1m = JobPosting(
            title='Frontend Engineer Intern',
            department='Engineering',
            location='Remote (Worldwide)',
            employment_type='Internship',
            duration='1_month',
            short_description='1-Month Frontend Internship role.',
            description='Detailed description for 1-month frontend internship.',
            requirements='HTML, CSS, JavaScript',
            responsibilities='Build UI components',
            is_active=True
        )
        db.session.add(self.job_1m)

        # Create 3 Months Job
        self.job_3m = JobPosting(
            title='AI Research Intern',
            department='AI & Data',
            location='Remote (Worldwide)',
            employment_type='Internship',
            duration='3_months',
            short_description='3-Month AI Internship role.',
            description='Detailed description for 3-month AI internship.',
            requirements='Python, PyTorch, Machine Learning',
            responsibilities='Train models',
            is_active=True
        )
        db.session.add(self.job_3m)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_admin(self):
        return self.client.post('/login', data={'email': 'admin@antimatrix.ai', 'password': 'Admin@AntiMatrix2026!'})

    def login_candidate(self, email=None, password=None):
        e = email or self.candidate.email
        p = password or 'Candidate@2026!'
        return self.client.post('/login', data={'email': e, 'password': p})

    def logout_user(self):
        return self.client.get('/logout')

    def test_01_review_page_renders_test_payment_button_when_test_mode_enabled(self):
        """Verify job_apply_review renders 'Complete Test Payment' button when PAYMENT_TEST_MODE is True."""
        self.login_candidate()
        app_record = JobApplication(
            job_id=self.job_1m.id,
            user_id=self.candidate.id,
            first_name='Rohan',
            last_name='Mehta',
            full_name='Rohan Mehta',
            email=self.candidate.email,
            phone='9876543210',
            address='123 Tech Park',
            state='Tamil Nadu',
            city='Chennai',
            pincode='600001',
            education_level="Bachelor's Degree",
            degree='B.Tech',
            major='Computer Science',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            duration='1_month',
            application_fee=199,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        resp = self.client.get(f'/careers/apply/review/{app_record.id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        self.assertIn('Base Fee', html)
        self.assertIn('199.00', html)
        self.assertIn('GST (18%)', html)
        self.assertIn('35.82', html)
        self.assertIn('Total Payable', html)
        self.assertIn('234.82', html)
        self.assertIn('Complete Test Payment', html)

    def test_02_1_month_test_payment_flow_amount_199(self):
        """Verify 1 Month test payment sets fee to 199, creates TEST payment with 18% GST (Total 234.82), generates Application ID, and sends email."""
        self.login_candidate()
        app_record = JobApplication(
            job_id=self.job_1m.id,
            user_id=self.candidate.id,
            first_name='Vikram',
            last_name='Aditya',
            full_name='Vikram Aditya',
            email=self.candidate.email,
            phone='9876543210',
            address='45 Anna Nagar',
            state='Tamil Nadu',
            city='Chennai',
            pincode='600040',
            education_level="Bachelor's Degree",
            degree='B.E.',
            major='Information Technology',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            duration='1_month',
            application_fee=199,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        # Submit test payment
        resp = self.client.post(f'/careers/apply/test-payment/{app_record.id}', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Refresh application from DB
        db.session.refresh(app_record)
        self.assertEqual(app_record.payment_status, 'paid')
        self.assertIn(app_record.application_status, ['submitted', 'APPLIED'])
        self.assertEqual(app_record.status, 'APPLIED')
        self.assertEqual(app_record.application_fee, 199)
        self.assertEqual(app_record.base_amount, 199.0)
        self.assertEqual(app_record.gst_rate, 18.0)
        self.assertEqual(app_record.gst_amount, 35.82)
        self.assertTrue(app_record.application_code.startswith('AM-APP-'))

        # Verify Payment record
        payment = Payment.query.filter_by(application_id=app_record.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.gateway, 'TEST')
        self.assertEqual(payment.amount, 234.82)
        self.assertEqual(payment.base_amount, 199.0)
        self.assertEqual(payment.gst_rate, 18.0)
        self.assertEqual(payment.gst_amount, 35.82)
        self.assertEqual(payment.payment_status, 'paid')

        # Verify Application Success Email status is updated
        self.assertIn(app_record.application_success_email_status, ['PENDING', 'SENT'])

    def test_03_3_months_test_payment_flow_amount_399(self):
        """Verify 3 Months test payment sets fee to 399, creates TEST payment with 18% GST (Total 470.82), generates Application ID."""
        self.login_candidate()
        app_record = JobApplication(
            job_id=self.job_3m.id,
            user_id=self.candidate.id,
            first_name='Ananya',
            last_name='Deshmukh',
            full_name='Ananya Deshmukh',
            email=self.candidate.email,
            phone='9876543210',
            address='78 MG Road',
            state='Maharashtra',
            city='Mumbai',
            pincode='400001',
            education_level="Master's Degree",
            degree='M.Tech',
            major='AI & Data Science',
            graduation_year='2027',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            aadhaar_filename='aadhaar.pdf',
            aadhaar_path='/tmp/aadhaar.pdf',
            duration='3_months',
            application_fee=399,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        # Submit test payment
        resp = self.client.post(f'/careers/apply/test-payment/{app_record.id}', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Refresh application from DB
        db.session.refresh(app_record)
        self.assertEqual(app_record.payment_status, 'paid')
        self.assertIn(app_record.application_status, ['submitted', 'APPLIED'])
        self.assertEqual(app_record.status, 'APPLIED')
        self.assertEqual(app_record.application_fee, 399)
        self.assertEqual(app_record.base_amount, 399.0)
        self.assertEqual(app_record.gst_rate, 18.0)
        self.assertEqual(app_record.gst_amount, 71.82)
        self.assertTrue(app_record.application_code.startswith('AM-APP-'))

        # Verify Payment record
        payment = Payment.query.filter_by(application_id=app_record.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.gateway, 'TEST')
        self.assertEqual(payment.amount, 470.82)
        self.assertEqual(payment.base_amount, 399.0)
        self.assertEqual(payment.gst_rate, 18.0)
        self.assertEqual(payment.gst_amount, 71.82)
        self.assertEqual(payment.payment_status, 'paid')

        # Verify success page HTML contains details
        html = resp.data.decode('utf-8')
        self.assertIn('Application Submitted Successfully', html)
        self.assertIn(app_record.formatted_code, html)
        self.assertIn('470.82', html)

    def test_04_idempotent_duplicate_click_protection(self):
        """Verify calling test-payment multiple times returns existing Application ID without duplicates."""
        self.login_candidate()
        app_record = JobApplication(
            job_id=self.job_1m.id,
            user_id=self.candidate.id,
            first_name='Karthik',
            last_name='Natarajan',
            full_name='Karthik Natarajan',
            email=self.candidate.email,
            phone='9876543210',
            address='12 OMR Road',
            state='Tamil Nadu',
            city='Chennai',
            pincode='600096',
            education_level="Bachelor's Degree",
            degree='B.Tech',
            major='Computer Science',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            duration='1_month',
            application_fee=199,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        # First test payment click
        resp1 = self.client.post(f'/careers/apply/test-payment/{app_record.id}', follow_redirects=False)
        self.assertEqual(resp1.status_code, 302)
        db.session.refresh(app_record)
        app_code_1 = app_record.formatted_code

        # Second rapid test payment click
        resp2 = self.client.post(f'/careers/apply/test-payment/{app_record.id}', follow_redirects=False)
        self.assertEqual(resp2.status_code, 302)
        db.session.refresh(app_record)
        app_code_2 = app_record.formatted_code

        # Verify identical code and single application
        self.assertEqual(app_code_1, app_code_2)
        self.assertEqual(JobApplication.query.filter_by(email=self.candidate.email).count(), 1)

    def test_05_admin_dashboard_displays_test_payment_application(self):
        """Verify Admin Dashboard and application list immediately displays candidate after test payment."""
        self.login_candidate()
        app_record = JobApplication(
            job_id=self.job_3m.id,
            user_id=self.candidate.id,
            first_name='Sneha',
            last_name='Kapoor',
            full_name='Sneha Kapoor',
            email=self.candidate.email,
            phone='9876543210',
            address='88 Indiranagar',
            state='Karnataka',
            city='Bengaluru',
            pincode='560038',
            education_level="Bachelor's Degree",
            degree='B.Tech',
            major='AI',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            duration='3_months',
            application_fee=399,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        # Submit test payment
        self.client.post(f'/careers/apply/test-payment/{app_record.id}')
        db.session.refresh(app_record)

        # Login admin and view applications
        self.logout_user()
        self.login_admin()
        resp = self.client.get('/admin/applications')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')
        self.assertIn('Sneha Kapoor', html)
        self.assertIn(app_record.formatted_code, html)
        self.assertIn('470.82', html)
        self.assertIn('Paid', html)

    def test_06_real_cashfree_preserved_when_test_mode_is_false(self):
        """Verify that when PAYMENT_TEST_MODE is False, job_apply_review renders Cashfree pay button."""
        self.app.config['PAYMENT_TEST_MODE'] = False
        self.login_candidate()

        app_record = JobApplication(
            job_id=self.job_1m.id,
            user_id=self.candidate.id,
            first_name='Pooja',
            last_name='Nair',
            full_name='Pooja Nair',
            email=self.candidate.email,
            phone='9876543210',
            address='12 MG Road',
            state='Kerala',
            city='Kochi',
            pincode='682001',
            education_level="Bachelor's Degree",
            degree='B.Sc',
            major='CS',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            duration='1_month',
            application_fee=199,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_record)
        db.session.commit()

        resp = self.client.get(f'/careers/apply/review/{app_record.id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Should show regular Pay button and Cashfree encryption label
        self.assertIn('Pay', html)
        self.assertIn('Cashfree Payments', html)
        self.assertNotIn('Complete Test Payment', html)


if __name__ == '__main__':
    unittest.main()
