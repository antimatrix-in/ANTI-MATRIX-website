import os
import io
import unittest
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment


class CandidatePipelineAndPaymentUITestCase(unittest.TestCase):
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

        # Create Admin
        self.admin = User(name='Admin User', email='admin@antimatrix.ai', role='admin', is_active=True)
        self.admin.set_password('Admin@2026!')
        db.session.add(self.admin)

        # Create Candidate Alice
        self.user_alice = User(name='Alice Sharma', email='alice@antimatrix.org', role='member', is_active=True)
        self.user_alice.set_password('AlicePass123!')
        db.session.add(self.user_alice)

        # Create Candidate Bob
        self.user_bob = User(name='Bob Verma', email='bob@antimatrix.org', role='member', is_active=True)
        self.user_bob.set_password('BobPass123!')
        db.session.add(self.user_bob)

        # Create Internship Job
        self.job = JobPosting(
            title='AI Research Intern',
            department='Machine Learning',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            short_description='Research next-gen ML models.',
            description='Deep learning research position.',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

        # Create Alice's Application
        self.alice_app = JobApplication(
            job_id=self.job.id,
            user_id=self.user_alice.id,
            full_name='Alice Sharma',
            email='alice@antimatrix.org',
            phone='9876543210',
            duration='1_month',
            college='IIT Madras',
            application_fee=199,
            payment_status='pending',
            application_status='APPLIED',
            status='APPLIED',
            resume_filename='alice_resume.pdf',
            resume_path='/uploads/resumes/alice_resume.pdf'
        )
        db.session.add(self.alice_app)
        db.session.commit()
        self.alice_app.application_code = JobApplication.generate_unique_application_code(app_id=self.alice_app.id)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def login(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_my_applications_removes_payment_pending_and_complete_payment(self):
        """Candidate 'My Applications' page must NOT show 'Payment Pending' or 'Complete Payment' button."""
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res = self.client.get('/my-applications')
        self.assertEqual(res.status_code, 200)

        # Payment Pending must not appear
        self.assertNotIn(b'Payment Pending', res.data)
        # Complete Payment button must not appear
        self.assertNotIn(b'Complete Payment', res.data)
        # Useful metadata must remain
        self.assertIn(b'AI Research Intern', res.data)
        self.assertIn(b'1 Month', res.data)
        self.assertIn(b'Applied', res.data)
        self.assertIn(b'View Dossier', res.data)

    def test_application_detail_removes_payment_ui(self):
        """Candidate application detail page must NOT show 'Payment Pending' or 'Complete Payment'."""
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res.status_code, 200)

        self.assertNotIn(b'Payment Pending', res.data)
        self.assertNotIn(b'Complete Payment', res.data)

    def test_initial_pipeline_stage_applied(self):
        """When application is APPLIED, Step 1 is highlighted as CURRENT, Steps 2 and 3 are Upcoming."""
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res.status_code, 200)

        html = res.data.decode('utf-8')
        self.assertIn('Submitted', html)
        self.assertIn('Under Review', html)
        self.assertIn('Shortlisted', html)
        self.assertIn('Pending Evaluation', html)
        self.assertIn('Awaiting Decision', html)

    def test_admin_updates_to_under_review_reflects_dynamically(self):
        """Admin marks application Under Review -> candidate details page immediately reflects Under Review as CURRENT."""
        # Admin updates stage
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        res_admin = self.client.post(f'/admin/applications/{self.alice_app.id}/mark-under-review', follow_redirects=True)
        self.assertEqual(res_admin.status_code, 200)

        # Verify database
        app_db = db.session.get(JobApplication, self.alice_app.id)
        db.session.refresh(app_db)
        self.assertEqual(app_db.stage, 'UNDER_REVIEW')

        # Alice refreshes application details
        self.logout()
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res_alice = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res_alice.status_code, 200)

        html = res_alice.data.decode('utf-8')
        self.assertIn('In Evaluation &bull; Current Stage', html)
        self.assertIn('Awaiting Decision', html)

    def test_admin_updates_to_shortlisted_reflects_dynamically(self):
        """Admin marks application Shortlisted -> candidate details page immediately reflects Shortlisted as CURRENT."""
        # Admin updates stage via status endpoint
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        res_admin = self.client.post(f'/admin/applications/{self.alice_app.id}/status', data={'status': 'SHORTLISTED'}, follow_redirects=True)
        self.assertEqual(res_admin.status_code, 200)

        # Verify database
        app_db = db.session.get(JobApplication, self.alice_app.id)
        db.session.refresh(app_db)
        self.assertEqual(app_db.stage, 'SHORTLISTED')

        # Alice refreshes page
        self.logout()
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res_alice = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res_alice.status_code, 200)

        html = res_alice.data.decode('utf-8')
        self.assertIn('Evaluation Completed', html)
        self.assertIn('Offer Process &bull; Current Stage', html)

    def test_admin_updates_to_rejected_reflects_dynamically(self):
        """Admin marks application Rejected -> candidate details page reflects Not Selected."""
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        self.client.post(f'/admin/applications/{self.alice_app.id}/status', data={'status': 'REJECTED'}, follow_redirects=True)

        self.logout()
        self.login('alice@antimatrix.org', 'AlicePass123!')
        res_alice = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res_alice.status_code, 200)

        html = res_alice.data.decode('utf-8')
        self.assertIn('Not Selected', html)
        self.assertIn('Application Concluded', html)

    def test_candidate_cannot_view_another_candidates_application(self):
        """Security: Bob cannot view Alice's application details."""
        self.login('bob@antimatrix.org', 'BobPass123!')
        res = self.client.get(f'/my-applications/{self.alice_app.id}')
        self.assertEqual(res.status_code, 404)


if __name__ == '__main__':
    unittest.main()
