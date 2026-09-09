"""
Comprehensive Lifecycle Test for Anti-Matrix Employee Onboarding Credentials System.
Strictly validates Tests 1 through 10 in an isolated in-memory test environment.
"""

import html
import unittest
from datetime import datetime, timezone
from app import create_app
from models import db, User, JobPosting, JobApplication, Employee, EmployeeOnboardingCredential
from services.email_service import render_joining_credentials_email, send_joining_credentials_email


class EmployeeOnboardingCredentialLifecycleTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['SECRET_KEY'] = 'test-secret-key-antimatrix-2026-onboarding'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Retrieve or create test Admin
        self.admin = User.query.filter_by(email='admin@antimatrix.ai').first()
        if not self.admin:
            self.admin = User(
                name='Test Admin',
                email='admin@antimatrix.ai',
                role='admin',
                is_active=True
            )
            db.session.add(self.admin)
        else:
            self.admin.role = 'admin'
            self.admin.is_active = True
        self.admin.set_password('AdminSecurePass123!')

        # Create sample Job Posting
        self.job = JobPosting(
            title='AI Research Scientist Intern',
            department='AI & Data',
            location='Remote',
            employment_type='Internship',
            duration='3_months',
            short_description='AI Research',
            description='Full AI Research description',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

        # Create sample Job Application
        self.application = JobApplication(
            job_id=self.job.id,
            full_name='Rohan Mehra',
            first_name='Rohan',
            last_name='Mehra',
            email='rohan.mehra@example.com',
            phone='+919876543210',
            resume_filename='rohan_resume.pdf',
            resume_path='uploads/resumes/rohan_resume.pdf',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            application_status='SHORTLISTED',
            status='SHORTLISTED'
        )
        db.session.add(self.application)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _login(self, email, password):
        return self.client.post('/login', data={
            'email': email,
            'password': password
        }, follow_redirects=True)

    def _logout(self):
        return self.client.get('/logout', follow_redirects=True)

    def test_complete_onboarding_credential_lifecycle_1_to_10(self):
        secret_key = self.app.config['SECRET_KEY']

        # =====================================================================
        # TEST 1: Employee created -> Employee ID generated, temporary password
        # generated, onboarding credential row created, status ACTIVE
        # =====================================================================
        emp_id = Employee.generate_unique_employee_id()
        plaintext_temp_password = Employee.generate_secure_password(12)

        employee = Employee(
            employee_id=emp_id,
            application_id=self.application.id,
            account_status='active'
        )
        employee.set_password(plaintext_temp_password)
        employee.set_temp_password(plaintext_temp_password, secret_key)
        db.session.add(employee)
        db.session.commit()

        # Verify onboarding credential table record
        cred_row = EmployeeOnboardingCredential.query.filter_by(employee_id=emp_id).first()
        self.assertIsNotNone(cred_row, "Onboarding credential record was not created")
        self.assertEqual(cred_row.employee_id, emp_id)
        self.assertEqual(cred_row.status, 'ACTIVE')
        self.assertIsNone(cred_row.password_reset_at)
        self.assertIsNotNone(cred_row.temporary_password_encrypted)
        self.assertIsNotNone(cred_row.temporary_password_hash)
        self.assertNotEqual(cred_row.temporary_password_encrypted, plaintext_temp_password)
        self.assertNotEqual(cred_row.temporary_password_hash, plaintext_temp_password)
        self.assertTrue(cred_row.is_active)

        # Verify 1-to-1 relationship from Employee
        self.assertIsNotNone(employee.onboarding_credential)
        self.assertEqual(employee.onboarding_credential.id, cred_row.id)
        self.assertTrue(employee.is_temporary_password_active)
        self.assertEqual(employee.get_temp_password(secret_key), plaintext_temp_password)

        # =====================================================================
        # TEST 2: Joining Email generated -> exact Employee ID appears,
        # exact temporary password appears
        # =====================================================================
        rendered_email = render_joining_credentials_email(self.application)
        self.assertIn(emp_id, rendered_email['body_text'])
        self.assertIn(plaintext_temp_password, rendered_email['body_text'])
        self.assertIn(emp_id, rendered_email['body_html'])
        self.assertIn(plaintext_temp_password, rendered_email['body_html'])

        # =====================================================================
        # TEST 3: Joining Email retry -> same Employee ID, same temporary password,
        # no duplicate credential row
        # =====================================================================
        # Pre-count credential rows
        initial_cred_count = EmployeeOnboardingCredential.query.filter_by(employee_id=emp_id).count()
        self.assertEqual(initial_cred_count, 1)

        # Re-render email (simulation of retry)
        rendered_retry = render_joining_credentials_email(self.application)
        self.assertIn(emp_id, rendered_retry['body_text'])
        self.assertIn(plaintext_temp_password, rendered_retry['body_text'])

        # Verify no duplicate credential row was created
        post_cred_count = EmployeeOnboardingCredential.query.filter_by(employee_id=emp_id).count()
        self.assertEqual(post_cred_count, 1, "Duplicate onboarding credential row detected on retry!")

        # Verify retry uses the same active credential
        active_cred = EmployeeOnboardingCredential.query.filter_by(employee_id=emp_id).first()
        self.assertEqual(active_cred.decrypt_password(secret_key), plaintext_temp_password)
        self.assertEqual(active_cred.status, 'ACTIVE')

        # =====================================================================
        # TEST 4: Internship Portal enters correct credentials -> authentication succeeds
        # =====================================================================
        self.assertTrue(
            active_cred.verify_password(plaintext_temp_password),
            "Internship Portal verification of correct temporary password failed"
        )
        # Also test via web login
        res_cand_login = self._login(emp_id, plaintext_temp_password)
        self.assertEqual(res_cand_login.status_code, 200)
        self.assertTrue(b'Log Out' in res_cand_login.data or b'/logout' in res_cand_login.data)
        self._logout()

        # =====================================================================
        # TEST 5: Internship Portal enters wrong password -> authentication fails
        # =====================================================================
        self.assertFalse(
            active_cred.verify_password("IncorrectTempPassword123!"),
            "Internship Portal should fail on wrong password"
        )
        res_wrong_login = self._login(emp_id, "IncorrectTempPassword123!")
        self.assertIn(b'Invalid Employee ID or password', res_wrong_login.data)

        # =====================================================================
        # TEST 6: Employee successfully resets password ->
        # onboarding credential status becomes RESET
        # =====================================================================
        new_permanent_password = "MyNewPermanentPassword2026!#"
        employee.reset_password(new_permanent_password)
        db.session.commit()

        refreshed_cred = EmployeeOnboardingCredential.query.filter_by(employee_id=emp_id).first()
        self.assertEqual(refreshed_cred.status, 'RESET')
        self.assertIsNotNone(refreshed_cred.password_reset_at)
        self.assertFalse(refreshed_cred.is_active)
        self.assertIsNone(refreshed_cred.temporary_password_encrypted)

        # =====================================================================
        # TEST 7: Old temporary password -> no longer works
        # =====================================================================
        self.assertFalse(
            refreshed_cred.verify_password(plaintext_temp_password),
            "Old temporary password still verifies on onboarding credential after reset!"
        )
        self.assertFalse(
            employee.check_password(plaintext_temp_password),
            "Old temporary password still verifies on employee after reset!"
        )
        res_old_pwd_login = self._login(emp_id, plaintext_temp_password)
        self.assertIn(b'Invalid Employee ID or password', res_old_pwd_login.data)

        # =====================================================================
        # TEST 8: New permanent password -> works
        # =====================================================================
        self.assertTrue(
            employee.check_password(new_permanent_password),
            "New permanent password failed to verify"
        )
        res_new_pwd_login = self._login(emp_id, new_permanent_password)
        self.assertEqual(res_new_pwd_login.status_code, 200)
        self.assertTrue(b'Log Out' in res_new_pwd_login.data or b'/logout' in res_new_pwd_login.data)
        self._logout()

        # =====================================================================
        # TEST 9: Anti-Matrix Admin Portal ->
        # Employee ID remains visible, old temporary password is hidden
        # =====================================================================
        self._login('admin@antimatrix.ai', 'AdminSecurePass123!')

        # 9a. Employee Profile view
        res_emp_view = self.client.get(f'/admin/employees/{emp_id}')
        self.assertEqual(res_emp_view.status_code, 200)
        self.assertIn(emp_id.encode(), res_emp_view.data)
        self.assertNotIn(plaintext_temp_password.encode(), res_emp_view.data)
        self.assertNotIn(html.escape(plaintext_temp_password).encode(), res_emp_view.data)
        self.assertNotIn(new_permanent_password.encode(), res_emp_view.data)
        self.assertIn(b'Temporary Password Reset', res_emp_view.data)

        # 9b. Application Dossier view
        res_app_view = self.client.get(f'/admin/applications/{self.application.id}')
        self.assertEqual(res_app_view.status_code, 200)
        self.assertIn(emp_id.encode(), res_app_view.data)
        self.assertNotIn(plaintext_temp_password.encode(), res_app_view.data)
        self.assertNotIn(html.escape(plaintext_temp_password).encode(), res_app_view.data)
        self.assertNotIn(new_permanent_password.encode(), res_app_view.data)
        self.assertIn(b'Temporary Password Reset', res_app_view.data)

        # =====================================================================
        # TEST 10: Joining Email retry after password reset ->
        # MUST NOT send the old temporary password
        # =====================================================================
        send_success, send_msg = send_joining_credentials_email(
            self.application,
            joining_date="15/09/2026"
        )
        self.assertFalse(send_success, "Joining email dispatch should be blocked when credential is RESET")
        self.assertIn(
            "already activated/reset their portal password",
            send_msg
        )

        rendered_post_reset = render_joining_credentials_email(self.application)
        self.assertNotIn(
            plaintext_temp_password,
            rendered_post_reset['body_text'],
            "Obsolete temporary password found in post-reset rendered email body!"
        )
        self.assertNotIn(
            plaintext_temp_password,
            rendered_post_reset['body_html'],
            "Obsolete temporary password found in post-reset rendered email HTML!"
        )

        self._logout()


if __name__ == '__main__':
    unittest.main()
