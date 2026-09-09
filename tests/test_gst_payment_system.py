import json
import unittest
from decimal import Decimal
from app import create_app
from models import db, User, JobPosting, JobApplication, Payment, MoneyTransaction
from services.payment_service import calculate_payment_total
from services.cashfree_service import CashfreeService
from services.money_service import record_cashfree_income


class GSTPaymentSystemTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Create Admin
        self.admin = User(name='GST Admin', email='admin_gst@antimatrix.ai', role='admin', is_active=True)
        self.admin.set_password('Admin@2026!')
        db.session.add(self.admin)

        # Create Candidate
        self.candidate = User(name='Pooja GST', email='candidate_gst@antimatrix.ai', role='member', is_active=True)
        self.candidate.set_password('Candidate@2026!')
        db.session.add(self.candidate)

        # Create 1 Month Job
        self.job_1m = JobPosting(
            title='Backend Engineer Intern',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            short_description='1-Month Backend Internship.',
            description='Detailed description.',
            requirements='Python, Flask',
            responsibilities='Build APIs',
            is_active=True
        )
        db.session.add(self.job_1m)

        # Create 3 Months Job
        self.job_3m = JobPosting(
            title='AI Research Intern',
            department='AI',
            location='Remote',
            employment_type='Internship',
            duration='3_months',
            short_description='3-Month AI Internship.',
            description='Detailed description.',
            requirements='PyTorch, Python',
            responsibilities='Train Models',
            is_active=True
        )
        db.session.add(self.job_3m)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_candidate(self):
        return self.client.post('/login', data={'email': self.candidate.email, 'password': 'Candidate@2026!'})

    def _create_app(self, job_id, duration='1_month', fee=199):
        app = JobApplication(
            job_id=job_id,
            user_id=self.candidate.id,
            first_name='Test',
            last_name='Candidate',
            full_name='Test Candidate',
            email=self.candidate.email,
            phone='9876543210',
            duration=duration,
            application_fee=fee,
            resume_filename='resume.pdf',
            resume_path='/tmp/resume.pdf',
            payment_status='pending',
            application_status='pending_payment'
        )
        db.session.add(app)
        db.session.commit()
        return app

    # -------------------------------------------------------------
    # TEST 1: 1 Month Plan (Base 199.00 -> GST 35.82 -> Total 234.82)
    # -------------------------------------------------------------
    def test_01_one_month_gst_calculation(self):
        result = calculate_payment_total(199)
        self.assertEqual(result['base_amount'], 199.00)
        self.assertEqual(result['gst_rate'], 18.0)
        self.assertEqual(result['gst_amount'], 35.82)
        self.assertEqual(result['total_amount'], 234.82)
        self.assertEqual(result['amount_paise'], 23482)
        self.assertEqual(result['formatted_base'], '₹199.00')
        self.assertEqual(result['formatted_gst'], '₹35.82')
        self.assertEqual(result['formatted_total'], '₹234.82')

    # -------------------------------------------------------------
    # TEST 2: 3 Months Plan (Base 399.00 -> GST 71.82 -> Total 470.82)
    # -------------------------------------------------------------
    def test_02_three_months_gst_calculation(self):
        result = calculate_payment_total(399)
        self.assertEqual(result['base_amount'], 399.00)
        self.assertEqual(result['gst_rate'], 18.0)
        self.assertEqual(result['gst_amount'], 71.82)
        self.assertEqual(result['total_amount'], 470.82)
        self.assertEqual(result['amount_paise'], 47082)
        self.assertEqual(result['formatted_base'], '₹399.00')
        self.assertEqual(result['formatted_gst'], '₹71.82')
        self.assertEqual(result['formatted_total'], '₹470.82')

    # -------------------------------------------------------------
    # TEST 3: Arbitrary Base Amounts & Exact Decimal Precision
    # -------------------------------------------------------------
    def test_03_arbitrary_amounts_and_decimal_precision(self):
        # 550.50 * 0.18 = 99.09 -> Total 649.59
        res1 = calculate_payment_total(550.50)
        self.assertEqual(res1['base_amount'], 550.50)
        self.assertEqual(res1['gst_amount'], 99.09)
        self.assertEqual(res1['total_amount'], 649.59)

        # 1000.00 * 0.18 = 180.00 -> Total 1180.00
        res2 = calculate_payment_total(1000)
        self.assertEqual(res2['base_amount'], 1000.00)
        self.assertEqual(res2['gst_amount'], 180.00)
        self.assertEqual(res2['total_amount'], 1180.00)

        # 1.00 * 0.18 = 0.18 -> Total 1.18
        res3 = calculate_payment_total(1)
        self.assertEqual(res3['base_amount'], 1.00)
        self.assertEqual(res3['gst_amount'], 0.18)
        self.assertEqual(res3['total_amount'], 1.18)

    # -------------------------------------------------------------
    # TEST 4: Zero and Negative (Free) Base Amount Behavior
    # -------------------------------------------------------------
    def test_04_free_or_zero_base_amount(self):
        res_zero = calculate_payment_total(0)
        self.assertEqual(res_zero['base_amount'], 0.00)
        self.assertEqual(res_zero['gst_amount'], 0.00)
        self.assertEqual(res_zero['total_amount'], 0.00)

        res_none = calculate_payment_total(None)
        self.assertEqual(res_none['base_amount'], 0.00)
        self.assertEqual(res_none['gst_amount'], 0.00)
        self.assertEqual(res_none['total_amount'], 0.00)

    # -------------------------------------------------------------
    # TEST 5: Frontend Tamper Resistance
    # -------------------------------------------------------------
    def test_05_client_tamper_resistance(self):
        self.login_candidate()
        app_record = self._create_app(self.job_1m.id, '1_month', 199)

        # Post test payment attempting to pass a spoofed amount of ₹1.00
        resp = self.client.post(
            f'/careers/apply/test-payment/{app_record.id}',
            data={'amount': '1.00', 'total_amount': '1.00'},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)

        # Verify backend ignored client values and enforced ₹234.82
        payment = Payment.query.filter_by(application_id=app_record.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.amount, 234.82)
        self.assertEqual(payment.base_amount, 199.00)
        self.assertEqual(payment.gst_amount, 35.82)

    # -------------------------------------------------------------
    # TEST 6: Cashfree Order Creation Amount Matches GST Total
    # -------------------------------------------------------------
    def test_06_cashfree_order_creation_amount(self):
        return_url = "http://localhost/payment/cashfree/return?order_id={order_id}"
        app_1m = self._create_app(self.job_1m.id, '1_month', 199)
        success, order_data, err = CashfreeService.create_order(app_1m, self.job_1m, return_url)
        self.assertTrue(success)
        # Order amount in Cashfree payload must be exactly 234.82
        self.assertEqual(order_data.get('order_amount'), 234.82)

        app_3m = self._create_app(self.job_3m.id, '3_months', 399)
        success3, order_data3, err3 = CashfreeService.create_order(app_3m, self.job_3m, return_url)
        self.assertTrue(success3)
        # Order amount in Cashfree payload must be exactly 470.82
        self.assertEqual(order_data3.get('order_amount'), 470.82)

    # -------------------------------------------------------------
    # TEST 7: Server-Side Payment Verification Rejects Underpayment
    # -------------------------------------------------------------
    def test_07_payment_verification_amount_check(self):
        return_url = "http://localhost/payment/cashfree/return?order_id={order_id}"
        app_rec = self._create_app(self.job_1m.id, '1_month', 199)
        success, order_data, _ = CashfreeService.create_order(app_rec, self.job_1m, return_url)
        order_id = order_data['order_id']

        # Verifying with expected_amount matching order amount
        is_paid, status, details, err = CashfreeService.verify_order_payment(order_id, expected_amount=234.82)
        self.assertTrue(is_paid)
        self.assertEqual(status, 'SUCCESS')

        # Verifying with expected_amount mismatch (e.g. 500.00 expected but paid 234.82)
        is_paid_bad, status_bad, _, err_bad = CashfreeService.verify_order_payment(order_id, expected_amount=500.00)
        self.assertFalse(is_paid_bad)
        self.assertEqual(status_bad, 'AMOUNT_MISMATCH')

    # -------------------------------------------------------------
    # TEST 8: Money Management Ledger Entry Single Record & Audit
    # -------------------------------------------------------------
    def test_08_money_management_ledger_recording(self):
        app_rec = self._create_app(self.job_1m.id, '1_month', 199)
        app_rec.base_amount = 199.00
        app_rec.gst_rate = 18.0
        app_rec.gst_amount = 35.82
        db.session.commit()

        payment = Payment(
            application_id=app_rec.id,
            cashfree_order_id='TEST-LEDGER-001',
            amount=234.82,
            base_amount=199.00,
            gst_rate=18.0,
            gst_amount=35.82,
            currency='INR',
            payment_status='paid',
            gateway='TEST'
        )
        db.session.add(payment)
        db.session.commit()

        # Record income
        ok, txn, _ = record_cashfree_income(app_rec, payment, {'simulated': True}, env='TEST')
        self.assertTrue(ok)
        self.assertIsNotNone(txn)
        self.assertEqual(txn.amount, 234.82)
        self.assertEqual(txn.transaction_type, 'INCOME')
        self.assertEqual(txn.category, 'Internship Application Fee')
        self.assertIn('Base: ₹199.00 + GST 18%: ₹35.82', txn.description)

        # Calling record_cashfree_income again for the same order should be idempotent (no duplicate txn)
        ok2, txn2, _ = record_cashfree_income(app_rec, payment, {'simulated': True}, env='TEST')
        self.assertTrue(ok2)
        self.assertEqual(txn.id, txn2.id)
        self.assertEqual(MoneyTransaction.query.filter_by(reference='TEST-LEDGER-001').count(), 1)

    # -------------------------------------------------------------
    # TEST 9: Payment Retry Recalculation Idempotence
    # -------------------------------------------------------------
    def test_09_payment_retry_recalculation(self):
        self.login_candidate()
        app_rec = self._create_app(self.job_3m.id, '3_months', 399)

        # Step 1: User starts checkout
        resp1 = self.client.post(f'/careers/apply/checkout/{app_rec.id}')
        self.assertEqual(resp1.status_code, 302)

        payment1 = Payment.query.filter_by(application_id=app_rec.id).first()
        self.assertIsNotNone(payment1)
        self.assertEqual(payment1.amount, 470.82)
        self.assertEqual(payment1.base_amount, 399.00)
        self.assertEqual(payment1.gst_amount, 71.82)

        # Step 2: User returns and retries checkout
        resp2 = self.client.post(f'/careers/apply/checkout/{app_rec.id}')
        self.assertEqual(resp2.status_code, 302)

        # Payment count should still be 1 (reused or updated), not duplicated
        payments = Payment.query.filter_by(application_id=app_rec.id).all()
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].amount, 470.82)

    # -------------------------------------------------------------
    # TEST 10: Historical Payment Backward Compatibility
    # -------------------------------------------------------------
    def test_10_historical_payment_backward_compatibility(self):
        app_rec = self._create_app(self.job_3m.id, '3_months', 399)

        # Simulate a historical payment record created before GST migration
        # amount = 399.0, base_amount = None, gst_rate = None, gst_amount = None
        historical_payment = Payment(
            application_id=app_rec.id,
            cashfree_order_id='HISTORICAL-ORDER-094',
            amount=399.0,
            base_amount=None,
            gst_rate=None,
            gst_amount=None,
            currency='INR',
            payment_status='paid',
            gateway='cashfree'
        )
        db.session.add(historical_payment)
        db.session.commit()

        # Access model properties
        self.assertIsNone(historical_payment.base_amount)
        self.assertIsNone(historical_payment.gst_amount)

        # fee_breakdown property should gracefully fallback to amount without crashing
        breakdown = historical_payment.fee_breakdown
        self.assertEqual(breakdown['base_amount'], 399.0)
        self.assertEqual(breakdown['total_amount'], 399.0)
        self.assertEqual(breakdown['gst_amount'], 0.0)


if __name__ == '__main__':
    unittest.main()
