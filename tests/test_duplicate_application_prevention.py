import os
import io
import unittest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment


class DuplicateApplicationPreventionTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        Payment.query.delete()
        JobApplication.query.delete()
        JobPosting.query.delete()
        User.query.delete()
        db.session.commit()

        # Create Internship Job
        self.job = JobPosting(
            title='Full Stack Intern',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            short_description='Develop modern web apps.',
            description='Full stack role using Python and modern frontend.',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def submit_application(self, full_name, email, phone, college="IIT Bombay", duration="1_month"):
        resume_file = (io.BytesIO(b'%PDF-1.4 Mock resume'), 'resume.pdf')
        data = {
            'full_name': full_name,
            'email': email,
            'phone': phone,
            'college': college,
            'duration': duration,
            'resume': resume_file
        }
        return self.client.post(f'/careers/apply/{self.job.id}', data=data, content_type='multipart/form-data', follow_redirects=True)

    # -------------------------------------------------------------
    # TEST 1: New candidate + new email + new mobile -> Application succeeds
    # -------------------------------------------------------------
    def test_01_new_candidate_succeeds(self):
        initial_count = JobApplication.query.count()
        res = self.submit_application('Kavitha Nair', 'kavitha@example.com', '9876543211')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(JobApplication.query.count(), initial_count + 1)
        self.assertIn(b'Application submitted successfully', res.data)

        app = JobApplication.query.filter_by(email='kavitha@example.com').first()
        self.assertIsNotNone(app)
        self.assertEqual(app.phone, '9876543211')

    # -------------------------------------------------------------
    # TEST 2: Same email + different mobile -> Application rejected
    # -------------------------------------------------------------
    def test_02_same_email_different_mobile_rejected(self):
        # First submission
        self.submit_application('Kavitha Nair', 'kavitha@example.com', '9876543211')
        initial_count = JobApplication.query.count()

        # Second submission with same email but different phone
        res = self.submit_application('Kavitha Duplicate', 'kavitha@example.com', '9123456789')
        self.assertEqual(res.status_code, 200)
        # Database count remains unchanged
        self.assertEqual(JobApplication.query.count(), initial_count)
        # Safe user message
        self.assertIn(b'An application has already been submitted using this email address or mobile number.', res.data)

    # -------------------------------------------------------------
    # TEST 3: Different email + same mobile -> Application rejected
    # -------------------------------------------------------------
    def test_03_different_email_same_mobile_rejected(self):
        # First submission
        self.submit_application('Kavitha Nair', 'kavitha@example.com', '9876543211')
        initial_count = JobApplication.query.count()

        # Second submission with different email but same phone
        res = self.submit_application('Another Person', 'another.person@example.com', '9876543211')
        self.assertEqual(res.status_code, 200)
        # Database count remains unchanged
        self.assertEqual(JobApplication.query.count(), initial_count)
        self.assertIn(b'An application has already been submitted using this email address or mobile number.', res.data)

    # -------------------------------------------------------------
    # TEST 4: Same email + same mobile -> Application rejected
    # -------------------------------------------------------------
    def test_04_same_email_same_mobile_rejected(self):
        # First submission
        self.submit_application('Kavitha Nair', 'kavitha@example.com', '9876543211')
        initial_count = JobApplication.query.count()

        # Repeat identical submission
        res = self.submit_application('Kavitha Nair', 'kavitha@example.com', '9876543211')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(JobApplication.query.count(), initial_count)
        self.assertIn(b'An application has already been submitted using this email address or mobile number.', res.data)

    # -------------------------------------------------------------
    # TEST 5: Same candidate attempts to submit the same application again
    # -------------------------------------------------------------
    def test_05_same_candidate_attempts_to_submit_again(self):
        # First submission
        self.submit_application('Rohan Das', 'rohandas@example.com', '9988776655')
        initial_count = JobApplication.query.count()

        # Attempt duplicate using '+91 99887 76655' and 'RohanDas@Example.COM'
        res = self.submit_application('Rohan Das', '  RohanDas@Example.COM  ', '+91 99887 76655')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(JobApplication.query.count(), initial_count)
        self.assertIn(b'An application has already been submitted using this email address or mobile number.', res.data)

    # -------------------------------------------------------------
    # TEST 6: Direct API call / bypassed frontend still rejected
    # -------------------------------------------------------------
    def test_06_direct_backend_request_rejected(self):
        self.submit_application('Praveen R', 'praveen@test.com', '9876543210')
        initial_count = JobApplication.query.count()

        # Direct HTTP POST without browser UI
        res = self.client.post(f'/careers/apply/{self.job.id}', data={
            'full_name': 'Praveen R',
            'email': 'praveen@test.com',
            'phone': '9876543210',
            'college': 'Anna University',
            'duration': '3_months'
        }, follow_redirects=True)

        self.assertEqual(JobApplication.query.count(), initial_count)
        self.assertIn(b'An application has already been submitted', res.data)

    # -------------------------------------------------------------
    # TEST 7: Race Condition / Concurrent submissions handled via DB constraint
    # -------------------------------------------------------------
    def test_07_concurrent_submissions_race_condition_handled(self):
        # Simulate simultaneous arrival where db.session.commit raises IntegrityError
        with patch.object(db.session, 'commit', side_effect=IntegrityError("duplicate key", {}, None)):
            res = self.submit_application('Concurrent User', 'concurrent@antimatrix.org', '9443322110')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'An application has already been submitted using this email address or mobile number.', res.data)

    # -------------------------------------------------------------
    # TEST 8: Existing candidate and application records remain intact
    # -------------------------------------------------------------
    def test_08_existing_records_remain_completely_intact(self):
        # Seed an existing application record
        existing_app = JobApplication(
            job_id=self.job.id,
            full_name='Praveen Production',
            email='praveen_prod@antimatrix.com',
            phone='8825418639',
            duration='1_month',
            payment_status='paid',
            application_status='submitted',
            status='APPLIED',
            resume_filename='prod.pdf'
        )
        db.session.add(existing_app)
        db.session.commit()
        original_id = existing_app.id
        original_code = existing_app.formatted_code

        # Attempt to apply with same email
        res = self.submit_application('Praveen Hacker', 'praveen_prod@antimatrix.com', '9999900000')
        self.assertIn(b'An application has already been submitted', res.data)

        # Verify original record unchanged
        refreshed = db.session.get(JobApplication, original_id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.full_name, 'Praveen Production')
        self.assertEqual(refreshed.phone, '8825418639')
        self.assertEqual(refreshed.formatted_code, original_code)
        self.assertEqual(refreshed.payment_status, 'paid')

    # -------------------------------------------------------------
    # TEST 9: Existing payment records remain completely intact
    # -------------------------------------------------------------
    def test_09_existing_payment_records_remain_intact(self):
        # Create an application and a linked payment
        app = JobApplication(
            job_id=self.job.id,
            full_name='Paid Candidate',
            email='paid_candidate@antimatrix.com',
            phone='9551073031',
            duration='1_month',
            payment_status='paid',
            application_status='submitted',
            status='APPLIED',
            resume_filename='paid.pdf'
        )
        db.session.add(app)
        db.session.flush()

        payment = Payment(
            application_id=app.id,
            cashfree_order_id='order_cf_123456',
            amount=199.0,
            base_amount=199.0,
            currency='INR',
            payment_status='paid',
            gateway='CASHFREE',
            cf_payment_id='cf_123456'
        )
        db.session.add(payment)
        db.session.commit()

        initial_payments_count = Payment.query.count()
        self.assertEqual(initial_payments_count, 1)

        # Attempt duplicate submission
        res = self.submit_application('Duplicate Candidate', 'paid_candidate@antimatrix.com', '9551073031')
        self.assertIn(b'An application has already been submitted', res.data)

        # Ensure no payment record was added, altered, or deleted
        self.assertEqual(Payment.query.count(), initial_payments_count)
        p = Payment.query.first()
        self.assertEqual(p.cf_payment_id, 'cf_123456')
        self.assertEqual(p.cashfree_order_id, 'order_cf_123456')
        self.assertEqual(p.payment_status, 'paid')

    # -------------------------------------------------------------
    # TEST 10: Application startup on Render with constraint verification
    # -------------------------------------------------------------
    def test_10_application_startup_and_connection(self):
        from migrations.migrate_unique_applicant_constraints import run_migration
        # Test that migration and startup checks run cleanly and idempotently
        run_migration()
        # Verify app initializes normally
        app = create_app('testing')
        self.assertIsNotNone(app)


if __name__ == '__main__':
    unittest.main()
