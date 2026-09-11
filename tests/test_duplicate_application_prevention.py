import os
import io
import unittest
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
    # TEST 5: Formatting variations (+91, spaces, uppercase email)
    # -------------------------------------------------------------
    def test_05_formatting_differences_normalized_and_rejected(self):
        # First submission with canonical 10-digit phone
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

        # Direct HTTP POST
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
    # TEST 7: Database Unique Constraint / IntegrityError handling
    # -------------------------------------------------------------
    def test_07_integrity_error_handled_gracefully(self):
        from sqlalchemy.exc import IntegrityError
        # Create initial record directly in DB
        app1 = JobApplication(
            job_id=self.job.id,
            full_name='Simulated User',
            email='simulated@antimatrix.org',
            phone='9112233445',
            duration='1_month',
            payment_status='pending',
            application_status='APPLIED',
            status='APPLIED',
            resume_filename='resume.pdf'
        )
        db.session.add(app1)
        db.session.commit()

        # Verify find_existing_applicant detects it
        existing = JobApplication.find_existing_applicant('SIMULATED@antimatrix.org', '+91 91122 33445')
        self.assertIsNotNone(existing)
        self.assertEqual(existing.id, app1.id)

    # -------------------------------------------------------------
    # TEST 8: No new application ID or payment record generated on duplicate
    # -------------------------------------------------------------
    def test_08_no_side_effects_on_duplicate_rejection(self):
        self.submit_application('Target Candidate', 'target@example.com', '9777788888')
        first_app = JobApplication.query.filter_by(email='target@example.com').first()
        first_code = first_app.formatted_code

        # Attempt duplicate
        self.submit_application('Target Candidate', 'target@example.com', '9777788888')

        # Verify only one application exists and code didn't change
        apps = JobApplication.query.filter_by(email='target@example.com').all()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0].formatted_code, first_code)
        self.assertEqual(Payment.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
