import os
import io
import unittest
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment


class UserApplicationFlowTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['PAYMENT_TEST_MODE'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        Payment.query.delete()
        JobApplication.query.delete()
        JobPosting.query.delete()
        User.query.delete()
        db.session.commit()

        # 1. Create Admin
        self.admin = User(name='Admin User', email='admin@antimatrix.ai', role='admin', is_active=True)
        self.admin.set_password('Admin@2026!')
        db.session.add(self.admin)

        # 2. Create Candidate User A
        self.user_a = User(name='Alice Sharma', email='alice@example.com', role='member', is_active=True)
        self.user_a.set_password('AlicePass123!')
        db.session.add(self.user_a)

        # 3. Create Candidate User B
        self.user_b = User(name='Bob Verma', email='bob@example.com', role='member', is_active=True)
        self.user_b.set_password('BobPass123!')
        db.session.add(self.user_b)

        # 4. Create Job A (1 Month Internship)
        self.job_a = JobPosting(
            title='AI Engineer Intern',
            department='AI & Data',
            location='Remote (Worldwide)',
            employment_type='Internship',
            duration='1_month',
            short_description='Develop production machine learning pipelines.',
            description='Work directly with senior AI architects on NLP and vision systems.',
            is_active=True
        )
        db.session.add(self.job_a)

        # 5. Create Job B (3 Months Internship)
        self.job_b = JobPosting(
            title='Python Developer Intern',
            department='Engineering',
            location='Remote (Worldwide)',
            employment_type='Internship',
            duration='3_months',
            short_description='Build scalable backend APIs and microservices.',
            description='Develop enterprise web applications and data pipelines with Python.',
            is_active=True
        )
        db.session.add(self.job_b)

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def login(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password}, follow_redirects=False)

    def logout(self):
        return self.client.get('/logout', follow_redirects=True)

    # -------------------------------------------------------------
    # 1. TEST: Unauthenticated user accessing Apply Now -> Login redirect
    # -------------------------------------------------------------
    def test_apply_now_requires_login_and_preserves_job(self):
        """Unauthenticated visitor clicking Apply Now must be redirected to login with next parameter."""
        res = self.client.get(f'/careers/apply/{self.job_a.id}', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn(f'/login?next=/careers/apply/{self.job_a.id}', res.headers['Location'])

    # -------------------------------------------------------------
    # 2. TEST: Safe redirect validation (Open redirect prevention)
    # -------------------------------------------------------------
    def test_login_safe_redirect_prevents_open_redirect(self):
        """External or malformed redirect targets must be safely sanitized to default home/dashboard."""
        from routes.auth import get_safe_redirect
        self.assertEqual(get_safe_redirect('https://evil.com'), '/')
        self.assertEqual(get_safe_redirect('//evil.com/phish'), '/')
        self.assertEqual(get_safe_redirect('/careers/apply/1'), '/careers/apply/1')
        self.assertEqual(get_safe_redirect('/my-applications'), '/my-applications')

    # -------------------------------------------------------------
    # 3. TEST: Successful login returns to original job application page
    # -------------------------------------------------------------
    def test_login_returns_to_intended_job_application(self):
        """After logging in, user is automatically redirected to the selected job application page."""
        target_path = f'/careers/apply/{self.job_a.id}'
        res = self.client.post('/login', data={
            'email': 'alice@example.com',
            'password': 'AlicePass123!',
            'redirect': target_path
        }, follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.headers['Location'], target_path)

        # Accessing the application page as logged in user directly returns 200
        app_page = self.client.get(target_path)
        self.assertEqual(app_page.status_code, 200)
        self.assertIn(b'AI Engineer Intern', app_page.data)
        self.assertIn(b'alice@example.com', app_page.data)

    # -------------------------------------------------------------
    # 4. TEST: Already authenticated user accesses Apply Now directly
    # -------------------------------------------------------------
    def test_already_logged_in_user_direct_access(self):
        """Already logged-in user goes straight to application form without seeing login."""
        self.login('alice@example.com', 'AlicePass123!')
        res = self.client.get(f'/careers/apply/{self.job_a.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Application Form', res.data)
        self.assertNotIn(b'Sign in to your Anti-Matrix account', res.data)

    # -------------------------------------------------------------
    # 5. TEST: End-to-end application submission and User Account binding
    # -------------------------------------------------------------
    def test_application_submission_binds_user_and_generates_app_id(self):
        """Application submission binds user_id, processes simulated payment, and issues AM-APP-XXXXXX."""
        self.login('alice@example.com', 'AlicePass123!')

        resume_file = (io.BytesIO(b'%PDF-1.4 Mock resume content for Alice'), 'alice_resume.pdf')
        form_data = {
            'first_name': 'Alice',
            'last_name': 'Sharma',
            'email': 'alice@example.com',
            'phone': '9876543210',
            'address': '123 Tech Park, Anna Nagar',
            'state': 'Tamil Nadu',
            'city': 'Chennai',
            'pincode': '600040',
            'education_level': "Bachelor's Degree",
            'degree': 'B.Tech',
            'major': 'Computer Science',
            'graduation_year': '2026',
            'resume': resume_file
        }

        # Step 1: Submit Application Form -> Redirects to Review & Payment
        res = self.client.post(f'/careers/apply/{self.job_a.id}', data=form_data, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)

        app_record = JobApplication.query.filter_by(job_id=self.job_a.id, user_id=self.user_a.id).first()
        self.assertIsNotNone(app_record)
        self.assertEqual(app_record.user_id, self.user_a.id)
        self.assertEqual(app_record.payment_status, 'pending')

        # Step 2: Review Page
        rev_res = self.client.get(f'/careers/apply/review/{app_record.id}')
        self.assertEqual(rev_res.status_code, 200)
        self.assertIn(b'199', rev_res.data)

        # Step 3: Complete Test Payment
        pay_res = self.client.post(f'/careers/apply/test-payment/{app_record.id}', follow_redirects=False)
        self.assertEqual(pay_res.status_code, 302)

        db.session.refresh(app_record)
        self.assertEqual(app_record.payment_status, 'paid')
        self.assertIn(app_record.application_status, ['submitted', 'APPLIED'])
        self.assertTrue(app_record.formatted_code.startswith('AM-APP-'))

    # -------------------------------------------------------------
    # 6. TEST: My Applications page lists candidate's applications
    # -------------------------------------------------------------
    def test_my_applications_page_displays_user_applications(self):
        """Candidate's My Applications page shows their applications with real status from DB."""
        self.login('alice@example.com', 'AlicePass123!')

        # Create paid application for Alice
        app_record = JobApplication(
            job_id=self.job_a.id,
            user_id=self.user_a.id,
            full_name='Alice Sharma',
            email='alice@example.com',
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            payment_status='paid',
            application_status='APPLIED',
            status='APPLIED',
            resume_filename='resume.pdf',
            resume_path='/path/to/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()
        app_record.application_code = f"AM-APP-{app_record.id:06d}"
        db.session.commit()

        res = self.client.get('/my-applications')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn(app_record.formatted_code, html)
        self.assertIn('AI Engineer Intern', html)
        self.assertIn('1 Month', html)
        self.assertIn('Applied', html)
        self.assertIn('Payment: Paid', html)

    # -------------------------------------------------------------
    # 7. TEST: Multiple Applications to different jobs
    # -------------------------------------------------------------
    def test_multiple_applications_for_different_jobs(self):
        """Candidate can apply to Job A and Job B, and both appear on My Applications."""
        self.login('alice@example.com', 'AlicePass123!')

        app_a = JobApplication(
            job_id=self.job_a.id,
            user_id=self.user_a.id,
            full_name='Alice Sharma',
            email='alice@example.com',
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            payment_status='paid',
            application_status='APPLIED',
            status='APPLIED',
            resume_filename='resume.pdf',
            resume_path='/path/to/resume.pdf'
        )
        app_b = JobApplication(
            job_id=self.job_b.id,
            user_id=self.user_a.id,
            full_name='Alice Sharma',
            email='alice@example.com',
            phone='9876543210',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            application_status='UNDER_REVIEW',
            status='UNDER_REVIEW',
            resume_filename='resume.pdf',
            resume_path='/path/to/resume.pdf'
        )
        db.session.add_all([app_a, app_b])
        db.session.commit()

        res = self.client.get('/my-applications')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')
        self.assertIn('AI Engineer Intern', html)
        self.assertIn('Python Developer Intern', html)
        self.assertIn('Applied', html)
        self.assertIn('Under Review', html)

    # -------------------------------------------------------------
    # 8. TEST: Duplicate application protection for the SAME job
    # -------------------------------------------------------------
    def test_duplicate_application_protection_for_same_job(self):
        """User cannot submit duplicate paid application for the same job."""
        self.login('alice@example.com', 'AlicePass123!')

        app_record = JobApplication(
            job_id=self.job_a.id,
            user_id=self.user_a.id,
            full_name='Alice Sharma',
            email='alice@example.com',
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            payment_status='paid',
            application_status='submitted',
            status='New',
            resume_filename='resume.pdf',
            resume_path='/path/to/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()
        app_record.application_code = f"AM-APP-{app_record.id:06d}"
        db.session.commit()

        # Attempt to access apply page again for same job
        res = self.client.get(f'/careers/apply/{self.job_a.id}', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/my-applications', res.headers['Location'])

    # -------------------------------------------------------------
    # 9. TEST: User Data Isolation & Document Privacy
    # -------------------------------------------------------------
    def test_user_data_isolation_and_privacy(self):
        """User A cannot access User B's application or documents."""
        # Create application for User B
        app_b = JobApplication(
            job_id=self.job_b.id,
            user_id=self.user_b.id,
            full_name='Bob Verma',
            email='bob@example.com',
            phone='9123456780',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            application_status='submitted',
            status='New',
            resume_filename='bob_resume.pdf',
            resume_path='/path/to/bob_resume.pdf'
        )
        db.session.add(app_b)
        db.session.commit()

        # Login as User A
        self.login('alice@example.com', 'AlicePass123!')

        # User A views /my-applications -> Bob's app is NOT visible
        res_list = self.client.get('/my-applications')
        self.assertEqual(res_list.status_code, 200)
        self.assertNotIn(b'Bob Verma', res_list.data)

        # User A tries to directly access User B's detail page -> 404 Forbidden
        res_detail = self.client.get(f'/my-applications/{app_b.id}')
        self.assertEqual(res_detail.status_code, 404)

        # User A tries to download User B's resume -> 404 Forbidden
        res_doc = self.client.get(f'/my-applications/{app_b.id}/document/resume')
        self.assertEqual(res_doc.status_code, 404)

    # -------------------------------------------------------------
    # 10. TEST: Admin status update reflects dynamically in candidate view
    # -------------------------------------------------------------
    def test_admin_status_update_reflects_in_my_applications(self):
        """When Admin updates candidate status, My Applications displays the new human-friendly status."""
        app_record = JobApplication(
            job_id=self.job_a.id,
            user_id=self.user_a.id,
            full_name='Alice Sharma',
            email='alice@example.com',
            phone='9876543210',
            duration='1_month',
            application_fee=199,
            payment_status='paid',
            application_status='submitted',
            status='New',
            resume_filename='resume.pdf',
            resume_path='/path/to/resume.pdf'
        )
        db.session.add(app_record)
        db.session.commit()
        app_record.application_code = f"AM-APP-{app_record.id:06d}"
        db.session.commit()

        # Admin logs in and updates status to Reviewed
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        admin_res1 = self.client.post(f'/admin/applications/{app_record.id}/status', data={'status': 'Reviewed'}, follow_redirects=True)
        self.assertEqual(admin_res1.status_code, 200)

        # Alice logs in and checks My Applications -> Under Review
        self.logout()
        self.login('alice@example.com', 'AlicePass123!')
        alice_res1 = self.client.get('/my-applications')
        self.assertIn(b'Under Review', alice_res1.data)

        # Admin updates status to Shortlisted
        self.logout()
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        self.client.post(f'/admin/applications/{app_record.id}/status', data={'status': 'Shortlisted'}, follow_redirects=True)

        # Alice checks again -> Shortlisted
        self.logout()
        self.login('alice@example.com', 'AlicePass123!')
        alice_res2 = self.client.get('/my-applications')
        self.assertIn(b'Shortlisted', alice_res2.data)

        # Admin updates status to Rejected
        self.logout()
        self.login('admin@antimatrix.ai', 'Admin@2026!')
        self.client.post(f'/admin/applications/{app_record.id}/status', data={'status': 'Rejected'}, follow_redirects=True)

        # Alice checks again -> Not Selected
        self.logout()
        self.login('alice@example.com', 'AlicePass123!')
        alice_res3 = self.client.get('/my-applications')
        self.assertIn(b'Not Selected', alice_res3.data)

    # -------------------------------------------------------------
    # 11. TEST: Logout protection
    # -------------------------------------------------------------
    def test_logout_clears_session_and_reprotects_apply(self):
        """Logging out clears session and prevents unauthenticated access to apply/my-applications."""
        self.login('alice@example.com', 'AlicePass123!')
        self.logout()

        # Attempt to access My Applications
        res_my_apps = self.client.get('/my-applications', follow_redirects=False)
        self.assertEqual(res_my_apps.status_code, 302)
        self.assertIn('/login', res_my_apps.headers['Location'])

        # Attempt to access Apply
        res_apply = self.client.get(f'/careers/apply/{self.job_a.id}', follow_redirects=False)
        self.assertEqual(res_apply.status_code, 302)
        self.assertIn('/login', res_apply.headers['Location'])


if __name__ == '__main__':
    unittest.main()
