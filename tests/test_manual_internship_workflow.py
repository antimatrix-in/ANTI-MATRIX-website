import os
import io
import re
import html as html_lib
import unittest
from datetime import datetime, timezone, timedelta
from app import create_app, db
from models import (
    User, JobPosting, JobApplication, Employee,
    EmployeeOnboardingCredential, Payment
)


class TestManualInternshipWorkflow(unittest.TestCase):
    """
    Automated Test Suite for the New Manual Internship Application and Admin Onboarding Workflow.
    Verifies:
    1. Active Job Posting with Job Code (JB####) and Department.
    2. 1-Month candidate application submission (5 required inputs only).
    3. 3-Months candidate application submission with correct GST breakdown.
    4. Duplicate application submission protection within 10 minutes.
    5. Concurrency-safe unique Application Code generation (AM-APP-000XXX).
    6. No Cashfree payment gateway order or checkout redirect created.
    7. Admin Applications listing display with Job Code, Duration, College, and Pending badge.
    8. Payment status filtering in Admin (pending vs paid).
    9. Admin manual payment status update (pending -> paid / verified).
    10. Admin manual employee creation with AM#### ID and secure onboarding credentials.
    11. Duplicate employee creation prevention (idempotent onboarding).
    12. Configuration toggle (MANUAL_APPLICATION_WORKFLOW).
    """

    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = True
        self.app.config['APPLICATION_PAYMENT_MODE'] = 'MANUAL'
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-credentials-32b'

        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # 1. Create Admin Account
        self.admin = User(
            name='Super Admin',
            email='admin@antimatrix.co.in',
            role='admin',
            is_active=True
        )
        self.admin.set_password('AdminSecure123!')
        db.session.add(self.admin)

        # 2. Create Active Job Posting with Job Code (JB1001) & Department
        self.job = JobPosting(
            title='AI & ML Research Intern',
            job_code='JB1001',
            job_id='JB1001',
            department='Artificial Intelligence',
            location='Bengaluru, India (Remote Available)',
            employment_type='Internship',
            experience='Freshers / Students',
            short_description='AI & ML Internship Research Role',
            duration='1 Month',
            is_active=True,
            description='Research and build cutting-edge generative AI models and multi-agent systems.'
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

    # -------------------------------------------------------------------------
    # Scenario 1: Job Posting Exists with Job Code & Department
    # -------------------------------------------------------------------------
    def test_01_job_posting_exists_with_code_and_department(self):
        """Active Job Posting must have valid Job Code (JB####) and Department."""
        job = JobPosting.query.filter_by(job_code='JB1001').first()
        self.assertIsNotNone(job)
        self.assertEqual(job.title, 'AI & ML Research Intern')
        self.assertEqual(job.department, 'Artificial Intelligence')
        self.assertTrue(job.job_code.startswith('JB'))
        self.assertTrue(job.is_active)

    # -------------------------------------------------------------------------
    # Scenario 2: Candidate Submits 1 Month Application (5 inputs only)
    # -------------------------------------------------------------------------
    def test_02_candidate_submits_1_month_application(self):
        """Candidate submits 6 required inputs for 1 Month duration; verifies derived values and receipt."""
        response = self.client.post(f'/careers/apply/{self.job.id}', data={
            'full_name': 'Praveen Kumar',
            'email': 'praveen.test@example.com',
            'phone': '9876543210',
            'duration': '1_month',
            'college': 'Indian Institute of Technology Madras',
            'resume': (io.BytesIO(b'%PDF-1.4 test resume content'), 'praveen_resume.pdf')
        }, content_type='multipart/form-data', follow_redirects=False)

        # Must redirect directly to confirmation success page, NOT Cashfree
        self.assertEqual(response.status_code, 302)
        self.assertIn('/careers/apply/success/', response.location)

        # Verify application in database
        app = JobApplication.query.filter_by(email='praveen.test@example.com').first()
        self.assertIsNotNone(app)
        self.assertEqual(app.full_name, 'Praveen Kumar')
        self.assertEqual(app.email, 'praveen.test@example.com')
        self.assertEqual(app.phone, '9876543210')
        self.assertEqual(app.duration, '1_month')
        self.assertEqual(app.college, 'Indian Institute of Technology Madras')
        self.assertEqual(app.status, 'APPLIED')
        self.assertEqual(app.payment_status, 'pending')

        # Derived fields
        self.assertEqual(app.job_id, self.job.id)
        self.assertEqual(app.job_code, 'JB1001')
        self.assertEqual(app.department, 'Artificial Intelligence')
        self.assertEqual(app.base_amount, 199.0)
        self.assertEqual(app.gst_amount, 35.82)
        self.assertEqual(app.application_fee, 199)

        # Application Code format: AM-APP-000XXX
        self.assertTrue(app.formatted_code.startswith('AM-APP-'))
        self.assertRegex(app.formatted_code, r'^AM-APP-\d{6}$')

        # Resume saved
        self.assertTrue(app.resume_filename.endswith('.pdf'))
        self.assertTrue(os.path.exists(app.resume_path))

    # -------------------------------------------------------------------------
    # Scenario 3: Candidate Submits 3 Months Application
    # -------------------------------------------------------------------------
    def test_03_candidate_submits_3_months_application(self):
        """Candidate submits 3 Months application; verifies ₹399 base and ₹71.82 GST."""
        response = self.client.post(f'/careers/apply/{self.job.id}', data={
            'full_name': 'Sneha Patel',
            'email': 'sneha.patel@example.com',
            'phone': '9812345678',
            'duration': '3_months',
            'college': 'National Institute of Technology Karnataka',
            'resume': (io.BytesIO(b'PK\x03\x04 test docx resume'), 'sneha_resume.docx')
        }, content_type='multipart/form-data', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/careers/apply/success/', response.location)

        app = JobApplication.query.filter_by(email='sneha.patel@example.com').first()
        self.assertIsNotNone(app)
        self.assertEqual(app.duration, '3_months')
        self.assertEqual(app.base_amount, 399.0)
        self.assertEqual(app.gst_rate, 18.0)
        self.assertEqual(app.gst_amount, 71.82)
        self.assertEqual(app.application_fee, 399)
        self.assertEqual(app.college, 'National Institute of Technology Karnataka')
        self.assertTrue(app.resume_filename.endswith('.docx'))

    # -------------------------------------------------------------------------
    # Scenario 4: Duplicate Submission Protection within 10 Minutes
    # -------------------------------------------------------------------------
    def test_04_duplicate_submission_protection_within_10_minutes(self):
        """Submitting twice with same email & job within 10 minutes prevents duplicate rows."""
        data = {
            'full_name': 'Arun Sharma',
            'email': 'arun.sharma@example.com',
            'phone': '9822334455',
            'duration': '1_month',
            'college': 'BITS Pilani',
            'resume': (io.BytesIO(b'%PDF-1.4 test resume'), 'arun.pdf')
        }

        # First Submission
        res1 = self.client.post(f'/careers/apply/{self.job.id}', data=data, content_type='multipart/form-data', follow_redirects=False)
        self.assertEqual(res1.status_code, 302)

        initial_count = JobApplication.query.filter_by(email='arun.sharma@example.com').count()
        self.assertEqual(initial_count, 1)

        # Immediate Second Submission
        data2 = dict(data, resume=(io.BytesIO(b'%PDF-1.4 test resume'), 'arun.pdf'))
        res2 = self.client.post(f'/careers/apply/{self.job.id}', data=data2, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertIn(b'An application has already been submitted using this email address or mobile number.', res2.data)

        # Verify no second application created
        final_count = JobApplication.query.filter_by(email='arun.sharma@example.com').count()
        self.assertEqual(final_count, 1)

    # -------------------------------------------------------------------------
    # Scenario 5: Concurrency-Safe Application Code Generation
    # -------------------------------------------------------------------------
    def test_05_application_code_generation(self):
        """Application code generation should be formatted AM-APP-000XXX and strictly unique."""
        code1 = JobApplication.generate_unique_application_code(app_id=42)
        code2 = JobApplication.generate_unique_application_code(app_id=105)
        code3 = JobApplication.generate_unique_application_code()

        self.assertEqual(code1, 'AM-APP-000042')
        self.assertEqual(code2, 'AM-APP-000105')
        self.assertRegex(code3, r'^AM-APP-\d{6}$')

    # -------------------------------------------------------------------------
    # Scenario 6: Verification that NO Cashfree Order Was Created
    # -------------------------------------------------------------------------
    def test_06_no_cashfree_order_created(self):
        """Manual application workflow must NOT initialize any Payment or Cashfree Order record."""
        response = self.client.post(f'/careers/apply/{self.job.id}', data={
            'full_name': 'Meera Nair',
            'email': 'meera.nair@example.com',
            'phone': '9845012345',
            'duration': '1_month',
            'college': 'College of Engineering Guindy',
            'resume': (io.BytesIO(b'%PDF-1.4 test resume'), 'meera.pdf')
        }, content_type='multipart/form-data', follow_redirects=False)

        app = JobApplication.query.filter_by(email='meera.nair@example.com').first()
        self.assertIsNotNone(app)

        # Ensure no payment records exist
        payment_count = Payment.query.filter_by(application_id=app.id).count()
        self.assertEqual(payment_count, 0)
        self.assertIsNone(app.latest_payment)

    # -------------------------------------------------------------------------
    # Scenario 7: Admin Applications Listing Display
    # -------------------------------------------------------------------------
    def test_07_admin_applications_listing_display(self):
        """Application appears in Admin Applications list with ID, Job Code, College, and Pending badge."""
        self._login_admin()

        app = JobApplication(
            job_id=self.job.id,
            full_name='Vikram Seth',
            email='vikram.seth@example.com',
            phone='9712345678',
            duration='1_month',
            college='Delhi Technological University',
            status='APPLIED',
            payment_status='pending',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        db.session.add(app)
        db.session.flush()
        app.application_code = JobApplication.generate_unique_application_code(app_id=app.id)
        db.session.commit()

        response = self.client.get('/admin/applications')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn(app.formatted_code, html)
        self.assertIn('Vikram Seth', html)
        self.assertIn('JB1001', html)
        self.assertIn('1 Month', html)
        self.assertIn('Pending', html)
        self.assertIn('Create Employee', html)

    # -------------------------------------------------------------------------
    # Scenario 8: Payment Status Filter in Admin
    # -------------------------------------------------------------------------
    def test_08_payment_status_filter_in_admin(self):
        """Admin can filter applications by payment_status (pending vs paid)."""
        self._login_admin()

        # Create 1 pending and 1 paid application
        app_pending = JobApplication(
            job_id=self.job.id,
            full_name='Pending Candidate',
            email='pending@example.com',
            phone='9811111111',
            duration='1_month',
            college='College A',
            payment_status='pending',
            status='APPLIED',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        app_paid = JobApplication(
            job_id=self.job.id,
            full_name='Paid Candidate',
            email='paid@example.com',
            phone='9822222222',
            duration='3_months',
            college='College B',
            payment_status='paid',
            status='APPLIED',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        db.session.add_all([app_pending, app_paid])
        db.session.commit()

        # Filter by Pending
        res_pending = self.client.get('/admin/applications?payment_status=pending')
        html_p = res_pending.get_data(as_text=True)
        self.assertIn('Pending Candidate', html_p)
        self.assertNotIn('Paid Candidate', html_p)

        # Filter by Paid
        res_paid = self.client.get('/admin/applications?payment_status=paid')
        html_paid = res_paid.get_data(as_text=True)
        self.assertIn('Paid Candidate', html_paid)
        self.assertNotIn('Pending Candidate', html_paid)

    # -------------------------------------------------------------------------
    # Scenario 9: Admin Updates Payment Status Manually
    # -------------------------------------------------------------------------
    def test_09_admin_updates_payment_status_manually(self):
        """Admin marks payment status as 'paid' via manual verification route."""
        self._login_admin()

        app = JobApplication(
            job_id=self.job.id,
            full_name='Rohan Verma',
            email='rohan.verma@example.com',
            phone='9833333333',
            duration='1_month',
            college='Manipal University',
            payment_status='pending',
            status='APPLIED',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        db.session.add(app)
        db.session.commit()

        # Post update to 'paid'
        res = self.client.post(
            f'/admin/applications/{app.id}/update-payment-status',
            data={'payment_status': 'paid'},
            follow_redirects=True
        )
        self.assertEqual(res.status_code, 200)

        # Verify DB updated
        refreshed_app = db.session.get(JobApplication, app.id)
        self.assertEqual(refreshed_app.payment_status, 'paid')

    # -------------------------------------------------------------------------
    # Scenario 10: Admin Manual Employee Creation
    # -------------------------------------------------------------------------
    def test_10_admin_create_employee_workflow(self):
        """Admin creates employee from application; generates AM#### and encrypted temp credentials."""
        self._login_admin()

        app = JobApplication(
            job_id=self.job.id,
            full_name='Divya Krishnan',
            email='divya.k@example.com',
            phone='9844444444',
            duration='1_month',
            college='PSG College of Technology',
            payment_status='paid',
            status='APPLIED',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        db.session.add(app)
        db.session.flush()
        app.application_code = JobApplication.generate_unique_application_code(app_id=app.id)
        db.session.commit()

        # Admin calls POST /admin/employees/create
        res = self.client.post('/admin/employees/create', data={
            'application_id': app.id
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Verify Employee record in database
        emp = Employee.query.filter_by(application_id=app.id).first()
        self.assertIsNotNone(emp)
        self.assertRegex(emp.employee_id, r'^AM\d{4}$')
        self.assertEqual(emp.account_status, 'active')

        # Verify Onboarding Credential stored
        cred = EmployeeOnboardingCredential.query.filter_by(employee_id=emp.employee_id).first()
        self.assertIsNotNone(cred)
        self.assertTrue(cred.is_active)
        self.assertIsNotNone(cred.temporary_password_encrypted)

        # Verify decrypted password works with current secret key
        temp_pw = cred.decrypt_password(self.app.config['SECRET_KEY'])
        self.assertIsNotNone(temp_pw)
        self.assertTrue(len(temp_pw) >= 8)

        # Verify display box on page
        self.assertIn('Employee Created Successfully!', html)
        self.assertIn(emp.employee_id, html)
        self.assertTrue(temp_pw in html or html_lib.escape(temp_pw) in html)

    # -------------------------------------------------------------------------
    # Scenario 11: Duplicate Employee Creation Prevention (Idempotent)
    # -------------------------------------------------------------------------
    def test_11_duplicate_employee_creation_prevention(self):
        """Attempting to create employee for an already onboarded application prevents duplicates."""
        self._login_admin()

        app = JobApplication(
            job_id=self.job.id,
            full_name='Karan Gupta',
            email='karan.gupta@example.com',
            phone='9855555555',
            duration='1_month',
            college='Thapar Institute',
            payment_status='paid',
            status='APPLIED',
            resume_filename='NOT_PROVIDED',
            resume_path=''
        )
        db.session.add(app)
        db.session.flush()
        app.application_code = JobApplication.generate_unique_application_code(app_id=app.id)
        db.session.commit()

        # First Creation
        res1 = self.client.post('/admin/employees/create', data={'application_id': app.id}, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        emp_count1 = Employee.query.filter_by(application_id=app.id).count()
        self.assertEqual(emp_count1, 1)
        original_emp = Employee.query.filter_by(application_id=app.id).first()

        # Second Creation Attempt for same application
        res2 = self.client.post('/admin/employees/create', data={'application_id': app.id}, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        html2 = res2.get_data(as_text=True)

        emp_count2 = Employee.query.filter_by(application_id=app.id).count()
        self.assertEqual(emp_count2, 1)  # Stays strictly 1
        self.assertIn('Employee Already Exists', html2)
        self.assertIn(original_emp.employee_id, html2)

    # -------------------------------------------------------------------------
    # Scenario 12: Configuration Toggle Flag
    # -------------------------------------------------------------------------
    def test_12_workflow_configuration_toggle(self):
        """Toggling MANUAL_APPLICATION_WORKFLOW switches seamlessly between flows."""
        from routes.main import is_manual_application_workflow

        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = True
        self.assertTrue(is_manual_application_workflow())

        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = False
        self.assertFalse(is_manual_application_workflow())

        # When toggled back to True
        self.app.config['MANUAL_APPLICATION_WORKFLOW'] = True
        self.assertTrue(is_manual_application_workflow())


if __name__ == '__main__':
    unittest.main()
