import os
import re
import time
import uuid
import json
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app, abort, send_from_directory
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
from models import db, ContactInquiry, JobPosting, JobApplication, Payment
from services.cashfree_service import CashfreeService
from config import (
    INTERNSHIP_FEES, INTERNSHIP_PRICING,
    INDIA_STATES_AND_CITIES, EDUCATION_LEVELS, COMMON_DEGREES, GRADUATION_YEARS
)

main_bp = Blueprint('main', __name__)

EMAIL_REGEX = re.compile(r'^\S+@\S+\.\S+$')
URL_REGEX = re.compile(r'^https?://\S+$', re.IGNORECASE)
INDIAN_PHONE_REGEX = re.compile(r'^(?:\+?91[\-\s]?)?[6-9]\d{9}$')
PINCODE_REGEX = re.compile(r'^[1-9][0-9]{5}$')

ALLOWED_DOC_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
ALLOWED_RESUME_EXTENSIONS = {'pdf', 'doc', 'docx'}
DISALLOWED_EXTENSIONS = {'exe', 'bat', 'cmd', 'sh', 'php', 'js', 'py', 'vbs', 'scr', 'msi', 'bin', 'jar'}

SUBJECT_OPTIONS = [
    'New Project Inquiry',
    'Pricing & Packages',
    'Partnership Opportunity',
    'Support & Maintenance',
    'Careers',
    'Other'
]


def save_secure_file(file_obj, upload_folder, prefix, job_id, allowed_exts, required=True):
    """Safely validate, rename and store an uploaded document."""
    if not file_obj or not file_obj.filename:
        if required:
            return None, None, "File is required"
        return None, None, None

    filename = file_obj.filename
    if '.' not in filename:
        return None, None, "Invalid file format: missing file extension"

    ext = filename.rsplit('.', 1)[1].lower()
    if ext in DISALLOWED_EXTENSIONS or ext not in allowed_exts:
        return None, None, f"Invalid file format '.{ext}'. Allowed: {', '.join(sorted(allowed_exts)).upper()}"

    # Check file size (Read up to 16MB)
    file_obj.seek(0, os.SEEK_END)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > 16 * 1024 * 1024:
        return None, None, f"File size exceeds 16 MB limit ({(size/1024/1024):.1f} MB)"

    safe_base = secure_filename(filename.rsplit('.', 1)[0])[:30] or prefix
    safe_base = re.sub(r'[^a-zA-Z0-9_-]', '_', safe_base)
    unique_filename = f"{prefix}_j{job_id}_{int(time.time())}_{uuid.uuid4().hex[:6]}_{safe_base}.{ext}"

    os.makedirs(upload_folder, exist_ok=True)
    save_path = os.path.join(upload_folder, unique_filename)
    file_obj.save(save_path)
    return unique_filename, save_path, None


@main_bp.route('/')
def home():
    return render_template('pages/home.html')


@main_bp.route('/about')
def about():
    return render_template('pages/about.html')


@main_bp.route('/services')
def services():
    return render_template('pages/services.html')


@main_bp.route('/pricing')
def pricing():
    if current_user.is_authenticated:
        return render_template('pages/pricing.html')
    return render_template('pages/pricing_locked.html')


@main_bp.route('/careers')
def careers():
    jobs = JobPosting.query.filter_by(is_active=True).order_by(JobPosting.created_at.desc()).all()
    return render_template('pages/careers.html', jobs=jobs)


@main_bp.route('/careers/apply/<int:job_id>', methods=['GET', 'POST'])
def apply_job(job_id):
    # Server-Side Authentication Enforcement
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.path))

    job = db.session.get(JobPosting, job_id) or abort(404)
    if not job.is_active:
        flash('This position is currently not accepting new applications.', 'warning')
        return redirect(url_for('main.careers'))

    # Duplicate Application Protection for Authenticated User
    existing_paid = JobApplication.query.filter(
        JobApplication.job_id == job.id,
        ((JobApplication.user_id == current_user.id) | (JobApplication.email == current_user.email.lower())),
        (JobApplication.payment_status == 'paid') | (JobApplication.application_status == 'submitted')
    ).first()

    if existing_paid:
        flash(f"You have already applied for this position ({job.title}). Application ID: {existing_paid.formatted_code}.", 'info')
        return redirect(url_for('main.my_applications'))

    if request.method == 'POST':
        # 1. Personal Details
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        full_name = f"{first_name} {last_name}".strip()
        if not full_name and request.form.get('full_name'):
            full_name = (request.form.get('full_name') or '').strip()
            parts = full_name.split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''

        email = (request.form.get('email') or '').strip().lower()
        phone = (request.form.get('phone') or request.form.get('phone_number') or '').strip()
        address = (request.form.get('address') or '').strip()
        state = (request.form.get('state') or '').strip()
        city = (request.form.get('city') or '').strip()
        pincode = (request.form.get('pincode') or '').strip()

        # 2. Education Details
        education_level = (request.form.get('education_level') or request.form.get('education') or '').strip()
        degree = (request.form.get('degree') or '').strip()
        major = (request.form.get('major') or request.form.get('department') or '').strip()
        graduation_year_str = (request.form.get('graduation_year') or '').strip()

        # Legacy / Optional Fields
        college = (request.form.get('college') or '').strip()
        department = (request.form.get('department') or major).strip()
        year_of_study = (request.form.get('year_of_study') or '').strip()
        cgpa_str = (request.form.get('current_cgpa') or '').strip()
        experience = (request.form.get('experience') or '').strip()
        skills = (request.form.get('skills') or '').strip()
        portfolio_url = (request.form.get('portfolio_url') or '').strip()
        linkedin_url = (request.form.get('linkedin_url') or '').strip()
        github_url = (request.form.get('github_url') or '').strip()
        cover_letter = (request.form.get('cover_letter') or '').strip()
        why_join = (request.form.get('why_join') or '').strip()

        errors = []

        # Validate Personal Information
        if not first_name:
            errors.append('First Name is required.')
        if not last_name:
            errors.append('Last Name is required.')
        if not email:
            errors.append('Email is required.')
        elif not EMAIL_REGEX.match(email):
            errors.append('Please provide a valid email address.')
        if not phone:
            errors.append('Phone Number is required.')
        elif not INDIAN_PHONE_REGEX.match(phone) and len(re.sub(r'\D', '', phone)) != 10:
            errors.append('Please enter a valid 10-digit Indian phone number.')

        if not address:
            errors.append('Address is required.')
        if not state:
            errors.append('State is required.')
        elif state not in INDIA_STATES_AND_CITIES:
            errors.append('Please select a valid Indian state from the list.')

        if not city:
            errors.append('City is required.')
        elif state in INDIA_STATES_AND_CITIES:
            valid_cities = [c.lower() for c in INDIA_STATES_AND_CITIES[state]]
            if city.lower() not in valid_cities:
                errors.append(f'Selected city is not valid for state {state}.')

        if not pincode:
            errors.append('Pincode is required.')
        elif not PINCODE_REGEX.match(pincode):
            errors.append('Please enter a valid 6-digit Indian pincode (e.g., 600001).')

        # Validate Education
        if not education_level:
            errors.append('Education level is required.')
        if not degree:
            errors.append('Degree is required.')
        if not major:
            errors.append('Major / Specialization is required.')

        graduation_year = None
        if not graduation_year_str:
            errors.append('Graduation Year is required.')
        else:
            try:
                grad_yr_int = int(re.sub(r'\D', '', graduation_year_str))
                if grad_yr_int > 2029:
                    errors.append('Graduation Year cannot be greater than 2029.')
                else:
                    graduation_year = str(grad_yr_int)
            except ValueError:
                errors.append('Please select a valid graduation year up to 2029.')

        current_cgpa = None
        if cgpa_str:
            try:
                current_cgpa = float(cgpa_str)
                if current_cgpa < 0.0 or current_cgpa > 10.0:
                    errors.append('CGPA must be between 0.0 and 10.0.')
            except ValueError:
                errors.append('Please enter a valid numeric CGPA.')

        # Validate URLs if provided
        if portfolio_url and not URL_REGEX.match(portfolio_url):
            errors.append('Portfolio URL must start with http:// or https://')
        if linkedin_url and not URL_REGEX.match(linkedin_url):
            errors.append('LinkedIn URL must start with http:// or https://')
        if github_url and not URL_REGEX.match(github_url):
            errors.append('GitHub URL must start with http:// or https://')

        # Document Folders
        resumes_folder = current_app.config.get('UPLOAD_FOLDER_RESUMES', os.path.join(current_app.root_path, 'uploads', 'resumes'))
        docs_folder = current_app.config.get('UPLOAD_FOLDER_DOCUMENTS', os.path.join(current_app.root_path, 'uploads', 'documents'))

        # Resume File (Always Required)
        resume_file = request.files.get('resume')
        resume_fname, resume_fpath, resume_err = save_secure_file(
            resume_file, resumes_folder, 'resume', job.id, ALLOWED_RESUME_EXTENSIONS, required=True
        )
        if resume_err:
            errors.append(f"Resume: {resume_err}")

        # Conditional Proofs based on job duration
        aadhaar_fname, aadhaar_fpath = None, None
        pan_fname, pan_fpath = None, None
        college_id_fname, college_id_fpath = None, None

        if job.duration == '3_months':
            # 3 Months: Aadhaar is REQUIRED
            aadhaar_file = request.files.get('aadhaar')
            aadhaar_fname, aadhaar_fpath, aadhaar_err = save_secure_file(
                aadhaar_file, docs_folder, 'aadhaar', job.id, ALLOWED_DOC_EXTENSIONS, required=True
            )
            if aadhaar_err:
                errors.append(f"Aadhaar Card: {aadhaar_err}")

            # 3 Months: PAN Card is OPTIONAL
            pan_file = request.files.get('pan')
            if pan_file and pan_file.filename:
                pan_fname, pan_fpath, pan_err = save_secure_file(
                    pan_file, docs_folder, 'pan', job.id, ALLOWED_DOC_EXTENSIONS, required=False
                )
                if pan_err:
                    errors.append(f"PAN Card: {pan_err}")

            # 3 Months: College ID is OPTIONAL
            college_id_file = request.files.get('college_id')
            if college_id_file and college_id_file.filename:
                college_id_fname, college_id_fpath, college_id_err = save_secure_file(
                    college_id_file, docs_folder, 'college_id', job.id, ALLOWED_DOC_EXTENSIONS, required=False
                )
                if college_id_err:
                    errors.append(f"College ID Card: {college_id_err}")

        # If errors, re-render form with inputs and error alerts
        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template(
                'pages/job_apply.html',
                job=job,
                form_data=request.form,
                states_and_cities=INDIA_STATES_AND_CITIES,
                education_levels=EDUCATION_LEVELS,
                common_degrees=COMMON_DEGREES,
                graduation_years=GRADUATION_YEARS
            )

        # Check for existing unpaid draft application to reuse/update
        application = JobApplication.query.filter(
            JobApplication.job_id == job.id,
            ((JobApplication.user_id == current_user.id) | (JobApplication.email == email))
        ).filter(JobApplication.payment_status != 'paid').first()

        is_internship = job.is_internship
        fee_inr = job.fee_inr if is_internship else 0

        if not application:
            application = JobApplication(
                job_id=job.id,
                user_id=current_user.id,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                email=email,
                phone=phone,
                address=address,
                state=state,
                city=city,
                pincode=pincode,
                education_level=education_level,
                college=college,
                department=department,
                degree=degree,
                major=major,
                year_of_study=year_of_study,
                graduation_year=graduation_year or graduation_year_str,
                current_cgpa=current_cgpa,
                experience=experience,
                skills=skills,
                portfolio_url=portfolio_url or None,
                linkedin_url=linkedin_url or None,
                github_url=github_url or None,
                cover_letter=cover_letter,
                why_join=why_join or None,
                aadhaar_filename=aadhaar_fname,
                aadhaar_path=aadhaar_fpath,
                pan_filename=pan_fname,
                pan_path=pan_fpath,
                college_id_filename=college_id_fname,
                college_id_path=college_id_fpath,
                resume_filename=resume_fname,
                resume_path=resume_fpath,
                duration=job.duration if is_internship else None,
                application_fee=fee_inr,
                payment_status='pending' if is_internship else 'exempt',
                application_status='pending_payment' if is_internship else 'submitted',
                status='New'
            )
            db.session.add(application)
            db.session.flush()
            if not is_internship or fee_inr == 0:
                application.application_code = f"AM-APP-{application.id:06d}"
            else:
                application.application_code = None
        else:
            # Update existing draft application
            application.user_id = current_user.id
            application.first_name = first_name
            application.last_name = last_name
            application.full_name = full_name
            application.phone = phone
            application.address = address
            application.state = state
            application.city = city
            application.pincode = pincode
            application.education_level = education_level
            application.college = college
            application.department = department
            application.degree = degree
            application.major = major
            application.year_of_study = year_of_study
            application.graduation_year = graduation_year or graduation_year_str
            application.current_cgpa = current_cgpa
            application.experience = experience
            application.skills = skills
            application.portfolio_url = portfolio_url or None
            application.linkedin_url = linkedin_url or None
            application.github_url = github_url or None
            application.cover_letter = cover_letter
            application.why_join = why_join or None
            if aadhaar_fname:
                application.aadhaar_filename = aadhaar_fname
                application.aadhaar_path = aadhaar_fpath
            if pan_fname:
                application.pan_filename = pan_fname
                application.pan_path = pan_fpath
            if college_id_fname:
                application.college_id_filename = college_id_fname
                application.college_id_path = college_id_fpath
            if resume_fname:
                application.resume_filename = resume_fname
                application.resume_path = resume_fpath
            application.duration = job.duration if is_internship else None
            application.application_fee = fee_inr
            application.payment_status = 'pending' if is_internship else 'exempt'
            application.application_status = 'pending_payment' if is_internship else 'APPLIED'
            application.status = 'APPLIED' if not is_internship else 'New'
            if not is_internship or fee_inr == 0:
                if not application.application_code:
                    application.application_code = f"AM-APP-{application.id:06d}"

        db.session.commit()

        if is_internship and fee_inr > 0:
            # Redirect candidate to Review & Payment step
            return redirect(url_for('main.job_apply_review', app_id=application.id))
        else:
            # Exempt/Free application submission
            flash(f"Application submitted successfully! Application reference: {application.formatted_code}.", 'success')
            return redirect(url_for('main.job_apply_success', app_id=application.id))

    # Pre-fill name and email for authenticated candidate
    name_parts = (current_user.name or '').strip().split(' ', 1)
    prefilled_form = {
        'first_name': name_parts[0] if name_parts else '',
        'last_name': name_parts[1] if len(name_parts) > 1 else '',
        'email': current_user.email
    }

    return render_template(
        'pages/job_apply.html',
        job=job,
        form_data=prefilled_form,
        states_and_cities=INDIA_STATES_AND_CITIES,
        education_levels=EDUCATION_LEVELS,
        common_degrees=COMMON_DEGREES,
        graduation_years=GRADUATION_YEARS
    )


@main_bp.route('/careers/apply/review/<int:app_id>')
def job_apply_review(app_id):
    """Candidate Review Step before initiating Cashfree Payment or Simulated Test Payment."""
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.path))

    application = db.session.get(JobApplication, app_id) or abort(404)
    if application.user_id and application.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    job = application.job
    
    # If already paid, redirect straight to success
    if application.payment_status == 'paid':
        return redirect(url_for('main.job_apply_success', app_id=application.id))

    # Calculate exact server fee & 18% GST breakdown
    base_fee = job.fee_inr if job else INTERNSHIP_FEES.get(application.duration, 199)
    from services.payment_service import calculate_payment_total
    pricing = calculate_payment_total(base_fee)
    fee_inr = pricing['total_amount']
    duration_label = job.duration_display if job else application.duration_display
    is_test_mode = current_app.config.get('PAYMENT_TEST_MODE', False)

    return render_template(
        'pages/job_apply_review.html',
        app=application,
        job=job,
        pricing=pricing,
        fee_inr=fee_inr,
        duration_label=duration_label,
        is_test_mode=is_test_mode
    )


@main_bp.route('/careers/apply/test-payment/<int:app_id>', methods=['POST'])
@main_bp.route('/application/test-payment/<int:app_id>', methods=['POST'])
def job_apply_test_payment(app_id):
    """
    Simulated Successful Payment Endpoint for Development and Testing.
    Strictly server-side controlled; performs full application finalization and email dispatch.
    """
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('main.job_apply_review', app_id=app_id)))

    # Verify test mode is active
    if not current_app.config.get('PAYMENT_TEST_MODE', False) and current_app.config.get('ENV') == 'production':
        flash('Test payment mode is disabled in production.', 'danger')
        return redirect(url_for('main.job_apply_review', app_id=app_id))

    application = db.session.get(JobApplication, app_id) or abort(404)
    if application.user_id and application.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    if application.user_id is None:
        application.user_id = current_user.id
    job = application.job
    if not job or not job.is_active:
        flash('This position is no longer accepting applications.', 'danger')
        return redirect(url_for('main.careers'))

    # Idempotency / Duplicate submission check
    if application.payment_status == 'paid':
        if not application.application_code:
            application.application_code = f"AM-APP-{application.id:06d}"
            db.session.commit()
        return redirect(url_for('main.job_apply_success', app_id=application.id))

    # 1. Determine server-side Application Base Fee & 18% GST calculation
    duration = job.duration or application.duration or '1_month'
    base_fee = INTERNSHIP_FEES.get(duration, 199)
    from services.payment_service import calculate_payment_total
    pricing = calculate_payment_total(base_fee)
    total_amount = pricing['total_amount']
    base_amount = pricing['base_amount']
    gst_rate = pricing['gst_rate']
    gst_amount = pricing['gst_amount']

    # 2. Record simulated payment with unique reference
    test_order_id = f"TEST-APP-{application.id:06d}-PAY-{int(time.time())}-{uuid.uuid4().hex[:5].upper()}"
    test_payment_id = f"test_sim_{uuid.uuid4().hex[:10]}"
    
    payment = Payment.query.filter_by(application_id=application.id).order_by(Payment.created_at.desc()).first()
    if not payment or payment.payment_status == 'paid':
        payment = Payment(
            application_id=application.id,
            cashfree_order_id=test_order_id,
            cashfree_payment_session_id=f"test_session_{uuid.uuid4().hex[:8]}",
            amount=total_amount,
            base_amount=base_amount,
            gst_rate=gst_rate,
            gst_amount=gst_amount,
            currency='INR',
            payment_status='paid',
            gateway='TEST',
            cf_payment_id=test_payment_id,
            gateway_response=json.dumps({
                "provider": "test",
                "status": "SUCCESS",
                "amount": total_amount,
                "base_amount": base_amount,
                "gst_rate": gst_rate,
                "gst_amount": gst_amount,
                "order_id": test_order_id,
                "cf_payment_id": test_payment_id,
                "mode": "SIMULATED_TEST_PAYMENT"
            })
        )
        db.session.add(payment)
    else:
        payment.cashfree_order_id = test_order_id
        payment.amount = total_amount
        payment.base_amount = base_amount
        payment.gst_rate = gst_rate
        payment.gst_amount = gst_amount
        payment.payment_status = 'paid'
        payment.gateway = 'TEST'
        payment.cf_payment_id = test_payment_id
        payment.gateway_response = json.dumps({
            "provider": "test",
            "status": "SUCCESS",
            "amount": total_amount,
            "base_amount": base_amount,
            "gst_rate": gst_rate,
            "gst_amount": gst_amount,
            "order_id": test_order_id,
            "cf_payment_id": test_payment_id,
            "mode": "SIMULATED_TEST_PAYMENT"
        })

    # 3. Finalize Application Data
    application.application_fee = int(base_amount)
    application.base_amount = base_amount
    application.gst_rate = gst_rate
    application.gst_amount = gst_amount
    application.payment_status = 'paid'
    application.application_status = 'APPLIED'
    application.status = 'APPLIED'
    if not application.application_code:
        application.application_code = f"AM-APP-{application.id:06d}"

    # Commit payment & application transaction
    db.session.commit()

    # Automatically record income in Money Management (Test Simulation)
    try:
        from services.money_service import record_cashfree_income
        record_cashfree_income(application, payment, {"simulated": True}, env='TEST')
    except Exception as e:
        current_app.logger.warning(f"Failed to record money transaction for test payment: {e}")

    # Send application success email notification
    try:
        from services.email_service import send_application_successful_email
        send_application_successful_email(application)
    except Exception as e:
        current_app.logger.warning(f"Failed to send confirmation email for test application {application.id}: {e}")

    flash("Test payment completed successfully! Your application has been submitted.", "success")
    return redirect(url_for('main.job_apply_success', app_id=application.id))


@main_bp.route('/careers/apply/checkout/<int:app_id>', methods=['POST'])
def job_apply_checkout(app_id):
    """
    Create Cashfree Order and redirect to Cashfree checkout.
    Fee is strictly calculated on server from job duration.
    If PAYMENT_TEST_MODE is enabled, smoothly delegates to job_apply_test_payment.
    """
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=url_for('main.job_apply_review', app_id=app_id)))

    # Check if Test Mode is active
    if current_app.config.get('PAYMENT_TEST_MODE', False):
        return job_apply_test_payment(app_id)

    application = db.session.get(JobApplication, app_id) or abort(404)
    if application.user_id and application.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    if application.user_id is None:
        application.user_id = current_user.id
    job = application.job
    if not job or not job.is_active:
        flash('This position is no longer accepting applications.', 'danger')
        return redirect(url_for('main.careers'))

    if application.payment_status == 'paid':
        return redirect(url_for('main.job_apply_success', app_id=application.id))

    # Construct Dynamic Canonical Return & Webhook URLs
    # Priority:
    # 1. Configured CASHFREE_RETURN_URL if explicitly customized (and not a localhost default when running publicly)
    # 2. Canonical public host: request host with https scheme (or APP_URL)
    app_url = (current_app.config.get('APP_URL') or '').strip().rstrip('/')
    is_https = request.is_secure or request.headers.get('X-Forwarded-Proto', '').lower() == 'https'
    scheme = 'https' if (is_https or (app_url and app_url.startswith('https://'))) else request.scheme
    host = request.host
    canonical_base = f"{scheme}://{host}".rstrip('/')

    configured_return = (current_app.config.get('CASHFREE_RETURN_URL') or '').strip()
    is_local_host = ('127.0.0.1' in host or 'localhost' in host)
    if configured_return and not (('127.0.0.1' in configured_return or 'localhost' in configured_return) and not is_local_host):
        return_url = configured_return
    else:
        return_url = f"{canonical_base}/payment/cashfree/return?order_id={{order_id}}"

    configured_webhook = (current_app.config.get('CASHFREE_WEBHOOK_URL') or '').strip()
    if configured_webhook and not (('127.0.0.1' in configured_webhook or 'localhost' in configured_webhook) and not is_local_host):
        webhook_url = configured_webhook
    else:
        webhook_url = f"{canonical_base}/payment/cashfree/webhook"

    success, order_data, err_msg = CashfreeService.create_order(
        application=application,
        job=job,
        return_url=return_url,
        notify_url=webhook_url
    )

    if not success or not order_data:
        flash(f"Unable to initialize payment: {err_msg}", 'danger')
        return redirect(url_for('main.job_apply_review', app_id=application.id))

    order_id = order_data.get('order_id')
    payment_session_id = order_data.get('payment_session_id')
    if not payment_session_id:
        flash("Unable to initialize payment: Payment session token was not returned by gateway.", 'danger')
        return redirect(url_for('main.job_apply_review', app_id=application.id))

    from services.payment_service import calculate_payment_total
    base_fee = job.fee_inr if job else INTERNSHIP_FEES.get(application.duration, 199)
    pricing = calculate_payment_total(base_fee)
    amount = float(order_data.get('order_amount', pricing['total_amount']))
    base_amount = pricing['base_amount']
    gst_rate = pricing['gst_rate']
    gst_amount = pricing['gst_amount']

    # Update application breakdown
    application.base_amount = base_amount
    application.gst_rate = gst_rate
    application.gst_amount = gst_amount
    application.application_fee = int(amount)

    # Reuse existing pending Payment record if present, or create a new one
    payment = Payment.query.filter_by(application_id=application.id, payment_status='pending').order_by(Payment.created_at.desc()).first()
    if not payment:
        payment = Payment(
            application_id=application.id,
            cashfree_order_id=order_id,
            cashfree_payment_session_id=payment_session_id,
            amount=amount,
            base_amount=base_amount,
            gst_rate=gst_rate,
            gst_amount=gst_amount,
            currency='INR',
            payment_status='pending',
            gateway='cashfree',
            gateway_response=json.dumps(order_data)
        )
        db.session.add(payment)
    else:
        payment.cashfree_order_id = order_id
        payment.cashfree_payment_session_id = payment_session_id
        payment.amount = amount
        payment.base_amount = base_amount
        payment.gst_rate = gst_rate
        payment.gst_amount = gst_amount
        payment.currency = 'INR'
        payment.payment_status = 'pending'
        payment.gateway = 'cashfree'
        payment.gateway_response = json.dumps(order_data)
    db.session.commit()

    return redirect(url_for('main.cashfree_checkout_page', payment_id=payment.id))


@main_bp.route('/payment/cashfree/checkout/<int:payment_id>')
def cashfree_checkout_page(payment_id):
    """Render Cashfree Web Checkout SDK interface."""
    payment = db.session.get(Payment, payment_id) or abort(404)
    application = payment.application
    job = application.job
    
    cfg = CashfreeService.get_config()
    is_simulation = 'session_test_' in (payment.cashfree_payment_session_id or '')

    return render_template(
        'pages/payment_cashfree_checkout.html',
        payment=payment,
        app=application,
        job=job,
        cashfree_env=cfg['environment'],
        is_simulation=is_simulation
    )


@main_bp.route('/payment/cashfree/return', methods=['GET', 'POST'])
def cashfree_return():
    """
    Cashfree Return Endpoint.
    Verifies transaction status server-side from Cashfree Sandbox before updating state.
    """
    order_id = (
        request.args.get('order_id') or 
        request.args.get('cf_order_id') or 
        request.args.get('orderId') or 
        request.form.get('order_id') or 
        request.form.get('cf_order_id') or 
        ''
    ).strip()

    if not order_id:
        current_app.logger.warning("Cashfree return received without order_id parameter.")
        flash('Invalid payment return request: missing order ID.', 'danger')
        return redirect(url_for('main.careers'))

    current_app.logger.info(f"Return URL received for Cashfree Order ID: {order_id}")

    payment = Payment.query.filter_by(cashfree_order_id=order_id).first()
    if not payment:
        current_app.logger.warning(f"Payment record not found for Cashfree order ID: {order_id}")
        flash('Payment record not found for this transaction.', 'danger')
        return redirect(url_for('main.careers'))

    application = payment.application

    # Security check: User authorization (Test Case 9)
    # If user is authenticated, ensure they own the application (or are admin)
    if current_user.is_authenticated:
        if application.user_id and application.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
            current_app.logger.warning(f"Unauthorized payment return access attempt: User {current_user.id} tried to access order {order_id} belonging to User {application.user_id}")
            flash('Access denied: You do not have permission to view this transaction.', 'danger')
            return redirect(url_for('main.careers'))
    else:
        if application.user_id:
            return redirect(url_for('auth.login', next=request.full_path))

    # If already verified paid, safely redirect to success (Idempotent)
    if payment.payment_status == 'paid' and application.payment_status == 'paid':
        return redirect(url_for('main.job_apply_success', app_id=application.id))

    cfg = CashfreeService.get_config()
    is_test_env = (cfg['environment'] == 'test' or current_app.config.get('TESTING', False))

    # Allow simulation bypass ONLY during isolated automated unit test execution
    sim_status = request.args.get('sim_status')
    if sim_status and is_test_env:
        if sim_status == 'SUCCESS':
            is_paid = True
            p_status = 'SUCCESS'
            pay_details = {'cf_payment_id': f"cf_sim_{order_id}", 'simulated': True}
            err = None
        else:
            is_paid = False
            p_status = 'FAILED'
            pay_details = {'cf_payment_id': None, 'simulated': True}
            err = "Simulated payment failure."
    else:
        # Perform Server-Side Verification via Official Cashfree Sandbox API
        is_paid, p_status, pay_details, err = CashfreeService.verify_order_payment(order_id, expected_amount=payment.amount)

    if is_paid and p_status == 'SUCCESS':
        payment.payment_status = 'paid'
        if pay_details and isinstance(pay_details, dict):
            payment.cf_payment_id = pay_details.get('cf_payment_id') or str(pay_details.get('payment_id', ''))
            payment.gateway_response = json.dumps(pay_details)
        
        application.payment_status = 'paid'
        application.application_status = 'APPLIED'
        application.status = 'APPLIED'
        if not application.application_code:
            application.application_code = f"AM-APP-{application.id:06d}"
        if payment.base_amount:
            application.base_amount = payment.base_amount
            application.gst_rate = payment.gst_rate
            application.gst_amount = payment.gst_amount
            application.application_fee = int(payment.base_amount)
        elif payment.amount:
            application.application_fee = int(payment.amount)
        db.session.commit()

        # Automatically record income in Money Management
        try:
            from services.money_service import record_cashfree_income
            record_cashfree_income(application, payment, pay_details, env=cfg['environment'])
        except Exception as e:
            current_app.logger.warning(f"Failed to record money transaction for Cashfree order {order_id}: {e}")

        # Send application success email notification
        try:
            from services.email_service import send_application_successful_email
            send_application_successful_email(application)
        except Exception as e:
            current_app.logger.warning(f"Failed to send confirmation email for application {application.id}: {e}")

        current_app.logger.info(f"Application finalization completed: {application.id} ({application.application_code}) for Cashfree order {order_id}")
        flash("Payment verified successfully! Your application has been submitted.", "success")
        return redirect(url_for('main.job_apply_success', app_id=application.id))
    
    elif p_status in ['PENDING', 'USER_DROPPED']:
        payment.payment_status = 'pending'
        application.payment_status = 'pending'
        db.session.commit()
        return render_template('pages/payment_pending.html', payment=payment, app=application, job=application.job)
    
    else:
        payment.payment_status = 'failed'
        application.payment_status = 'failed'
        db.session.commit()
        return render_template('pages/payment_failed.html', payment=payment, app=application, job=application.job, error_msg=err)


@main_bp.route('/payment/cashfree/webhook', methods=['POST'])
def cashfree_webhook():
    """
    Idempotent Cashfree Webhook Handler.
    Verifies Cashfree HMAC-SHA256 signature and updates payment status.
    """
    signature = request.headers.get('x-webhook-signature', '')
    timestamp = request.headers.get('x-webhook-timestamp', '')
    raw_body = request.get_data()

    cfg = CashfreeService.get_config()
    is_test_env = (cfg['environment'] == 'test' or current_app.config.get('TESTING', False))

    # Verify signature
    is_valid = CashfreeService.verify_webhook_signature(signature, timestamp, raw_body)
    if not is_valid and not is_test_env:
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400

    try:
        data = request.get_json(force=True, silent=True) or {}
        order_info = data.get('data', {}).get('order', {})
        payment_info = data.get('data', {}).get('payment', {})

        order_id = order_info.get('order_id') or data.get('order_id')
        if not order_id:
            return jsonify({'status': 'ignored', 'message': 'No order_id in payload'}), 200

        payment = Payment.query.filter_by(cashfree_order_id=order_id).first()
        if not payment:
            return jsonify({'status': 'ignored', 'message': 'Payment record not found'}), 200

        application = payment.application
        payment_status = (payment_info.get('payment_status') or order_info.get('order_status') or '').upper()

        # Idempotent check
        if payment.payment_status == 'paid':
            # Ensure financial transaction exists even if webhook fires after return url
            try:
                from services.money_service import record_cashfree_income
                record_cashfree_income(application, payment, payment_info, env=cfg['environment'])
            except Exception:
                pass
            return jsonify({'status': 'already_processed', 'message': 'Already processed'}), 200

        if payment_status in ['SUCCESS', 'PAID']:
            # Validate paid amount against expected order amount
            paid_amount_raw = payment_info.get('payment_amount') or order_info.get('order_amount')
            if paid_amount_raw is not None and payment.amount:
                try:
                    paid_amount = float(paid_amount_raw)
                    if abs(paid_amount - float(payment.amount)) > 0.05:
                        current_app.logger.warning(f"Webhook payment amount mismatch for order {order_id}: expected {payment.amount}, received {paid_amount}")
                        return jsonify({'status': 'amount_mismatch', 'message': 'Payment amount mismatch'}), 400
                except Exception:
                    pass

            payment.payment_status = 'paid'
            payment.cf_payment_id = payment_info.get('cf_payment_id') or str(payment_info.get('payment_id', ''))
            payment.gateway_response = json.dumps(data)
            
            application.payment_status = 'paid'
            application.application_status = 'APPLIED'
            application.status = 'APPLIED'
            if not application.application_code:
                application.application_code = f"AM-APP-{application.id:06d}"
            if payment.base_amount:
                application.base_amount = payment.base_amount
                application.gst_rate = payment.gst_rate
                application.gst_amount = payment.gst_amount
                application.application_fee = int(payment.base_amount)
            elif payment.amount:
                application.application_fee = int(payment.amount)
            db.session.commit()

            # Automatically record income in Money Management
            try:
                from services.money_service import record_cashfree_income
                record_cashfree_income(application, payment, payment_info, env=cfg['environment'])
            except Exception as e:
                current_app.logger.warning(f"Failed to record money transaction for webhook order {order_id}: {e}")

            # Send application success email notification
            try:
                from services.email_service import send_application_successful_email
                send_application_successful_email(application)
            except Exception as e:
                current_app.logger.warning(f"Failed to send confirmation email for webhook application {application.id}: {e}")

            current_app.logger.info(f"Application finalized via Webhook: {application.id} ({application.application_code}) for Cashfree order {order_id}")

        elif payment_status in ['FAILED', 'CANCELLED', 'USER_DROPPED']:
            payment.payment_status = 'failed'
            application.payment_status = 'failed'
            db.session.commit()

        return jsonify({'status': 'success'}), 200

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500



@main_bp.route('/careers/apply/retry-payment/<int:app_id>')
def retry_payment(app_id):
    """Allow candidate to retry payment for an existing unpaid application."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    if application.payment_status == 'paid':
        return redirect(url_for('main.job_apply_success', app_id=application.id))
    return redirect(url_for('main.job_apply_review', app_id=application.id))


@main_bp.route('/payment/failed/<int:payment_id>')
def payment_failed_page(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    return render_template(
        'pages/payment_failed.html',
        payment=payment,
        app=payment.application,
        job=payment.application.job,
        error_msg="Your payment was not completed or was cancelled."
    )


@main_bp.route('/payment/pending/<int:payment_id>')
def payment_pending_page(payment_id):
    payment = db.session.get(Payment, payment_id) or abort(404)
    return render_template(
        'pages/payment_pending.html',
        payment=payment,
        app=payment.application,
        job=payment.application.job
    )


@main_bp.route('/careers/apply/success/<int:app_id>')
def job_apply_success(app_id):
    if not current_user.is_authenticated:
        return redirect(url_for('auth.login', next=request.path))

    application = db.session.get(JobApplication, app_id) or abort(404)
    if application.user_id and application.user_id != current_user.id and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    return render_template('pages/job_apply_success.html', app=application, job=application.job)


@main_bp.route('/profile', methods=['GET', 'POST'])
@main_bp.route('/my-profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Display and manage user profile (Name, Email, Phone Number, Applied Positions)."""
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        if name:
            current_user.name = name
        current_user.phone = phone if phone else None
        db.session.commit()
        flash('Profile details updated successfully.', 'success')
        return redirect(url_for('main.profile'))

    user_applications = JobApplication.query.filter(
        (JobApplication.user_id == current_user.id) |
        ((JobApplication.user_id.is_(None)) & (JobApplication.email == current_user.email.lower()))
    ).order_by(JobApplication.created_at.desc()).all()

    # Ensure all matching prior applications are linked to this user_id
    needs_commit = False
    for app in user_applications:
        if app.user_id is None:
            app.user_id = current_user.id
            needs_commit = True
    if needs_commit:
        db.session.commit()

    return render_template(
        'pages/profile.html',
        applications=user_applications,
        apps_count=len(user_applications)
    )


@main_bp.route('/my-applications')
@login_required
def my_applications():
    """Display all submitted and in-progress applications for the authenticated candidate."""
    user_applications = JobApplication.query.filter(
        (JobApplication.user_id == current_user.id) |
        ((JobApplication.user_id.is_(None)) & (JobApplication.email == current_user.email.lower()))
    ).order_by(JobApplication.created_at.desc()).all()

    # Auto-link user_id if any older matching applications existed
    needs_commit = False
    for app in user_applications:
        if app.user_id is None:
            app.user_id = current_user.id
            needs_commit = True
    if needs_commit:
        db.session.commit()

    return render_template('pages/my_applications.html', applications=user_applications)


@main_bp.route('/my-applications/<int:app_id>')
@login_required
def my_application_detail(app_id):
    """View detailed candidate application status, submission dossier, and documents."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    
    # Strictly enforce candidate authorization
    if application.user_id != current_user.id and application.email.lower() != current_user.email.lower() and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    return render_template('pages/my_application_detail.html', app=application, job=application.job)


@main_bp.route('/my-applications/<int:app_id>/document/<string:doc_type>')
@login_required
def my_application_document(app_id, doc_type):
    """Securely serve candidate's own uploaded documents."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    
    # Strictly enforce document ownership
    if application.user_id != current_user.id and application.email.lower() != current_user.email.lower() and getattr(current_user, 'role', '') != 'admin':
        abort(404)

    if doc_type == 'resume':
        folder = current_app.config.get('UPLOAD_FOLDER_RESUMES', os.path.join(current_app.root_path, 'uploads', 'resumes'))
        filename = application.resume_filename
    elif doc_type == 'aadhaar':
        folder = current_app.config.get('UPLOAD_FOLDER_DOCUMENTS', os.path.join(current_app.root_path, 'uploads', 'documents'))
        filename = application.aadhaar_filename
    elif doc_type == 'pan':
        folder = current_app.config.get('UPLOAD_FOLDER_DOCUMENTS', os.path.join(current_app.root_path, 'uploads', 'documents'))
        filename = application.pan_filename
    elif doc_type == 'college_id':
        folder = current_app.config.get('UPLOAD_FOLDER_DOCUMENTS', os.path.join(current_app.root_path, 'uploads', 'documents'))
        filename = application.college_id_filename
    else:
        abort(404)

    if not filename:
        flash(f"No {doc_type} document found for this application.", 'warning')
        return redirect(url_for('main.my_application_detail', app_id=application.id))

    safe_filename = os.path.basename(filename)
    return send_from_directory(folder, safe_filename)


@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()
        phone = (data.get('phone') or '').strip()
        subject = (data.get('subject') or '').strip()
        message = (data.get('message') or '').strip()

        errors = {}
        if not name:
            errors['name'] = 'Name is required'

        if not email:
            errors['email'] = 'Email is required'
        elif not EMAIL_REGEX.match(email):
            errors['email'] = 'Enter a valid email address'

        if not subject:
            errors['subject'] = 'Please select a subject'

        if not message:
            errors['message'] = 'Message is required'
        elif len(message) < 20:
            errors['message'] = 'Message must be at least 20 characters'

        if errors:
            if is_json:
                return jsonify({'status': 'error', 'errors': errors}), 400
            for field, err in errors.items():
                flash(err, 'error')
            return render_template(
                'pages/contact.html',
                errors=errors,
                form_data={'name': name, 'email': email, 'phone': phone, 'subject': subject, 'message': message},
                subjects=SUBJECT_OPTIONS,
                success=False
            )

        inquiry = ContactInquiry(
            name=name,
            email=email,
            phone=phone if phone else None,
            subject=subject,
            message=message
        )
        db.session.add(inquiry)
        db.session.commit()

        if is_json:
            return jsonify({
                'status': 'success',
                'message': 'Message sent! Thank you for reaching out. Our team will review your message and reply within 24 hours.'
            })

        return render_template('pages/contact.html', success=True, subjects=SUBJECT_OPTIONS, errors={})

    return render_template('pages/contact.html', subjects=SUBJECT_OPTIONS, errors={}, success=False)


@main_bp.route('/privacy')
@main_bp.route('/privacy-policy')
def privacy():
    return render_template('pages/privacy.html')


@main_bp.route('/terms')
@main_bp.route('/terms-and-conditions')
def terms():
    return render_template('pages/terms.html')


@main_bp.route('/refund-policy')
@main_bp.route('/cancellation-refund')
@main_bp.route('/refunds')
def refund_policy():
    return render_template('pages/refund_policy.html')

