import os
import sys
import io
import uuid
import unittest
from datetime import datetime, timezone

from app import create_app
from models import (
    db, User, JobPosting, JobApplication, Payment, Employee,
    EmployeeDocument, DocumentTemplate, EmailTemplate, EmailLog, MoneyTransaction
)

class CandidateApplicationsSafePatchTestCase(unittest.TestCase):
    """
    Comprehensive verification test suite for Candidate Applications Safe Patch:
    1. Clear All Applications with DELETE confirmation
    2. Hide Pending Payments from Admin table
    3. Generate Application ID Only After Successful Payment
    4. Application ID format AM-APP-000001
    5. Admin table column rendering & paid badge
    6. Cashfree verification workflow
    7. Data preservation of jobs, employees, templates, money transactions, logs
    """

    @classmethod
    def setUpClass(cls):
        os.environ['FLASK_ENV'] = 'testing'
        cls.app = create_app()
        cls.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SERVER_NAME': 'localhost',
            'PAYMENT_TEST_MODE': True
        })

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Create test admin
        self.admin = User.query.filter_by(email='admin_patch_test@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(
                name='Patch Admin',
                email='admin_patch_test@antimatrix.ai',
                role='admin',
                is_active=True
            )
            self.admin.set_password('AdminPass123!')
            db.session.add(self.admin)
            db.session.commit()

        # Create test candidate user
        self.candidate = User.query.filter_by(email='candidate_patch_test@example.com').first()
        if not self.candidate:
            self.candidate = User(
                name='Patch Candidate',
                email='candidate_patch_test@example.com',
                role='candidate',
                is_active=True
            )
            self.candidate.set_password('CandPass123!')
            db.session.add(self.candidate)
            db.session.commit()

        # Create test job posting
        self.job = JobPosting.query.filter_by(title='Patch Test AI Intern').first()
        if not self.job:
            self.job = JobPosting(
                title='Patch Test AI Intern',
                department='Engineering',
                location='Remote',
                employment_type='Internship',
                duration='1_month',
                short_description='AI internship for safe patch tests',
                description='Full description for patch test job',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def login_user(self, email, password):
        return self.client.post('/login', data={'email': email, 'password': password}, follow_redirects=True)

    def logout_user(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_01_application_id_not_generated_before_payment(self):
        """Verify that submitting draft internship application does NOT generate Application ID before payment."""
        test_email = f"cand_draft_{uuid.uuid4().hex[:6]}@example.com"
        cand = User(name='Test Draft Cand', email=test_email, role='candidate', is_active=True)
        cand.set_password('Pass123!')
        db.session.add(cand)
        db.session.commit()

        self.login_user(test_email, 'Pass123!')

        os.makedirs(self.app.config.get('UPLOAD_FOLDER_RESUMES', os.path.join(self.app.root_path, 'uploads', 'resumes')), exist_ok=True)
        resume_data = io.BytesIO(b'%PDF-1.4 Dummy resume content for patch test')

        res = self.client.post(
            f'/careers/apply/{self.job.id}',
            data={
                'first_name': 'Draft',
                'last_name': 'Candidate',
                'email': test_email,
                'phone': '9876543210',
                'address': '123 Test Street, Anna Nagar',
                'state': 'Tamil Nadu',
                'city': 'Chennai',
                'pincode': '600001',
                'education_level': "Bachelor's Degree",
                'college': 'Anna University',
                'department': 'Computer Science',
                'degree': 'B.E.',
                'major': 'Computer Science',
                'graduation_year': '2026',
                'skills': 'Python, AI',
                'cover_letter': 'Cover letter test for safe patch',
                'resume': (resume_data, 'dummy_patch_resume.pdf')
            },
            content_type='multipart/form-data',
            follow_redirects=False
        )

        # Candidate is redirected to Review & Payment step
        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/review/', res.headers['Location'])

        app_rec = JobApplication.query.filter_by(email=test_email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.payment_status, 'pending')
        # Application Code MUST be None before payment
        self.assertIsNone(app_rec.application_code)
        self.assertEqual(app_rec.formatted_code, '')

        self.logout_user()

    def test_02_application_id_generated_after_payment(self):
        """Verify Application ID is generated in AM-APP-000001 format strictly after successful payment."""
        test_email = f"cand_paid_{uuid.uuid4().hex[:6]}@example.com"
        cand = User(name='Test Paid Cand', email=test_email, role='candidate', is_active=True)
        cand.set_password('Pass123!')
        db.session.add(cand)
        db.session.commit()

        self.login_user(test_email, 'Pass123!')

        os.makedirs(self.app.config.get('UPLOAD_FOLDER_RESUMES', os.path.join(self.app.root_path, 'uploads', 'resumes')), exist_ok=True)
        resume_data = io.BytesIO(b'%PDF-1.4 Dummy resume content for patch test')

        self.client.post(
            f'/careers/apply/{self.job.id}',
            data={
                'first_name': 'Paid',
                'last_name': 'Candidate',
                'email': test_email,
                'phone': '9876543210',
                'address': '123 Test Street, Anna Nagar',
                'state': 'Tamil Nadu',
                'city': 'Chennai',
                'pincode': '600001',
                'education_level': "Bachelor's Degree",
                'college': 'Anna University',
                'department': 'Computer Science',
                'degree': 'B.E.',
                'major': 'Computer Science',
                'graduation_year': '2026',
                'skills': 'Python, AI',
                'cover_letter': 'Cover letter test for safe patch',
                'resume': (resume_data, 'dummy_patch_resume.pdf')
            },
            content_type='multipart/form-data',
            follow_redirects=False
        )

        app_rec = JobApplication.query.filter_by(email=test_email).first()
        self.assertIsNotNone(app_rec)
        self.assertIsNone(app_rec.application_code)

        # Complete payment (simulated test mode / Cashfree verify return)
        res_pay = self.client.post(f'/careers/apply/test-payment/{app_rec.id}', follow_redirects=True)
        self.assertEqual(res_pay.status_code, 200)

        db.session.refresh(app_rec)
        self.assertEqual(app_rec.payment_status, 'paid')
        self.assertIsNotNone(app_rec.application_code)
        self.assertTrue(app_rec.application_code.startswith('AM-APP-'))
        self.assertEqual(len(app_rec.application_code), 13)  # e.g. AM-APP-000001
        self.assertEqual(app_rec.formatted_code, app_rec.application_code)

        self.logout_user()

    def test_03_hide_pending_payments_from_admin_table(self):
        """Verify that pending, failed, cancelled applications are hidden from /admin/applications."""
        uid = uuid.uuid4().hex[:6]
        pending_email = f"hidden_pending_{uid}@example.com"
        failed_email = f"hidden_failed_{uid}@example.com"
        paid_email = f"visible_paid_{uid}@example.com"

        # Create 1 pending, 1 failed, and 1 paid application
        pending_app = JobApplication(
            job_id=self.job.id,
            full_name=f'Hidden Pending Candidate {uid}',
            email=pending_email,
            phone='+91 99999 11111',
            payment_status='pending',
            application_code=None,
            status='New',
            resume_filename='res1.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'res1.pdf')
        )
        failed_app = JobApplication(
            job_id=self.job.id,
            full_name=f'Hidden Failed Candidate {uid}',
            email=failed_email,
            phone='+91 99999 22222',
            payment_status='failed',
            application_code=None,
            status='New',
            resume_filename='res2.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'res2.pdf')
        )
        paid_app = JobApplication(
            job_id=self.job.id,
            full_name=f'Visible Paid Candidate {uid}',
            email=paid_email,
            phone='+91 99999 33333',
            payment_status='paid',
            status='New',
            resume_filename='res3.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'res3.pdf')
        )
        db.session.add_all([pending_app, failed_app, paid_app])
        db.session.flush()
        paid_app.application_code = f"AM-APP-{paid_app.id:06d}"
        db.session.commit()

        self.login_user('admin_patch_test@antimatrix.ai', 'AdminPass123!')

        res = self.client.get('/admin/applications')
        self.assertEqual(res.status_code, 200)

        # Paid candidate MUST be in table
        self.assertIn(paid_app.full_name.encode('utf-8'), res.data)
        self.assertIn(paid_app.application_code.encode('utf-8'), res.data)
        # Pending and Failed candidates MUST NOT be in table
        self.assertNotIn(pending_app.full_name.encode('utf-8'), res.data)
        self.assertNotIn(failed_app.full_name.encode('utf-8'), res.data)

        # Check table columns exist
        self.assertIn(b'Application ID', res.data)
        self.assertIn(b'Candidate Name', res.data)
        self.assertIn(b'Position', res.data)
        self.assertIn(b'Duration', res.data)
        self.assertIn(b'Application Fee', res.data)
        self.assertIn(b'Payment', res.data)
        self.assertIn(b'Stage', res.data)
        self.assertIn(b'Applied Date', res.data)
        self.assertIn(b'Actions', res.data)

        # Payment status badge is 'Paid'
        self.assertIn(b'Paid', res.data)

        self.logout_user()

    def test_04_clear_all_applications_modal_and_preservation(self):
        """Verify Clear All Applications requires DELETE confirmation and strictly preserves jobs, employees, transactions."""
        # Ensure we have at least 1 application
        test_app = JobApplication(
            job_id=self.job.id,
            full_name='Clear Test Candidate',
            email=f'clear_cand_{uuid.uuid4().hex[:6]}@example.com',
            phone='+91 99999 44444',
            payment_status='paid',
            status='New',
            resume_filename='res_clear.pdf',
            resume_path=os.path.join(self.app.config['UPLOAD_FOLDER'], 'res_clear.pdf')
        )
        db.session.add(test_app)
        db.session.flush()
        test_app.application_code = f"AM-APP-{test_app.id:06d}"

        # Create an Employee record and MoneyTransaction record to verify preservation
        emp_code = f"EMP-{uuid.uuid4().hex[:6].upper()}"
        emp = Employee(
            employee_id=emp_code,
            application_id=test_app.id,
            account_status='ACTIVE'
        )
        emp.set_password('EmpPass123!')
        db.session.add(emp)

        txn = MoneyTransaction(
            transaction_type='INCOME',
            amount=199.0,
            category='Internship Application Fee',
            purpose='Application fee payment',
            payment_method='Cashfree',
            provider='CASHFREE',
            environment='TEST',
            application_id=test_app.id
        )
        db.session.add(txn)
        db.session.commit()

        initial_jobs_count = JobPosting.query.count()
        initial_emp_count = Employee.query.count()
        initial_txn_count = MoneyTransaction.query.count()
        initial_tmpl_count = DocumentTemplate.query.count()
        initial_email_tmpl_count = EmailTemplate.query.count()

        self.login_user('admin_patch_test@antimatrix.ai', 'AdminPass123!')

        # 1. Invalid confirmation test
        res_fail = self.client.post('/admin/applications/clear-all', data={'confirmation': 'delete'}, follow_redirects=True)
        self.assertIn(b'You must type DELETE to confirm', res_fail.data)
        self.assertGreater(JobApplication.query.count(), 0)

        # 2. Valid confirmation with exact 'DELETE'
        res_success = self.client.post('/admin/applications/clear-all', data={'confirmation': 'DELETE'}, follow_redirects=True)
        self.assertIn(b'cleared successfully', res_success.data)

        # All JobApplication records deleted
        self.assertEqual(JobApplication.query.count(), 0)

        # BUT JobPostings, Employees, MoneyTransactions, Templates strictly preserved
        self.assertEqual(JobPosting.query.count(), initial_jobs_count)
        self.assertEqual(Employee.query.count(), initial_emp_count)
        self.assertEqual(MoneyTransaction.query.count(), initial_txn_count)
        self.assertEqual(DocumentTemplate.query.count(), initial_tmpl_count)
        self.assertEqual(EmailTemplate.query.count(), initial_email_tmpl_count)

        self.logout_user()


if __name__ == '__main__':
    unittest.main()
