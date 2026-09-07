import os
import unittest
import string
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment, Employee


class EmployeeCredentialsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('development')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        Employee.query.delete()
        JobApplication.query.filter(
            (JobApplication.email.like('kavitha_%')) |
            (JobApplication.email == 'unpaid.candidate@example.com')
        ).delete()
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

        # Ensure a base internship job posting exists
        self.job = JobPosting.query.filter_by(title='AI Research Scientist Intern').first()
        if not self.job:
            self.job = JobPosting(
                title='AI Research Scientist Intern',
                department='AI & Data',
                location='Remote (Worldwide)',
                employment_type='Internship',
                duration='3_months',
                short_description='Research and build next-generation AI architectures.',
                skills='PyTorch, Python, Transformers',
                description='AI research intern description.',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def login_admin(self):
        return self.client.post('/login', data={'email': 'admin@antimatrix.ai', 'password': 'Admin@AntiMatrix2026!'})

    def login_member(self):
        return self.client.post('/login', data={'email': 'member@example.com', 'password': 'Member@2026!'})

    def logout(self):
        return self.client.get('/logout')

    def create_paid_application(self, email_suffix: str = "1"):
        """Helper to create a valid, paid, submitted application."""
        app_record = JobApplication(
            job_id=self.job.id,
            first_name='Kavitha',
            last_name=f'Raman_{email_suffix}',
            full_name=f'Kavitha Raman {email_suffix}',
            email=f'kavitha_{email_suffix}@example.com',
            phone='9876543210',
            address='456 Cyber Gateway',
            state='Karnataka',
            city='Bengaluru',
            pincode='560001',
            education_level="Bachelor's Degree",
            degree='B.Tech Computer Science',
            major='Computer Science',
            graduation_year='2026',
            resume_filename=f'resume_{email_suffix}.pdf',
            resume_path=f'uploads/resumes/resume_{email_suffix}.pdf',
            duration='3_months',
            application_fee=399,
            payment_status='paid',
            application_status='submitted',
            status='New'
        )
        db.session.add(app_record)
        db.session.flush()
        app_record.application_code = f"AM-APP-{app_record.id:06d}"
        db.session.commit()
        return app_record

    def _create_employee_for_app(self, app_record):
        emp_id = Employee.generate_unique_employee_id()
        plaintext_password = Employee.generate_secure_password(12)
        employee = Employee(
            employee_id=emp_id,
            application_id=app_record.id,
            account_status='active'
        )
        employee.set_password(plaintext_password)
        db.session.add(employee)
        db.session.commit()
        return employee, plaintext_password

    # -------------------------------------------------------------
    # TEST 1: Admin Dashboard -> Create Employee ID button is removed
    # -------------------------------------------------------------
    def test_01_admin_dashboard_create_employee_button_removed(self):
        self.login_admin()
        res = self.client.get('/admin/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'Create Employee ID', res.data)
        self.assertNotIn(b'/admin/employees/create', res.data)

    # -------------------------------------------------------------
    # TEST 2: Employees Page -> Create Employee ID button is removed
    # -------------------------------------------------------------
    def test_02_employees_page_create_employee_button_removed(self):
        self.login_admin()
        res = self.client.get('/admin/employees')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'Create Employee ID', res.data)
        self.assertNotIn(b'Create First Employee ID', res.data)
        self.assertNotIn(b'/admin/employees/create', res.data)

    # -------------------------------------------------------------
    # TEST 3: Accessing /admin/employees/create -> Redirects to /admin/employees
    # -------------------------------------------------------------
    def test_03_direct_create_employee_route_redirects(self):
        self.login_admin()
        res = self.client.get('/admin/employees/create', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/employees', res.headers.get('Location', ''))

        res_post = self.client.post('/admin/employees/create', data={'application_id': 1}, follow_redirects=False)
        self.assertEqual(res_post.status_code, 302)
        self.assertIn('/admin/employees', res_post.headers.get('Location', ''))

    # -------------------------------------------------------------
    # TEST 4: Employee ID Format Verification (AM + 4 Digits)
    # -------------------------------------------------------------
    def test_04_employee_id_format(self):
        paid_app = self.create_paid_application(email_suffix="fmt")
        emp, pwd = self._create_employee_for_app(paid_app)
        
        self.assertTrue(emp.employee_id.startswith('AM'))
        self.assertEqual(len(emp.employee_id), 6)
        digits_part = emp.employee_id[2:]
        self.assertTrue(digits_part.isdigit())
        self.assertEqual(len(digits_part), 4)

    # -------------------------------------------------------------
    # TEST 5: Non-sequential random generation for multiple employees
    # -------------------------------------------------------------
    def test_05_non_sequential_random_ids(self):
        app1 = self.create_paid_application(email_suffix="rnd1")
        app2 = self.create_paid_application(email_suffix="rnd2")

        emp1, _ = self._create_employee_for_app(app1)
        emp2, _ = self._create_employee_for_app(app2)

        self.assertNotEqual(emp1.employee_id, emp2.employee_id)
        self.assertTrue(emp1.employee_id.startswith('AM') and emp1.employee_id[2:].isdigit())
        self.assertTrue(emp2.employee_id.startswith('AM') and emp2.employee_id[2:].isdigit())

    # -------------------------------------------------------------
    # TEST 6: Database constraint check -> employee_id is unique
    # -------------------------------------------------------------
    def test_06_employee_id_uniqueness(self):
        app1 = self.create_paid_application(email_suffix="uniq1")
        app2 = self.create_paid_application(email_suffix="uniq2")

        emp1 = Employee(employee_id='AM8888', application_id=app1.id, account_status='active')
        emp1.set_password('Pass1234@#AM')
        db.session.add(emp1)
        db.session.commit()

        # Attempt to insert duplicate employee_id 'AM8888' -> should raise error
        emp2 = Employee(employee_id='AM8888', application_id=app2.id, account_status='active')
        emp2.set_password('Pass5678@#AM')
        db.session.add(emp2)
        with self.assertRaises(Exception):
            db.session.commit()
        db.session.rollback()

    # -------------------------------------------------------------
    # TEST 7: Database password check -> Only password_hash stored
    # -------------------------------------------------------------
    def test_07_database_password_hashing(self):
        app = self.create_paid_application(email_suffix="hash")
        emp, _ = self._create_employee_for_app(app)

        self.assertIsNotNone(emp.password_hash)
        self.assertTrue(emp.password_hash.startswith('scrypt:') or emp.password_hash.startswith('pbkdf2:'))

        columns = [c.name for c in Employee.__table__.columns]
        self.assertIn('password_hash', columns)
        self.assertNotIn('password', columns)

    # -------------------------------------------------------------
    # TEST 8: Revisit employee details -> Plaintext password NOT retrievable
    # -------------------------------------------------------------
    def test_08_revisit_employee_detail_no_plaintext_password(self):
        app = self.create_paid_application(email_suffix="view")
        emp, _ = self._create_employee_for_app(app)

        self.login_admin()
        res_view = self.client.get(f'/admin/employees/{emp.employee_id}')
        self.assertEqual(res_view.status_code, 200)

        html_view = res_view.data.decode('utf-8')
        self.assertIn(emp.employee_id, html_view)
        self.assertIn(app.full_name, html_view)
        self.assertNotIn(emp.password_hash, html_view)

    # -------------------------------------------------------------
    # TEST 9: Existing employees list loads cleanly
    # -------------------------------------------------------------
    def test_09_existing_employees_list_loads(self):
        app = self.create_paid_application(email_suffix="list")
        emp, _ = self._create_employee_for_app(app)

        self.login_admin()
        res = self.client.get('/admin/employees')
        self.assertEqual(res.status_code, 200)
        self.assertIn(emp.employee_id.encode('utf-8'), res.data)

if __name__ == '__main__':
    unittest.main()
