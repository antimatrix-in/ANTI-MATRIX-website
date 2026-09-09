import re
import json
import unittest
from decimal import Decimal
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment
from services.payment_service import calculate_payment_total
from services.cashfree_service import CashfreeService
from config import get_internship_fee_breakdown, normalize_internship_duration, INTERNSHIP_FEES, INTERNSHIP_PRICING


class JobIdAndDurationPricingTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['PAYMENT_TEST_MODE'] = True
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Create Admin
        self.admin = User(name='Admin User', email='admin_test@antimatrix.ai', role='admin', is_active=True)
        self.admin.set_password('Admin@2026!')
        db.session.add(self.admin)

        # Create Candidate
        self.candidate = User(name='Pooja Sharma', email='pooja_test@antimatrix.ai', role='member', is_active=True)
        self.candidate.set_password('Candidate@2026!')
        db.session.add(self.candidate)

        # Create AI & ML Job (Job 126 in production context)
        self.ai_ml_job = JobPosting(
            job_id='JB1234',
            title='AI Research Intern',
            department='AI & Data',
            location='Remote',
            employment_type='Internship',
            duration='3_months',
            short_description='AI & ML internship opportunity.',
            description='Detailed description for AI Research Intern.',
            requirements='Python, Machine Learning, PyTorch',
            responsibilities='Build models',
            is_active=True
        )
        db.session.add(self.ai_ml_job)

        # Create Frontend Engineer Intern Job
        self.fe_job = JobPosting(
            job_id='JB1001',
            title='Frontend Engineer Intern',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            short_description='Frontend engineering internship.',
            description='Detailed description for Frontend Engineer.',
            requirements='HTML, CSS, JavaScript',
            responsibilities='Build UI',
            is_active=True
        )
        db.session.add(self.fe_job)

        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_ai_ml_job_id_format(self):
        """TEST 1: AI & ML job has unique Job ID matching JB#### format."""
        job = JobPosting.query.filter_by(title='AI Research Intern').first()
        self.assertIsNotNone(job, "AI & ML job must exist")
        self.assertIsNotNone(job.job_id, "Job ID must be assigned")
        self.assertTrue(re.match(r'^JB\d{4}$', job.job_id), f"Job ID {job.job_id} must match format JB####")
        self.assertEqual(job.job_id, 'JB1234', "AI & ML job should have Job ID JB1234")

        # Verify Job ID helper generates unique JB#### without collisions
        next_id = JobPosting.generate_unique_job_id()
        self.assertTrue(re.match(r'^JB\d{4}$', next_id))
        self.assertNotIn(next_id, [job.job_id, self.fe_job.job_id])

        # If preferred_id already taken, it assigns an unused ID
        collision_safe_id = JobPosting.generate_unique_job_id(preferred_id='JB1234')
        self.assertNotEqual(collision_safe_id, 'JB1234')
        self.assertTrue(re.match(r'^JB\d{4}$', collision_safe_id))

    def test_02_select_1_month_pricing(self):
        """TEST 2: 1 Month duration yields Base = ₹199, GST = ₹35.82, Total = ₹234.82."""
        pricing = get_internship_fee_breakdown('1_month')
        self.assertEqual(pricing['base_amount'], 199.00)
        self.assertEqual(pricing['gst_rate'], 18.0)
        self.assertEqual(pricing['gst_amount'], 35.82)
        self.assertEqual(pricing['total_amount'], 234.82)
        self.assertEqual(pricing['amount_paise'], 23482)
        self.assertEqual(pricing['formatted_base'], '₹199.00')
        self.assertEqual(pricing['formatted_gst'], '₹35.82')
        self.assertEqual(pricing['formatted_total'], '₹234.82')

        # Test label normalization
        pricing_label = get_internship_fee_breakdown('1 Month')
        self.assertEqual(pricing_label['base_amount'], 199.00)
        self.assertEqual(pricing_label['total_amount'], 234.82)

    def test_03_select_3_months_pricing(self):
        """TEST 3: 3 Months duration yields Base = ₹399, GST = ₹71.82, Total = ₹470.82."""
        pricing = get_internship_fee_breakdown('3_months')
        self.assertEqual(pricing['base_amount'], 399.00)
        self.assertEqual(pricing['gst_rate'], 18.0)
        self.assertEqual(pricing['gst_amount'], 71.82)
        self.assertEqual(pricing['total_amount'], 470.82)
        self.assertEqual(pricing['amount_paise'], 47082)
        self.assertEqual(pricing['formatted_base'], '₹399.00')
        self.assertEqual(pricing['formatted_gst'], '₹71.82')
        self.assertEqual(pricing['formatted_total'], '₹470.82')

        # Test label normalization
        pricing_label = get_internship_fee_breakdown('3 Months')
        self.assertEqual(pricing_label['base_amount'], 399.00)
        self.assertEqual(pricing_label['total_amount'], 470.82)

    def test_04_existing_gst_frontend_ui_preserved(self):
        """TEST 4: Verify existing GST frontend review page displays correctly without UI redesign."""
        # Log in candidate
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.candidate.id)

        # Create draft application for 1 Month
        app_1m = JobApplication(
            job_id=self.ai_ml_job.id,
            user_id=self.candidate.id,
            full_name='Pooja Sharma',
            email=self.candidate.email,
            phone='9876543210',
            address='123 Tech Lane',
            state='Karnataka',
            city='Bengaluru',
            pincode='560001',
            education_level="Bachelor's Degree",
            degree='B.Tech',
            major='Computer Science',
            graduation_year='2026',
            resume_filename='resume.pdf',
            resume_path='uploads/resumes/resume.pdf',
            duration='1_month',
            application_fee=199,
            base_amount=199.00,
            gst_rate=18.0,
            gst_amount=35.82,
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app_1m)
        db.session.commit()

        resp = self.client.get(f'/careers/apply/review/{app_1m.id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Verify existing GST elements are intact
        self.assertIn("Order Summary", html)
        self.assertIn("Program Duration", html)
        self.assertIn("1 Month", html)
        self.assertIn("Base Fee", html)
        self.assertIn("₹199.00", html)
        self.assertIn("GST (18%)", html)
        self.assertIn("₹35.82", html)
        self.assertIn("Total Payable", html)
        self.assertIn("₹234.82", html)

    def test_05_cashfree_order_receives_correct_amounts(self):
        """TEST 5: Verify Cashfree order receives ₹234.82 for 1 Month and ₹470.82 for 3 Months."""
        app_1m = JobApplication(
            id=901,
            job_id=self.ai_ml_job.id,
            user_id=self.candidate.id,
            full_name='Pooja 1M',
            email=self.candidate.email,
            phone='9876543210',
            resume_filename='resume.pdf',
            resume_path='uploads/resumes/resume.pdf',
            duration='1_month',
            payment_status='pending'
        )
        db.session.add(app_1m)
        db.session.commit()

        self.app.config['CASHFREE_ENVIRONMENT'] = 'test'
        success, order_data, err = CashfreeService.create_order(
            application=app_1m,
            job=self.ai_ml_job,
            return_url="http://localhost:5000/payment/cashfree/return"
        )
        self.assertTrue(success)
        self.assertEqual(order_data['order_amount'], 234.82, "Cashfree must receive ₹234.82 for 1 Month")

        # Now test 3 Months
        app_3m = JobApplication(
            id=902,
            job_id=self.ai_ml_job.id,
            user_id=self.candidate.id,
            full_name='Pooja 3M',
            email=self.candidate.email,
            phone='9876543210',
            resume_filename='resume.pdf',
            resume_path='uploads/resumes/resume.pdf',
            duration='3_months',
            payment_status='pending'
        )
        db.session.add(app_3m)
        db.session.commit()

        success3, order_data3, err3 = CashfreeService.create_order(
            application=app_3m,
            job=self.ai_ml_job,
            return_url="http://localhost:5000/payment/cashfree/return"
        )
        self.assertTrue(success3)
        self.assertEqual(order_data3['order_amount'], 470.82, "Cashfree must receive ₹470.82 for 3 Months")

    def test_06_frontend_amount_tampering_rejected(self):
        """TEST 6: Frontend cannot manipulate amount; backend strictly calculates from selected duration."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.candidate.id)

        import io
        fake_resume = (io.BytesIO(b'%PDF-1.4 test resume content'), 'my_resume.pdf')
        fake_aadhaar = (io.BytesIO(b'%PDF-1.4 test aadhaar content'), 'aadhaar.pdf')

        # Tampered client submission: duration = 3_months, but amount/fee fields injected as 1 or 0
        form_data = {
            'first_name': 'Hacker',
            'last_name': 'Candidate',
            'email': self.candidate.email,
            'phone': '9876543210',
            'address': 'Tamper St',
            'state': 'Delhi',
            'city': 'New Delhi',
            'pincode': '110001',
            'education_level': "Bachelor's Degree",
            'degree': 'B.Tech',
            'major': 'CS',
            'graduation_year': '2026',
            'duration': '3_months',
            'amount': '1.00',
            'fee': '0.00',
            'total': '10.00',
            'resume': fake_resume,
            'aadhaar': fake_aadhaar
        }

        resp = self.client.post(
            f'/careers/apply/{self.ai_ml_job.id}',
            data=form_data,
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)

        app_created = JobApplication.query.filter_by(email=self.candidate.email, job_id=self.ai_ml_job.id).first()
        self.assertIsNotNone(app_created)
        self.assertEqual(app_created.duration, '3_months')
        self.assertEqual(app_created.base_amount, 399.00, "Backend must force 399.00 base amount")
        self.assertEqual(app_created.gst_amount, 71.82, "Backend must force 71.82 GST amount")

        # Checkout calculation must use 470.82
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.candidate.id)

        resp_checkout = self.client.post(f'/careers/apply/test-payment/{app_created.id}', follow_redirects=True)
        self.assertEqual(resp_checkout.status_code, 200)

        payment = Payment.query.filter_by(application_id=app_created.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 470.82, "Payment must be strictly 470.82 regardless of client tampering")
        self.assertEqual(payment.base_amount, 399.00)
        self.assertEqual(payment.gst_amount, 71.82)

    def test_07_payment_retry_uses_stored_duration(self):
        """TEST 7: Retrying payment recalculates from stored application duration."""
        app_retry = JobApplication(
            job_id=self.ai_ml_job.id,
            user_id=self.candidate.id,
            full_name='Retry Candidate',
            email=self.candidate.email,
            phone='9876543210',
            resume_filename='resume.pdf',
            resume_path='uploads/resumes/resume.pdf',
            duration='3_months',
            application_fee=399,
            base_amount=399.00,
            gst_rate=18.0,
            gst_amount=71.82,
            payment_status='failed'
        )
        db.session.add(app_retry)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.candidate.id)

        # Hit retry endpoint
        resp = self.client.get(f'/careers/apply/retry-payment/{app_retry.id}')
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f'/careers/apply/review/{app_retry.id}', resp.headers['Location'])

        # Check the review page recalculation
        resp_review = self.client.get(f'/careers/apply/review/{app_retry.id}')
        self.assertEqual(resp_review.status_code, 200)
        html = resp_review.get_data(as_text=True)

        self.assertIn('3 Months', html)
        self.assertIn('₹399.00', html)
        self.assertIn('₹71.82', html)
        self.assertIn('₹470.82', html)

    def test_08_application_stores_duration(self):
        """TEST 8: Verify application record stores selected duration."""
        app = JobApplication(
            job_id=self.ai_ml_job.id,
            user_id=self.candidate.id,
            full_name='Pooja Stored',
            email=self.candidate.email,
            phone='9876543210',
            resume_filename='resume.pdf',
            resume_path='uploads/resumes/resume.pdf',
            duration='1_month'
        )
        db.session.add(app)
        db.session.commit()

        loaded = db.session.get(JobApplication, app.id)
        self.assertEqual(loaded.duration, '1_month')
        self.assertEqual(loaded.duration_display, '1 Month')


if __name__ == '__main__':
    unittest.main()
