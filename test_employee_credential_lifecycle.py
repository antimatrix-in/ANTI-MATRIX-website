"""
Comprehensive Lifecycle Test for Anti-Matrix Employee Credential Display & Temporary Password Lifecycle
Tests Scenarios A through H strictly in an isolated testing environment.
"""

import html
import unittest
from datetime import datetime, timezone
from app import create_app
from models import db, User, JobPosting, JobApplication, Employee


class EmployeeCredentialLifecycleTestCase(unittest.TestCase):
    def setUp(self):
        # Use isolated in-memory SQLite database for test safety
        self.app = create_app('testing')
        self.app.config['SECRET_KEY'] = 'test-secret-key-antimatrix-2026'
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

        # Create regular Member (unauthorized)
        self.member = User(
            name='Regular Member',
            email='member@antimatrix.ai',
            role='member',
            is_active=True
        )
        self.member.set_password('MemberSecurePass123!')
        db.session.add(self.member)

        # Create sample Job Posting
        self.job = JobPosting(
            title='AI Research Scientist Intern',
            department='AI & Data',
            location='Remote',
            employment_type='Internship',
            duration='3_months',
            short_description='AI Research',
            description='Full AI Research',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

        # Create sample Job Application
        self.application = JobApplication(
            job_id=self.job.id,
            full_name='Aarav Sharma',
            email='aarav.sharma@example.com',
            phone='+919876543210',
            resume_filename='aarav_resume.pdf',
            resume_path='uploads/resumes/aarav_resume.pdf',
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

    def test_complete_credential_lifecycle_scenarios_a_to_h(self):
        secret_key = self.app.config['SECRET_KEY']

        # =====================================================================
        # SCENARIO A: New Employee Created
        # -> Employee ID generated
        # -> Temporary Password generated and encrypted
        # -> Status = Temporary Password Active
        # =====================================================================
        emp_id = Employee.generate_unique_employee_id()
        plaintext_temp_password = Employee.generate_secure_password(12)

        employee = Employee(
            employee_id=emp_id,
            application_id=self.application.id,
            account_status='active',
            temporary_password_active=True
        )
        employee.set_password(plaintext_temp_password)
        employee.set_temp_password(plaintext_temp_password, secret_key)
        db.session.add(employee)
        db.session.commit()

        # Verify model state
        self.assertTrue(employee.temporary_password_active)
        self.assertTrue(employee.is_temporary_password_active)
        self.assertIsNotNone(employee.temp_password_encrypted)
        self.assertEqual(employee.get_temp_password(secret_key), plaintext_temp_password)
        self.assertTrue(employee.check_password(plaintext_temp_password))

        # Log in as Admin and verify display on Employee Detail page
        self._login('admin@antimatrix.ai', 'AdminSecurePass123!')
        res_emp = self.client.get(f'/admin/employees/{emp_id}')
        self.assertEqual(res_emp.status_code, 200)
        self.assertIn(emp_id.encode(), res_emp.data)
        self.assertTrue(
            plaintext_temp_password.encode() in res_emp.data or
            html.escape(plaintext_temp_password).encode() in res_emp.data
        )
        self.assertIn(b'Temporary Password Active', res_emp.data)

        # Verify display on Application Detail dossier page
        res_app = self.client.get(f'/admin/applications/{self.application.id}')
        self.assertEqual(res_app.status_code, 200)
        self.assertIn(emp_id.encode(), res_app.data)
        self.assertTrue(
            plaintext_temp_password.encode() in res_app.data or
            html.escape(plaintext_temp_password).encode() in res_app.data
        )
        self.assertIn(b'Temporary Password Active', res_app.data)
        self._logout()

        # =====================================================================
        # SCENARIO B: Employee logs into Anti-Matrix / Internship Portal with temp password
        # -> Authentication succeeds
        # =====================================================================
        res_cand_login = self._login(emp_id, plaintext_temp_password)
        self.assertEqual(res_cand_login.status_code, 200)
        self.assertTrue(b'Log Out' in res_cand_login.data or b'/logout' in res_cand_login.data)
        self._logout()

        # =====================================================================
        # SCENARIO G: Failed password reset attempt
        # -> Temporary password remains active
        # =====================================================================
        # Admin attempts reset with password shorter than 6 characters
        self._login('admin@antimatrix.ai', 'AdminSecurePass123!')
        res_fail_reset = self.client.post(f'/admin/employees/{emp_id}/reset-password', data={
            'new_password': '123'
        }, follow_redirects=True)
        self.assertIn(b'New password must be at least 6 characters long', res_fail_reset.data)

        # Refresh employee from database
        emp_after_failed_reset = Employee.query.filter_by(employee_id=emp_id).first()
        self.assertTrue(emp_after_failed_reset.is_temporary_password_active)
        self.assertEqual(emp_after_failed_reset.get_temp_password(secret_key), plaintext_temp_password)
        self.assertTrue(emp_after_failed_reset.check_password(plaintext_temp_password))

        # =====================================================================
        # SCENARIO C: Employee changes password successfully
        # -> Password hash updated
        # -> Temporary password becomes inactive / reset
        # -> temp_password_encrypted is purged
        # =====================================================================
        new_permanent_password = "MyNewPermanentSecurePass2026!"
        emp_after_failed_reset.reset_password(new_permanent_password)
        db.session.commit()

        # Verify state transition in database
        emp_reset = Employee.query.filter_by(employee_id=emp_id).first()
        self.assertFalse(emp_reset.temporary_password_active)
        self.assertFalse(emp_reset.is_temporary_password_active)
        self.assertIsNone(emp_reset.temp_password_encrypted)
        self.assertEqual(emp_reset.get_temp_password(secret_key), "")
        self.assertTrue(emp_reset.check_password(new_permanent_password))
        self.assertFalse(emp_reset.check_password(plaintext_temp_password))

        # =====================================================================
        # SCENARIO D: Refresh Anti-Matrix Admin Portal
        # -> Employee ID still visible
        # -> Old temporary password no longer visible
        # -> Status shows 'Temporary Password Reset'
        # -> New password is NOT displayed anywhere
        # =====================================================================
        res_emp_refresh = self.client.get(f'/admin/employees/{emp_id}')
        self.assertEqual(res_emp_refresh.status_code, 200)
        self.assertIn(emp_id.encode(), res_emp_refresh.data)
        self.assertNotIn(plaintext_temp_password.encode(), res_emp_refresh.data)
        self.assertNotIn(html.escape(plaintext_temp_password).encode(), res_emp_refresh.data)
        self.assertNotIn(new_permanent_password.encode(), res_emp_refresh.data)
        self.assertIn(b'Temporary Password Reset', res_emp_refresh.data)

        # Also check Application Detail dossier
        res_app_refresh = self.client.get(f'/admin/applications/{self.application.id}')
        self.assertEqual(res_app_refresh.status_code, 200)
        self.assertIn(emp_id.encode(), res_app_refresh.data)
        self.assertNotIn(plaintext_temp_password.encode(), res_app_refresh.data)
        self.assertNotIn(html.escape(plaintext_temp_password).encode(), res_app_refresh.data)
        self.assertNotIn(new_permanent_password.encode(), res_app_refresh.data)
        self.assertIn(b'Temporary Password Reset', res_app_refresh.data)
        self._logout()

        # =====================================================================
        # SCENARIO E: Attempt to log in using old temporary password
        # -> Rejected
        # =====================================================================
        res_old_login = self._login(emp_id, plaintext_temp_password)
        self.assertIn(b'Invalid Employee ID or password', res_old_login.data)

        # =====================================================================
        # SCENARIO F: Login using new password
        # -> Succeeds
        # =====================================================================
        res_new_login = self._login(emp_id, new_permanent_password)
        self.assertEqual(res_new_login.status_code, 200)
        self.assertTrue(b'Log Out' in res_new_login.data or b'/logout' in res_new_login.data)
        self._logout()

        # =====================================================================
        # SCENARIO H: Unauthorized user attempts to access credential view
        # -> Rejected
        # =====================================================================
        # 1. Unauthenticated visitor
        res_unauth = self.client.get(f'/admin/employees/{emp_id}')
        self.assertIn(res_unauth.status_code, [302, 401, 403])

        # 2. Authenticated non-admin member
        self._login('member@antimatrix.ai', 'MemberSecurePass123!')
        res_member = self.client.get(f'/admin/employees/{emp_id}')
        self.assertIn(res_member.status_code, [302, 403])
        self._logout()


if __name__ == '__main__':
    unittest.main()
