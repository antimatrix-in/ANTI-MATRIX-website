import os
import io
import unittest
from app import create_app
from models import db, User, JobPosting, JobApplication


class AdminCareersTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for unit test client convenience
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        JobApplication.query.delete()
        db.session.commit()

        # Ensure base jobs exist for testing
        if JobPosting.query.filter_by(title='Senior Full-Stack Engineer').first() is None:
            base_job = JobPosting(
                title='Senior Full-Stack Engineer',
                department='Engineering',
                location='Remote (Worldwide)',
                employment_type='Full-time',
                skills='React, Node.js, PostgreSQL, AWS',
                short_description='Lead the development of complex web applications.',
                description='We are looking for a senior full-stack engineer.',
                is_active=True
            )
            db.session.add(base_job)
            db.session.commit()

        # Create or fetch test admin
        self.admin = User.query.filter_by(email='admin@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(name='Test Admin', email='admin@antimatrix.ai', role='admin', is_active=True)
            self.admin.set_password('Admin@AntiMatrix2026!')
            db.session.add(self.admin)
            db.session.commit()
        else:
            self.admin.role = 'admin'
            self.admin.set_password('Admin@AntiMatrix2026!')
            db.session.commit()

        # Create normal member
        self.member = User.query.filter_by(email='member@example.com').first()
        if not self.member:
            self.member = User(name='Regular Member', email='member@example.com', role='member', is_active=True)
            self.member.set_password('Member@2026!')
            db.session.add(self.member)
            db.session.commit()
        else:
            self.member.role = 'member'
            self.member.set_password('Member@2026!')
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def login_user(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password})

    def logout_user(self):
        return self.client.get('/logout')

    def get_or_create_test_job(self):
        job = JobPosting.query.filter_by(title='AI Research Scientist Intern').first()
        if not job:
            job = JobPosting(
                title='AI Research Scientist Intern',
                department='AI & Data',
                location='Remote (Worldwide)',
                employment_type='Internship',
                duration='3_months',
                short_description='Research and fine-tune next-gen LLMs and multi-modal architectures.',
                description='We are seeking an ambitious AI research intern with deep knowledge in deep learning.',
                skills='PyTorch, Transformers, LLMs, Python',
                requirements='Enrolled in CS / AI degree\nStrong math & linear algebra\nExperience with PyTorch',
                responsibilities='Conduct experiments on open-source LLMs\nPublish internal benchmark papers',
                salary='$45/hr',
                is_active=True
            )
            db.session.add(job)
            db.session.commit()
        elif not job.duration:
            job.duration = '3_months'
            db.session.commit()
        return job

    def test_01_admin_authorization(self):
        """Test admin access restrictions."""
        # 1. Unauthenticated guest accessing /admin -> redirect to login
        res = self.client.get('/admin', follow_redirects=False)
        self.assertIn(res.status_code, [302, 308])

        # 2. Regular user (role='member') accessing /admin -> 403 Forbidden
        self.login_user('member@example.com', 'Member@2026!')
        res = self.client.get('/admin')
        self.assertEqual(res.status_code, 403)
        self.assertIn(b'Access Restricted', res.data)
        self.logout_user()

        # 3. Admin user (role='admin') accessing /admin -> 200 OK
        self.login_user('admin@antimatrix.ai', 'Admin@AntiMatrix2026!')
        res = self.client.get('/admin')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Admin Dashboard', res.data)
        self.assertIn(b'Job Postings', res.data)
        self.logout_user()

    def test_02_job_posting_crud(self):
        """Test creating, reading, editing, toggling, and deleting jobs."""
        self.login_user('admin@antimatrix.ai', 'Admin@AntiMatrix2026!')

        # Clean existing test job if any
        JobPosting.query.filter_by(title='AI Research Scientist Intern').delete()
        db.session.commit()

        # Create Job
        job_data = {
            'title': 'AI Research Scientist Intern',
            'department': 'AI & Data',
            'location': 'Remote (Worldwide)',
            'employment_type': 'Internship',
            'short_description': 'Research and fine-tune next-gen LLMs and multi-modal architectures.',
            'description': 'We are seeking an ambitious AI research intern with deep knowledge in deep learning.',
            'skills': 'PyTorch, Transformers, LLMs, Python',
            'requirements': 'Enrolled in CS / AI degree\nStrong math & linear algebra\nExperience with PyTorch',
            'responsibilities': 'Conduct experiments on open-source LLMs\nPublish internal benchmark papers',
            'salary': '$45/hr',
            'is_active': 'true'
        }
        res = self.client.post('/admin/jobs/create', data=job_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'AI Research Scientist Intern', res.data)

        # Verify job is in DB
        job = JobPosting.query.filter_by(title='AI Research Scientist Intern').first()
        self.assertIsNotNone(job)
        self.assertEqual(job.employment_type, 'Internship')
        self.assertTrue(job.is_active)

        # Edit Job
        edit_data = job_data.copy()
        edit_data['salary'] = '$50/hr'
        edit_data['location'] = 'Remote (US/EU/APAC)'
        res = self.client.post(f'/admin/jobs/edit/{job.id}', data=edit_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        
        db.session.refresh(job)
        self.assertEqual(job.salary, '$50/hr')
        self.assertEqual(job.location, 'Remote (US/EU/APAC)')

        # Toggle Active/Inactive
        res = self.client.post(f'/admin/jobs/toggle/{job.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        db.session.refresh(job)
        self.assertFalse(job.is_active)

        # Toggle back to Active
        self.client.post(f'/admin/jobs/toggle/{job.id}')
        db.session.refresh(job)
        self.assertTrue(job.is_active)

        self.logout_user()

    def test_03_careers_public_rendering(self):
        """Test that public /careers dynamically lists active jobs from DB."""
        self.get_or_create_test_job()
        res = self.client.get('/careers')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Open Positions', res.data)
        self.assertIn(b'AI Research Scientist Intern', res.data)
        self.assertIn(b'Senior Full-Stack Engineer', res.data)

    def test_04_candidate_application_flow(self):
        """Test candidate applying for a job, file upload, duplicate prevention, and success page."""
        job = self.get_or_create_test_job()
        
        # Log in candidate
        self.login_user('member@example.com', 'Member@2026!')

        # Clean previous application with this test email
        JobApplication.query.filter_by(job_id=job.id, email='priya.sharma@example.com').delete()
        db.session.commit()

        # GET apply page
        res = self.client.get(f'/careers/apply/{job.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'AI Research Scientist Intern', res.data)

        # Mock PDF files
        resume_content = b"%PDF-1.4 Mock resume content for candidate Priya Sharma..."
        resume_file = (io.BytesIO(resume_content), 'priya_sharma_resume.pdf')
        aadhaar_file = (io.BytesIO(b"%PDF-1.4 Mock aadhaar"), 'priya_aadhaar.pdf')
        college_id_file = (io.BytesIO(b"%PDF-1.4 Mock college id"), 'priya_college_id.pdf')

        app_data = {
            'first_name': 'Priya',
            'last_name': 'Sharma',
            'full_name': 'Priya Sharma',
            'email': 'priya.sharma@example.com',
            'phone': '9876543210',
            'address': '123 Innovation Drive',
            'state': 'Maharashtra',
            'city': 'Mumbai',
            'pincode': '400001',
            'education_level': "Master's Degree",
            'college': 'Carnegie Mellon University',
            'degree': 'Master of Science',
            'major': 'Computer Science & AI',
            'department': 'Computer Science & AI',
            'year_of_study': 'Recent Graduate',
            'current_cgpa': '3.9',
            'graduation_year': '2025',
            'experience': '1 year research intern',
            'skills': 'PyTorch, Python, NLP, CUDA',
            'portfolio_url': 'https://priyasharma.dev',
            'linkedin_url': 'https://linkedin.com/in/priyasharma',
            'github_url': 'https://github.com/priyasharma',
            'cover_letter': 'I am thrilled to apply for the position at Anti-Matrix.',
            'why_join': 'Anti-Matrix has world-class engineering standards.',
            'resume': resume_file,
            'aadhaar': aadhaar_file,
            'college_id': college_id_file
        }

        res = self.client.post(f'/careers/apply/{job.id}', data=app_data, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/review/', res.headers.get('Location', ''))

        # Verify application in DB
        app_record = JobApplication.query.filter_by(email='priya.sharma@example.com').first()
        self.assertIsNotNone(app_record)
        self.assertEqual(app_record.full_name, 'Priya Sharma')
        self.assertEqual(app_record.job_id, job.id)
        self.assertTrue(os.path.exists(app_record.resume_path))

        # Test Payment Checkout & Verification Flow
        res_checkout = self.client.post(f'/careers/apply/checkout/{app_record.id}', follow_redirects=False)
        self.assertEqual(res_checkout.status_code, 302)
        
        # Simulate Cashfree Return
        payment = app_record.payments[0]
        res_return = self.client.get(f'/payment/cashfree/return?order_id={payment.cashfree_order_id}&sim_status=SUCCESS', follow_redirects=True)
        self.assertEqual(res_return.status_code, 200)
        self.assertIn(b'Application Submitted Successfully', res_return.data)
        self.assertIn(b'AM-APP-', res_return.data)

        # Test duplicate prevention (same email applying to same job when already submitted/paid)
        resume_file2 = (io.BytesIO(resume_content), 'priya_sharma_resume.pdf')
        aadhaar_file2 = (io.BytesIO(b"%PDF-1.4 Mock aadhaar"), 'priya_aadhaar.pdf')
        college_id_file2 = (io.BytesIO(b"%PDF-1.4 Mock college id"), 'priya_college_id.pdf')
        app_data['resume'] = resume_file2
        app_data['aadhaar'] = aadhaar_file2
        app_data['college_id'] = college_id_file2
        res2 = self.client.post(f'/careers/apply/{job.id}', data=app_data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIn(b'already applied', res2.data)

    def test_05_admin_application_management(self):
        """Test admin reviewing applications, updating status, and downloading resumes."""
        job = self.get_or_create_test_job()
        
        # Ensure candidate application exists and is marked paid
        app_record = JobApplication.query.filter_by(email='priya.sharma@example.com').first()
        if not app_record:
            app_record = JobApplication(
                job_id=job.id,
                full_name='Priya Sharma',
                email='priya.sharma@example.com',
                phone='+1 (555) 789-0123',
                college='Carnegie Mellon University',
                degree='Master of Science',
                department='Computer Science & AI',
                graduation_year='2025',
                experience='1 year research intern',
                skills='PyTorch, Python, NLP, CUDA',
                portfolio_url='https://priyasharma.dev',
                linkedin_url='https://linkedin.com/in/priyasharma',
                github_url='https://github.com/priyasharma',
                cover_letter='Cover letter text...',
                resume_filename='test_resume.pdf',
                resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'test_resume.pdf'),
                status='New',
                payment_status='paid',
                application_code='AM-APP-000001'
            )
            os.makedirs(self.app.config['UPLOAD_FOLDER'], exist_ok=True)
            with open(app_record.resume_path, 'wb') as f:
                f.write(b'%PDF-1.4 Mock resume content for download test')
            db.session.add(app_record)
            db.session.commit()
        else:
            app_record.payment_status = 'paid'
            if not app_record.application_code:
                app_record.application_code = f"AM-APP-{app_record.id:06d}"
            db.session.commit()

        self.login_user('admin@antimatrix.ai', 'Admin@AntiMatrix2026!')

        # List applications
        res = self.client.get('/admin/applications')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Priya Sharma', res.data)
        self.assertIn(b'AI Research Scientist Intern', res.data)

        # Filter by status
        res_filter = self.client.get('/admin/applications?status=New')
        self.assertEqual(res_filter.status_code, 200)
        self.assertIn(b'Priya Sharma', res_filter.data)

        # Application Detail
        res_detail = self.client.get(f'/admin/applications/{app_record.id}')
        self.assertEqual(res_detail.status_code, 200)
        self.assertIn(b'Carnegie Mellon University', res_detail.data)
        self.assertIn(b'https://priyasharma.dev', res_detail.data)

        # Update Status: New -> Shortlisted
        res_status = self.client.post(
            f'/admin/applications/{app_record.id}/status',
            data={'status': 'Shortlisted'},
            follow_redirects=True
        )
        db.session.refresh(app_record)
        self.assertIn(app_record.status, ['Shortlisted', 'SHORTLISTED'])
        self.assertEqual(app_record.status_display, 'Shortlisted')

        # Download Resume
        res_resume = self.client.get(f'/admin/applications/{app_record.id}/resume')
        self.assertEqual(res_resume.status_code, 200)

        self.logout_user()

    def test_06_regression_all_routes(self):
        """Verify that all standard site routes still respond with 200."""
        routes = ['/', '/about', '/services', '/pricing', '/careers', '/contact', '/privacy', '/terms', '/login', '/signup']
        for r in routes:
            res = self.client.get(r)
            self.assertEqual(res.status_code, 200, f"Route {r} failed with status {res.status_code}")

    def test_07_clear_all_applications_and_hide_pending(self):
        """Verify that pending applications are hidden and clear-all with DELETE works while preserving jobs."""
        job = self.get_or_create_test_job()

        # Create 1 pending application and 1 paid application
        pending_app = JobApplication(
            job_id=job.id,
            full_name='Pending Candidate',
            email='pending.cand@example.com',
            phone='+1 (555) 000-1111',
            payment_status='pending',
            status='New',
            resume_filename='test_pending.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'test_pending.pdf')
        )
        paid_app = JobApplication(
            job_id=job.id,
            full_name='Paid Candidate',
            email='paid.cand@example.com',
            phone='+1 (555) 000-2222',
            payment_status='paid',
            application_code='AM-APP-000099',
            status='New',
            resume_filename='test_paid.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'test_paid.pdf')
        )
        db.session.add_all([pending_app, paid_app])
        db.session.commit()

        self.login_user('admin@antimatrix.ai', 'Admin@AntiMatrix2026!')

        # 1. Verify pending application is hidden and paid application is shown
        res = self.client.get('/admin/applications')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Paid Candidate', res.data)
        self.assertNotIn(b'Pending Candidate', res.data)
        self.assertIn(b'AM-APP-000099', res.data)
        self.assertIn(b'Paid', res.data)

        # 2. Attempt to clear all without typing DELETE
        res_invalid = self.client.post('/admin/applications/clear-all', data={'confirmation': 'NO'}, follow_redirects=True)
        self.assertIn(b'You must type DELETE to confirm', res_invalid.data)
        self.assertGreater(JobApplication.query.count(), 0)

        # 3. Clear all with confirmation = DELETE
        job_count_before = JobPosting.query.count()
        res_clear = self.client.post('/admin/applications/clear-all', data={'confirmation': 'DELETE'}, follow_redirects=True)
        self.assertIn(b'cleared successfully', res_clear.data)
        self.assertEqual(JobApplication.query.count(), 0)
        # Job postings must be strictly preserved
        self.assertEqual(JobPosting.query.count(), job_count_before)

        self.logout_user()


if __name__ == '__main__':
    unittest.main()

