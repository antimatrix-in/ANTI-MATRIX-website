import logging
from datetime import datetime, timezone, date, timedelta
from flask import current_app
from models import db, MoneyTransaction, Payment, JobApplication

logger = logging.getLogger(__name__)

# Standard Categories for Income and Expense
STANDARD_INCOME_CATEGORIES = [
    "Internship Application Fee",
    "Website Development",
    "Software Development",
    "Mobile App Development",
    "Digital Services",
    "Consulting",
    "Other Income"
]

STANDARD_EXPENSE_CATEGORIES = [
    "Domain",
    "Hosting",
    "Server",
    "Software",
    "API",
    "Advertising",
    "Marketing",
    "Salary",
    "Office",
    "Internet",
    "Travel",
    "Equipment",
    "Development",
    "Other Expense"
]

PAYMENT_METHODS = [
    "Cashfree",
    "Bank Transfer",
    "UPI",
    "Cash",
    "Credit Card",
    "Debit Card",
    "Cheque",
    "Other"
]

# ==============================================================================
# MONEY MANAGEMENT SECURITY & PERMISSION BOUNDARY
# ==============================================================================
# RULE:
# 1. No AI prompt, LLM agent, natural-language command, chatbot, or automated prompt
#    mechanism has write access (INSERT, UPDATE, DELETE) to Money Management transactions.
# 2. AI / Prompt systems have strictly READ-ONLY access (e.g. summary, analytics, search).
# 3. Only an authenticated Administrator explicitly submitting the web form in the
#    Admin Dashboard (Money Management -> Transaction History -> Edit) may update an existing transaction.
# 4. Cashfree automatic transactions are immutable regarding core payment facts.
# ==============================================================================


def validate_manual_admin_mutation(user, txn=None, action="edit"):
    """
    Enforces the non-negotiable security boundary for Money Management write operations.
    
    Requirements:
    - User must be authenticated and have role == 'admin'.
    - Action must be explicit manual admin action.
    - If modifying an existing transaction (edit/delete), Cashfree automatic records are locked.
    
    Returns:
        (is_allowed: bool, error_message: str or None)
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False, "Authentication required. Only authenticated administrators can modify transactions."

    role = (getattr(user, 'role', '') or '').strip().lower()
    if role != 'admin':
        return False, "Unauthorized. Only administrators have permission to modify transaction records."

    if txn:
        # Check source protection for Cashfree transactions
        if txn.source != 'MANUAL' and action in ['edit', 'delete']:
            return False, "Cashfree automatic transactions cannot be manually modified or deleted."

    return True, None


def record_cashfree_income(application, payment, payment_details=None, env=None):
    """
    Safely and idempotently record a verified Cashfree payment as an INCOME transaction in Money Management.
    
    This function is strictly called upon backend verification of a PAID status.
    It guarantees duplicate prevention using cashfree_order_id and cf_payment_id.
    """
    if not application or not payment:
        logger.warning("[MoneyService] Missing application or payment object for cashfree income recording.")
        return False, None, "Missing application or payment object."

    order_id = payment.cashfree_order_id
    cf_payment_id = payment.cf_payment_id or (payment_details.get('cf_payment_id') if isinstance(payment_details, dict) else None)

    # 1. Idempotency Check: Verify if transaction has already been recorded
    existing_txn = None
    if order_id:
        existing_txn = MoneyTransaction.query.filter_by(cashfree_order_id=order_id).first()
    
    if not existing_txn and cf_payment_id:
        existing_txn = MoneyTransaction.query.filter_by(
            provider='CASHFREE',
            provider_transaction_id=str(cf_payment_id)
        ).first()

    if existing_txn:
        logger.info(f"[MoneyService] Cashfree order {order_id} already recorded in MoneyTransaction (ID: {existing_txn.id}). Skipping.")
        return True, existing_txn, "Already recorded"

    # 2. Determine Environment (SANDBOX vs PRODUCTION vs TEST)
    if not env:
        if current_app:
            if current_app.config.get('PAYMENT_TEST_MODE', False) and payment.gateway == 'TEST':
                env = 'TEST'
            else:
                raw_env = (
                    current_app.config.get('CASHFREE_ENVIRONMENT') or 
                    current_app.config.get('CASHFREE_ENV') or 
                    'sandbox'
                ).strip().lower()
                env = 'PRODUCTION' if raw_env == 'production' else 'SANDBOX'
        else:
            env = 'SANDBOX'
    else:
        env = env.strip().upper()

    now_utc = datetime.now(timezone.utc)
    txn_date = now_utc.date()
    txn_time = now_utc.strftime('%I:%M %p')

    # 3. Create MoneyTransaction
    amount = float(payment.amount or application.application_fee or 0)
    job_title = application.job.title if application.job else "Internship Application"
    app_code = application.formatted_code

    if getattr(payment, 'base_amount', None) and getattr(payment, 'gst_amount', None):
        description = f"Anti Matrix Internship Application Fee - {job_title} ({app_code}) [Base: ₹{payment.base_amount:.2f} + GST 18%: ₹{payment.gst_amount:.2f}]"
    elif getattr(application, 'base_amount', None) and getattr(application, 'gst_amount', None):
        description = f"Anti Matrix Internship Application Fee - {job_title} ({app_code}) [Base: ₹{application.base_amount:.2f} + GST 18%: ₹{application.gst_amount:.2f}]"
    else:
        description = f"Anti Matrix Internship Application Fee - {job_title} ({app_code})"
    purpose = f"Application Fee: {job_title}"
    ref = cf_payment_id or order_id

    try:
        txn = MoneyTransaction(
            transaction_type='INCOME',
            amount=amount,
            transaction_date=txn_date,
            transaction_time=txn_time,
            category='Internship Application Fee',
            purpose=purpose,
            description=description,
            payment_method='Cashfree',
            reference=ref,
            source='AUTOMATIC',
            provider='CASHFREE',
            provider_transaction_id=str(cf_payment_id) if cf_payment_id else None,
            cashfree_order_id=order_id,
            application_id=application.id,
            user_id=application.user_id,
            job_id=application.job_id,
            environment=env,
            created_at=now_utc,
            updated_at=now_utc
        )
        db.session.add(txn)
        db.session.commit()
        logger.info(f"[MoneyService] Successfully recorded Cashfree INCOME transaction (ID: {txn.id}) for Order: {order_id}, Amount: ₹{amount}")
        return True, txn, None
    except Exception as e:
        db.session.rollback()
        logger.error(f"[MoneyService] Error recording Cashfree income transaction for Order {order_id}: {str(e)}")
        return False, None, str(e)


def get_financial_summary(env_filter='all', date_filter='all', start_date=None, end_date=None, category_filter='all', search_query=None):
    """
    Calculate financial totals and summary metrics dynamically from database transaction records.
    No hardcoded totals. All math is database-backed.
    """
    today = datetime.now(timezone.utc).date()
    
    # Base query for all transactions
    all_txns = MoneyTransaction.query.all()

    # Calculate overall breakdown across all recorded transactions
    prod_income = sum(t.amount for t in all_txns if t.is_income and t.environment in ['PRODUCTION', 'MANUAL'])
    prod_expense = sum(t.amount for t in all_txns if t.is_expense and t.environment in ['PRODUCTION', 'MANUAL'])
    prod_balance = prod_income - prod_expense

    sandbox_income = sum(t.amount for t in all_txns if t.is_income and t.environment in ['SANDBOX', 'TEST'])
    sandbox_expense = sum(t.amount for t in all_txns if t.is_expense and t.environment in ['SANDBOX', 'TEST'])
    sandbox_balance = sandbox_income - sandbox_expense

    manual_income = sum(t.amount for t in all_txns if t.is_income and t.is_manual)
    manual_expense = sum(t.amount for t in all_txns if t.is_expense and t.is_manual)

    cashfree_income = sum(t.amount for t in all_txns if t.is_income and t.is_cashfree)

    # Calculate Today's figures
    today_income = sum(t.amount for t in all_txns if t.is_income and t.transaction_date == today)
    today_expense = sum(t.amount for t in all_txns if t.is_expense and t.transaction_date == today)

    # Calculate This Month's figures (same year and month)
    month_income = sum(t.amount for t in all_txns if t.is_income and t.transaction_date and t.transaction_date.year == today.year and t.transaction_date.month == today.month)
    month_expense = sum(t.amount for t in all_txns if t.is_expense and t.transaction_date and t.transaction_date.year == today.year and t.transaction_date.month == today.month)

    # Now calculate filtered totals based on current view/filter selections
    filtered_txns = filter_transactions(
        env_filter=env_filter,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        category_filter=category_filter,
        search_query=search_query
    ).all()

    filtered_income = sum(t.amount for t in filtered_txns if t.is_income)
    filtered_expense = sum(t.amount for t in filtered_txns if t.is_expense)
    filtered_balance = filtered_income - filtered_expense

    return {
        # Current Active Filter View Totals
        'total_income': filtered_income,
        'total_expense': filtered_expense,
        'balance': filtered_balance,
        'transaction_count': len(filtered_txns),
        
        # Production vs Sandbox Breakdown
        'production_income': prod_income,
        'production_expense': prod_expense,
        'production_balance': prod_balance,
        'sandbox_income': sandbox_income,
        'sandbox_expense': sandbox_expense,
        'sandbox_balance': sandbox_balance,

        # Source Breakdown
        'manual_income': manual_income,
        'manual_expense': manual_expense,
        'cashfree_income': cashfree_income,

        # Time Periods
        'today_income': today_income,
        'today_expense': today_expense,
        'month_income': month_income,
        'month_expense': month_expense,
        'all_time_count': len(all_txns)
    }


def filter_transactions(type_filter='all', env_filter='all', date_filter='all', 
                        start_date=None, end_date=None, category_filter='all', 
                        search_query=None, sort_by='newest'):
    """
    Build a SQLAlchemy query for MoneyTransaction applying all filters and search parameters.
    """
    query = MoneyTransaction.query

    # 1. Type Filter (INCOME / EXPENSE)
    if type_filter and type_filter.lower() in ['income', 'expense']:
        query = query.filter(MoneyTransaction.transaction_type == type_filter.upper())

    # 2. Environment Filter (PRODUCTION / SANDBOX / MANUAL)
    if env_filter and env_filter.lower() != 'all':
        env_val = env_filter.lower()
        if env_val == 'production':
            query = query.filter(MoneyTransaction.environment.in_(['PRODUCTION', 'MANUAL']))
        elif env_val == 'sandbox':
            query = query.filter(MoneyTransaction.environment.in_(['SANDBOX', 'TEST']))
        elif env_val == 'manual':
            query = query.filter(MoneyTransaction.source == 'MANUAL')

    # 3. Category Filter
    if category_filter and category_filter.lower() != 'all':
        query = query.filter(MoneyTransaction.category == category_filter)

    # 4. Date Filter
    today = datetime.now(timezone.utc).date()
    if date_filter == 'today':
        query = query.filter(MoneyTransaction.transaction_date == today)
    elif date_filter == 'this_week':
        start_of_week = today - timedelta(days=today.weekday())
        query = query.filter(MoneyTransaction.transaction_date >= start_of_week, MoneyTransaction.transaction_date <= today)
    elif date_filter == 'this_month':
        start_of_month = date(today.year, today.month, 1)
        query = query.filter(MoneyTransaction.transaction_date >= start_of_month, MoneyTransaction.transaction_date <= today)
    elif date_filter == 'custom':
        if start_date:
            try:
                if isinstance(start_date, str):
                    s_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                else:
                    s_date = start_date
                query = query.filter(MoneyTransaction.transaction_date >= s_date)
            except Exception:
                pass
        if end_date:
            try:
                if isinstance(end_date, str):
                    e_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                else:
                    e_date = end_date
                query = query.filter(MoneyTransaction.transaction_date <= e_date)
            except Exception:
                pass

    # 5. Search Query
    if search_query:
        q = f"%{search_query.strip()}%"
        # Join JobApplication for application_code search if needed
        query = query.outerjoin(JobApplication, MoneyTransaction.application_id == JobApplication.id).filter(
            (MoneyTransaction.category.ilike(q)) |
            (MoneyTransaction.purpose.ilike(q)) |
            (MoneyTransaction.description.ilike(q)) |
            (MoneyTransaction.reference.ilike(q)) |
            (MoneyTransaction.cashfree_order_id.ilike(q)) |
            (MoneyTransaction.provider_transaction_id.ilike(q)) |
            (MoneyTransaction.payment_method.ilike(q)) |
            (JobApplication.application_code.ilike(q)) |
            (JobApplication.full_name.ilike(q))
        )

    # 6. Sorting
    if sort_by == 'oldest':
        query = query.order_by(MoneyTransaction.transaction_date.asc(), MoneyTransaction.id.asc())
    elif sort_by == 'highest':
        query = query.order_by(MoneyTransaction.amount.desc(), MoneyTransaction.transaction_date.desc())
    elif sort_by == 'lowest':
        query = query.order_by(MoneyTransaction.amount.asc(), MoneyTransaction.transaction_date.desc())
    else:  # newest default
        query = query.order_by(MoneyTransaction.transaction_date.desc(), MoneyTransaction.id.desc())

    return query


def reconcile_cashfree_payments():
    """
    Scan all paid Payment records and ensure a corresponding MoneyTransaction exists.
    Returns (count_added, total_checked).
    """
    paid_payments = Payment.query.filter_by(payment_status='paid').all()
    count_added = 0
    
    for payment in paid_payments:
        if not payment.application:
            continue
        order_id = payment.cashfree_order_id
        existing = MoneyTransaction.query.filter_by(cashfree_order_id=order_id).first()
        if not existing and payment.cf_payment_id:
            existing = MoneyTransaction.query.filter_by(
                provider='CASHFREE',
                provider_transaction_id=str(payment.cf_payment_id)
            ).first()
        
        if not existing:
            success, txn, err = record_cashfree_income(
                application=payment.application,
                payment=payment
            )
            if success:
                count_added += 1

    return count_added, len(paid_payments)


def clear_all_transactions(admin_user=None):
    """
    Safely and permanently deletes ONLY records from the MoneyTransaction ledger table.
    Preserves all Users, JobPostings, JobApplications, Payments, Employees, and DocumentTemplates.
    Operates inside an atomic database transaction.
    Returns (success, deleted_count, error_message).
    """
    try:
        count = MoneyTransaction.query.count()
        if count > 0:
            # Delete only MoneyTransaction records
            MoneyTransaction.query.delete()
            db.session.commit()
            if admin_user:
                logger.warning(
                    f"[MoneyService] Admin ID {getattr(admin_user, 'id', 'unknown')} ({getattr(admin_user, 'email', 'unknown')}) permanently cleared all {count} MoneyTransaction ledger records."
                )
            else:
                logger.warning(f"[MoneyService] Permanently cleared all {count} MoneyTransaction ledger records.")
        return True, count, None
    except Exception as e:
        db.session.rollback()
        logger.error(f"[MoneyService] Error clearing MoneyTransaction ledger: {str(e)}", exc_info=True)
        return False, 0, str(e)

