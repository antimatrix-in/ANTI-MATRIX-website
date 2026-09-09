import os
import base64
import hmac
import hashlib
import json
import time
import uuid
import re
import logging
import requests
from flask import current_app
from config import INTERNSHIP_FEES

logger = logging.getLogger(__name__)


class CashfreeService:
    """Official Cashfree Payment Gateway Service for Anti-Matrix Internship Applications."""

    SANDBOX_BASE_URL = "https://sandbox.cashfree.com/pg"
    PRODUCTION_BASE_URL = "https://api.cashfree.com/pg"

    @classmethod
    def get_config(cls):
        app_env = ''
        app_client_id = ''
        app_client_secret = ''
        app_api_version = ''
        if current_app:
            app_env = (current_app.config.get('CASHFREE_ENV') or current_app.config.get('CASHFREE_ENVIRONMENT') or '').strip()
            app_client_id = (current_app.config.get('CASHFREE_APP_ID') or current_app.config.get('CASHFREE_CLIENT_ID') or '').strip()
            app_client_secret = (current_app.config.get('CASHFREE_SECRET_KEY') or current_app.config.get('CASHFREE_CLIENT_SECRET') or '').strip()
            app_api_version = (current_app.config.get('CASHFREE_API_VERSION') or '').strip()

        env = (
            app_env or
            os.environ.get('CASHFREE_ENV', '').strip() or 
            os.environ.get('CASHFREE_ENVIRONMENT', '').strip() or 
            'sandbox'
        ).lower()

        client_id = (
            app_client_id or
            os.environ.get('CASHFREE_APP_ID', '').strip() or 
            os.environ.get('CASHFREE_CLIENT_ID', '').strip()
        )

        client_secret = (
            app_client_secret or
            os.environ.get('CASHFREE_SECRET_KEY', '').strip() or 
            os.environ.get('CASHFREE_CLIENT_SECRET', '').strip()
        )

        api_version = (
            app_api_version or
            os.environ.get('CASHFREE_API_VERSION', '').strip() or 
            '2025-01-01'
        )
        
        # Determine base URL based on environment (defaults to Sandbox)
        if env == 'production':
            base_url = cls.PRODUCTION_BASE_URL
        else:
            base_url = cls.SANDBOX_BASE_URL

        return {
            'environment': env,
            'client_id': client_id,
            'client_secret': client_secret,
            'api_version': api_version,
            'base_url': base_url
        }

    @classmethod
    def get_headers(cls):
        cfg = cls.get_config()
        return {
            'x-client-id': cfg['client_id'],
            'x-client-secret': cfg['client_secret'],
            'x-api-version': cfg['api_version'],
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    @classmethod
    def generate_order_id(cls, application_id: int) -> str:
        """Generate a unique, collision-resistant Cashfree order ID."""
        ts = int(time.time())
        rand_suffix = uuid.uuid4().hex[:5].upper()
        return f"AM-APP-{application_id:06d}-PAY-{ts}-{rand_suffix}"

    @classmethod
    def clean_phone(cls, phone: str) -> str:
        """Extract a clean 10-digit Indian phone number."""
        digits = re.sub(r'\D', '', phone or '')
        if len(digits) > 10 and digits.startswith('91'):
            digits = digits[2:]
        if len(digits) == 10:
            return digits
        return digits[-10:] if len(digits) >= 10 else "9876543210"

    @classmethod
    def create_order(cls, application, job, return_url: str, notify_url: str = None):
        """
        Create a Cashfree Order server-side.
        Amount is strictly calculated on server including 18% GST.
        """
        cfg = cls.get_config()
        env = cfg['environment']
        
        # Authoritative server-side fee & 18% GST calculation strictly from application duration
        from config import get_internship_fee_breakdown
        app_duration = getattr(application, 'duration', None)
        job_duration = getattr(job, 'duration', None) if job else None
        target_duration = app_duration or job_duration or '1_month'

        pricing = get_internship_fee_breakdown(target_duration)
        total_amount = pricing['total_amount']
        base_amount = pricing['base_amount']
        gst_rate = pricing['gst_rate']
        gst_amount = pricing['gst_amount']
        duration_label = pricing['duration_label']
        
        order_id = cls.generate_order_id(application.id)
        phone = cls.clean_phone(application.phone)
        customer_id = f"cust_{application.id}_{application.email.split('@')[0][:15]}"
        customer_id = re.sub(r'[^a-zA-Z0-9_-]', '_', customer_id)

        # Standard Cashfree return_url format: Cashfree API expects {order_id} placeholder so the gateway replaces it upon redirect
        formatted_return_url = return_url
        if '{order_id}' not in formatted_return_url:
            separator = '&' if '?' in formatted_return_url else '?'
            formatted_return_url = f"{formatted_return_url}{separator}order_id={{order_id}}"

        payload = {
            "order_id": order_id,
            "order_amount": total_amount,
            "order_currency": "INR",
            "customer_details": {
                "customer_id": customer_id,
                "customer_name": application.full_name[:100],
                "customer_email": application.email[:100],
                "customer_phone": phone
            },
            "order_meta": {
                "return_url": formatted_return_url
            },
            "order_note": f"Anti-Matrix Application Fee - {job.title} ({duration_label})"
        }

        if notify_url:
            payload["order_meta"]["notify_url"] = notify_url

        # Safe structured logging (no credentials or secrets logged)
        logger.info(f"Cashfree environment: {env}")
        logger.info(f"Cashfree order creation started (Order ID: {order_id}, Base: INR {base_amount}, GST 18%: INR {gst_amount}, Total: INR {total_amount})")
        logger.info(f"Cashfree order return URL configured: {formatted_return_url}")

        # Isolated automated unit testing mode
        if env == 'test':
            mock_session_id = f"session_test_{order_id}_{uuid.uuid4().hex[:8]}"
            logger.info(f"Cashfree order created (Test Simulation): {order_id}")
            return True, {
                "order_id": order_id,
                "payment_session_id": mock_session_id,
                "order_status": "ACTIVE",
                "order_amount": total_amount,
                "base_amount": base_amount,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "order_currency": "INR",
                "is_sandbox_simulation": True
            }, None

        # Verify Sandbox credentials presence
        if not cfg['client_id'] or not cfg['client_secret'] or cfg['client_id'].startswith('your_') or cfg['client_secret'].startswith('your_'):
            logger.error(f"Cashfree {env.upper()} credentials not configured. Please set CASHFREE_APP_ID and CASHFREE_SECRET_KEY.")
            return False, None, f"Cashfree {env.capitalize()} credentials are not configured. Please set CASHFREE_APP_ID and CASHFREE_SECRET_KEY in your environment."

        # Execute Live Sandbox / Production Cashfree API call
        endpoint = f"{cfg['base_url']}/orders"
        try:
            response = requests.post(
                endpoint,
                headers=cls.get_headers(),
                data=json.dumps(payload),
                timeout=15
            )
            data = response.json()
            if response.status_code in [200, 201]:
                payment_session_id = data.get('payment_session_id')
                if not payment_session_id:
                    logger.warning(f"Cashfree order created but payment_session_id missing: {order_id}")
                    return False, data, "Cashfree gateway did not return a valid payment_session_id."
                logger.info(f"Cashfree order created: {order_id}")
                return True, data, None
            else:
                error_msg = data.get('message') or data.get('error', {}).get('message') or f"Cashfree API Error ({response.status_code})"
                logger.warning(f"Cashfree order creation failed ({response.status_code}): {error_msg}")
                return False, data, error_msg
        except Exception as e:
            logger.error(f"Network error connecting to Cashfree PG: {type(e).__name__}")
            return False, None, f"Network error connecting to Cashfree PG: {str(e)}"

    @classmethod
    def get_order_status(cls, order_id: str):
        """Retrieve the order details directly from Cashfree."""
        cfg = cls.get_config()
        env = cfg['environment']

        if env == 'test':
            sim_amount = 234.82
            try:
                from models import Payment
                p = Payment.query.filter_by(cashfree_order_id=order_id).first()
                if p and p.amount:
                    sim_amount = float(p.amount)
            except Exception:
                pass
            return True, {
                "order_id": order_id,
                "order_status": "PAID",
                "order_amount": sim_amount
            }, None

        if not cfg['client_id'] or not cfg['client_secret'] or cfg['client_id'].startswith('your_') or cfg['client_secret'].startswith('your_'):
            return False, None, f"Cashfree {env.capitalize()} credentials are not configured."

        endpoint = f"{cfg['base_url']}/orders/{order_id}"
        try:
            response = requests.get(
                endpoint,
                headers=cls.get_headers(),
                timeout=15
            )
            data = response.json()
            if response.status_code == 200:
                return True, data, None
            else:
                error_msg = data.get('message') or f"Unable to fetch Cashfree order status ({response.status_code})"
                return False, data, error_msg
        except Exception as e:
            return False, None, f"Network error querying Cashfree order: {str(e)}"

    @classmethod
    def get_order_payments(cls, order_id: str):
        """Retrieve all payment transactions for a given Cashfree order."""
        cfg = cls.get_config()
        env = cfg['environment']

        if env == 'test':
            sim_amount = 234.82
            try:
                from models import Payment
                p = Payment.query.filter_by(cashfree_order_id=order_id).first()
                if p and p.amount:
                    sim_amount = float(p.amount)
            except Exception:
                pass
            return True, [{
                "payment_status": "SUCCESS",
                "cf_payment_id": f"cf_sim_{order_id}",
                "payment_amount": sim_amount,
                "payment_currency": "INR",
                "payment_time": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }], None

        if not cfg['client_id'] or not cfg['client_secret'] or cfg['client_id'].startswith('your_') or cfg['client_secret'].startswith('your_'):
            return False, None, f"Cashfree {env.capitalize()} credentials are not configured."

        endpoint = f"{cfg['base_url']}/orders/{order_id}/payments"
        try:
            response = requests.get(
                endpoint,
                headers=cls.get_headers(),
                timeout=15
            )
            data = response.json()
            if response.status_code == 200:
                return True, data, None
            else:
                error_msg = data.get('message') if isinstance(data, dict) else f"Cashfree Payments Error ({response.status_code})"
                return False, data, error_msg
        except Exception as e:
            return False, None, f"Network error querying Cashfree payments: {str(e)}"

    @classmethod
    def verify_order_payment(cls, order_id: str, expected_amount: float = None):
        """
        Verify payment status server-side from Cashfree.
        If expected_amount is provided, also validates that the paid amount matches expected_amount.
        Returns (is_paid, payment_status_string, payment_info_dict, error_message).
        """
        logger.info(f"Cashfree payment verification started (Order ID: {order_id}, Expected Amount: {expected_amount})")
        success, payments_data, err = cls.get_order_payments(order_id)
        
        if success and isinstance(payments_data, list) and len(payments_data) > 0:
            # Check for successful payment attempt
            for pay in payments_data:
                p_status = pay.get('payment_status', '').upper()
                if p_status == 'SUCCESS':
                    paid_amt = float(pay.get('payment_amount', 0))
                    if expected_amount is not None and abs(paid_amt - float(expected_amount)) > 0.05:
                        logger.warning(f"Cashfree payment amount mismatch for {order_id}: expected {expected_amount}, received {paid_amt}")
                        return False, 'AMOUNT_MISMATCH', pay, f"Payment amount mismatch: expected ₹{expected_amount:.2f}, but received ₹{paid_amt:.2f}"
                    logger.info(f"Cashfree payment status: SUCCESS for Order ID: {order_id} (Amount: ₹{paid_amt:.2f})")
                    return True, 'SUCCESS', pay, None
                elif p_status in ['FAILED', 'USER_DROPPED', 'CANCELLED']:
                    logger.info(f"Cashfree payment status: {p_status} for Order ID: {order_id}")
                    return False, p_status, pay, None
                elif p_status == 'PENDING':
                    logger.info(f"Cashfree payment status: PENDING for Order ID: {order_id}")
                    return False, 'PENDING', pay, None

            # If none succeeded, return latest payment's status
            latest = payments_data[-1]
            p_status = latest.get('payment_status', 'FAILED')
            logger.info(f"Cashfree payment status: {p_status} for Order ID: {order_id}")
            return False, p_status, latest, None

        # Fallback to checking order status directly
        ord_success, order_data, ord_err = cls.get_order_status(order_id)
        if ord_success and isinstance(order_data, dict):
            ord_status = order_data.get('order_status', '').upper()
            if ord_status == 'PAID':
                paid_amt = float(order_data.get('order_amount', 0))
                if expected_amount is not None and abs(paid_amt - float(expected_amount)) > 0.05:
                    logger.warning(f"Cashfree order amount mismatch for {order_id}: expected {expected_amount}, received {paid_amt}")
                    return False, 'AMOUNT_MISMATCH', order_data, f"Order amount mismatch: expected ₹{expected_amount:.2f}, but received ₹{paid_amt:.2f}"
                logger.info(f"Cashfree payment status: SUCCESS (Order Paid) for Order ID: {order_id} (Amount: ₹{paid_amt:.2f})")
                return True, 'SUCCESS', order_data, None
            elif ord_status == 'ACTIVE':
                logger.info(f"Cashfree payment status: PENDING (Order Active) for Order ID: {order_id}")
                return False, 'PENDING', order_data, None
            elif ord_status in ['EXPIRED', 'TERMINATED']:
                logger.info(f"Cashfree payment status: FAILED (Order {ord_status}) for Order ID: {order_id}")
                return False, 'FAILED', order_data, None

        logger.warning(f"Cashfree payment verification status: UNKNOWN for Order ID: {order_id} - {err or ord_err}")
        return False, 'UNKNOWN', None, err or ord_err or "No payment records found for order"

    @classmethod
    def verify_webhook_signature(cls, signature: str, timestamp: str, raw_body: bytes) -> bool:
        """
        Verify Cashfree Webhook signature using HMAC-SHA256.
        Formula: HMAC_SHA256(timestamp + raw_body, client_secret) base64 encoded.
        """
        if not signature or not timestamp:
            return False

        cfg = cls.get_config()
        client_secret = cfg['client_secret']
        if not client_secret:
            return False

        try:
            message = timestamp.encode('utf-8') + raw_body
            computed_hmac = hmac.new(
                client_secret.encode('utf-8'),
                message,
                hashlib.sha256
            ).digest()
            computed_signature = base64.b64encode(computed_hmac).decode('utf-8')
            return hmac.compare_digest(computed_signature, signature)
        except Exception:
            return False

