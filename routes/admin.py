import os
import re
import uuid
import time
import docx
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    abort, current_app, send_from_directory, jsonify, session
)
from flask_login import current_user
from werkzeug.utils import secure_filename
from models import (
    db, JobPosting, JobApplication, Payment, User, Employee,
    DocumentTemplate, EmailTemplate, EmployeeDocument, MoneyTransaction
)

from services.offer_letter_service import (
    generate_offer_letter_docx, send_offer_letter_email,
    OfferLetterTemplateNotFoundError, OfferLetterTemplateFileMissingError,
    get_active_offer_letter_template, determine_job_category,
    OFFER_LETTER_CATEGORIES, ensure_default_templates_initialized
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in with an administrator account to access this area.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        if getattr(current_user, 'role', '') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('', strict_slashes=False)
@admin_bp.route('/', strict_slashes=False)
@admin_bp.route('/dashboard', strict_slashes=False)
@admin_required
def dashboard():
    total_jobs = JobPosting.query.count()
    active_jobs = JobPosting.query.filter_by(is_active=True).count()
    total_applications = JobApplication.query.count()
    paid_applications = JobApplication.query.filter(JobApplication.payment_status.in_(['paid', 'PAID', 'exempt'])).count()
    new_applications = JobApplication.query.filter(
        JobApplication.status.in_(['New', 'APPLIED', 'applied'])
    ).count()
    total_employees = Employee.query.count()

    recent_jobs = JobPosting.query.order_by(JobPosting.created_at.desc()).limit(5).all()
    recent_applications = JobApplication.query.order_by(JobApplication.created_at.desc()).limit(8).all()

    return render_template(
        'admin/dashboard.html',
        total_jobs=total_jobs,
        active_jobs=active_jobs,
        total_applications=total_applications,
        new_applications=new_applications,
        paid_applications=paid_applications,
        total_employees=total_employees,
        recent_jobs=recent_jobs,
        recent_applications=recent_applications
    )


@admin_bp.route('/jobs')
@admin_required
def jobs():
    status_filter = request.args.get('status', 'all').lower()
    dept_filter = request.args.get('dept', '').strip()
    search_query = request.args.get('q', '').strip()

    query = JobPosting.query

    if status_filter == 'active':
        query = query.filter_by(is_active=True)
    elif status_filter == 'inactive':
        query = query.filter_by(is_active=False)

    if dept_filter:
        query = query.filter(JobPosting.department.ilike(f'%{dept_filter}%'))

    if search_query:
        query = query.filter(
            (JobPosting.title.ilike(f'%{search_query}%')) |
            (JobPosting.location.ilike(f'%{search_query}%')) |
            (JobPosting.skills.ilike(f'%{search_query}%'))
        )

    all_jobs = query.order_by(JobPosting.created_at.desc()).all()
    total_unfiltered_jobs = JobPosting.query.count()
    departments = db.session.query(JobPosting.department).distinct().all()
    departments = [d[0] for d in departments if d[0]]

    return render_template(
        'admin/jobs.html',
        jobs=all_jobs,
        total_unfiltered_jobs=total_unfiltered_jobs,
        status_filter=status_filter,
        dept_filter=dept_filter,
        search_query=search_query,
        departments=departments
    )


@admin_bp.route('/jobs/delete-all', methods=['POST'])
@admin_required
def delete_all_jobs():
    confirmation = (request.form.get('confirmation') or '').strip()
    if confirmation != 'DELETE':
        flash('Deletion cancelled. You must type DELETE to confirm.', 'danger')
        return redirect(url_for('admin.jobs'))

    total_jobs = JobPosting.query.count()
    if total_jobs == 0:
        flash('There are no job postings to delete.', 'info')
        return redirect(url_for('admin.jobs'))

    try:
        Payment.query.delete()
        JobApplication.query.delete()
        JobPosting.query.delete()
        db.session.commit()
        flash('All job postings have been deleted successfully.', 'success')
    except Exception:
        db.session.rollback()
        flash('Unable to delete job postings. No changes were made.', 'danger')

    return redirect(url_for('admin.jobs'))


@admin_bp.route('/jobs/create', methods=['GET', 'POST'])
@admin_required
def create_job():
    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        department = (request.form.get('department') or '').strip()
        location = (request.form.get('location') or '').strip()
        employment_type = (request.form.get('employment_type') or 'Full-time').strip()
        duration = (request.form.get('duration') or '').strip() or None
        short_description = (request.form.get('short_description') or '').strip()
        description = (request.form.get('description') or '').strip()
        requirements = (request.form.get('requirements') or '').strip()
        qualifications = (request.form.get('qualifications') or '').strip()
        experience = (request.form.get('experience') or '').strip()
        responsibilities = (request.form.get('responsibilities') or '').strip()
        skills = (request.form.get('skills') or '').strip()
        salary = (request.form.get('salary') or '').strip()
        application_deadline = (request.form.get('application_deadline') or '').strip()
        is_active = True if request.form.get('is_active') in ['true', '1', 'on'] else False

        errors = []
        if not title:
            errors.append('Job title is required.')
        if not department:
            errors.append('Department is required.')
        if not location:
            errors.append('Location is required.')
        if not short_description:
            errors.append('Short description is required.')
        if not description:
            errors.append('Full job description is required.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('admin/create_job.html', form_data=request.form)

        # Auto-generate unique Job Code JB#### with concurrency retry or use manual if provided
        from sqlalchemy.exc import IntegrityError
        import re

        manual_code = (request.form.get('job_code') or request.form.get('job_id') or '').strip().upper()
        if manual_code:
            if not re.match(r'^JB\d{4}$', manual_code):
                flash('Job Code must follow the format JB#### (e.g. JB1001, JB1234).', 'danger')
                return render_template('admin/create_job.html', form_data=request.form)
            existing = JobPosting.query.filter((JobPosting.job_code == manual_code) | (JobPosting.job_id == manual_code)).first()
            if existing:
                flash(f'Job Code {manual_code} is already in use by "{existing.title}".', 'danger')
                return render_template('admin/create_job.html', form_data=request.form)

        saved = False
        final_job_code = None
        for attempt in range(5):
            final_job_code = manual_code if manual_code else JobPosting.generate_unique_job_code()
            job = JobPosting(
                job_id=final_job_code,
                job_code=final_job_code,
                title=title,
                department=department,
                location=location,
                employment_type=employment_type,
                duration=duration,
                short_description=short_description,
                description=description,
                requirements=requirements,
                qualifications=qualifications,
                experience=experience,
                responsibilities=responsibilities,
                skills=skills,
                salary=salary,
                application_deadline=application_deadline,
                is_active=is_active
            )
            try:
                db.session.add(job)
                db.session.commit()
                saved = True
                break
            except IntegrityError:
                db.session.rollback()
                if manual_code:
                    flash(f'Job Code {manual_code} already exists in the database.', 'danger')
                    return render_template('admin/create_job.html', form_data=request.form)
                if attempt == 4:
                    flash('Could not generate a unique Job Code due to concurrency conflict. Please try again.', 'danger')
                    return render_template('admin/create_job.html', form_data=request.form)

        flash(f"Job posting '{job.title}' ({final_job_code}) created successfully.", 'success')
        return redirect(url_for('admin.jobs'))

    return render_template('admin/create_job.html', form_data={})


@admin_bp.route('/jobs/edit/<int:job_id>', methods=['GET', 'POST'])
@admin_required
def edit_job(job_id):
    job = db.session.get(JobPosting, job_id) or abort(404)

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()
        department = (request.form.get('department') or '').strip()
        location = (request.form.get('location') or '').strip()
        employment_type = (request.form.get('employment_type') or 'Full-time').strip()
        duration = (request.form.get('duration') or '').strip() or None
        short_description = (request.form.get('short_description') or '').strip()
        description = (request.form.get('description') or '').strip()
        requirements = (request.form.get('requirements') or '').strip()
        qualifications = (request.form.get('qualifications') or '').strip()
        experience = (request.form.get('experience') or '').strip()
        responsibilities = (request.form.get('responsibilities') or '').strip()
        skills = (request.form.get('skills') or '').strip()
        salary = (request.form.get('salary') or '').strip()
        application_deadline = (request.form.get('application_deadline') or '').strip()
        is_active = True if request.form.get('is_active') in ['true', '1', 'on'] else False

        errors = []
        if not title:
            errors.append('Job title is required.')
        if not department:
            errors.append('Department is required.')
        if not location:
            errors.append('Location is required.')
        if not short_description:
            errors.append('Short description is required.')
        if not description:
            errors.append('Full job description is required.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('admin/edit_job.html', job=job)

        job_code_val = (request.form.get('job_code') or request.form.get('job_id') or '').strip().upper()
        if not job.job_code and not job.job_id:
            generated = JobPosting.generate_unique_job_code()
            job.job_code = generated
            job.job_id = generated
        elif job_code_val and job_code_val != (job.job_code or job.job_id or '').upper():
            import re
            if re.match(r'^JB\d{4}$', job_code_val):
                conflict = JobPosting.query.filter(
                    ((JobPosting.job_code == job_code_val) | (JobPosting.job_id == job_code_val)),
                    JobPosting.id != job.id
                ).first()
                if not conflict:
                    job.job_code = job_code_val
                    job.job_id = job_code_val
        elif not job.job_code and job.job_id:
            job.job_code = job.job_id

        job.title = title
        job.department = department
        job.location = location
        job.employment_type = employment_type
        job.duration = duration
        job.short_description = short_description
        job.description = description
        job.requirements = requirements
        job.qualifications = qualifications
        job.experience = experience
        job.responsibilities = responsibilities
        job.skills = skills
        job.salary = salary
        job.application_deadline = application_deadline
        job.is_active = is_active

        # Mark as Updated state handling
        mark_updated = True if request.form.get('is_updated') in ['true', '1', 'on'] else False
        if mark_updated:
            now = datetime.now(timezone.utc)
            cr = job.created_at
            if cr and cr.tzinfo is None:
                cr = cr.replace(tzinfo=timezone.utc)
            if cr and (now - cr).total_seconds() < 60:
                job.updated_at = job.created_at + timedelta(minutes=5)
            else:
                job.updated_at = now
        else:
            job.updated_at = job.created_at

        db.session.commit()
        flash(f"Job posting '{job.title}' updated successfully.", 'success')
        return redirect(url_for('admin.jobs'))

    return render_template('admin/edit_job.html', job=job)


@admin_bp.route('/jobs/toggle/<int:job_id>', methods=['POST'])
@admin_required
def toggle_job(job_id):
    job = db.session.get(JobPosting, job_id) or abort(404)
    job.is_active = not job.is_active
    db.session.commit()
    status_str = 'Active' if job.is_active else 'Inactive'
    flash(f"Job '{job.title}' is now {status_str}.", 'success')
    return redirect(request.referrer or url_for('admin.jobs'))


@admin_bp.route('/jobs/toggle-updated/<int:job_id>', methods=['POST'])
@admin_required
def toggle_job_updated(job_id):
    job = db.session.get(JobPosting, job_id) or abort(404)
    if job.is_updated:
        job.updated_at = job.created_at
        status_str = 'unmarked as Updated'
    else:
        now = datetime.now(timezone.utc)
        cr = job.created_at
        if cr and cr.tzinfo is None:
            cr = cr.replace(tzinfo=timezone.utc)
        if cr and (now - cr).total_seconds() < 60:
            job.updated_at = job.created_at + timedelta(minutes=5)
        else:
            job.updated_at = now
        status_str = 'marked as Updated'
    db.session.commit()
    flash(f"Job '{job.title}' {status_str}.", 'success')
    return redirect(request.referrer or url_for('admin.jobs'))


@admin_bp.route('/jobs/delete/<int:job_id>', methods=['POST'])
@admin_required
def delete_job(job_id):
    job = db.session.get(JobPosting, job_id) or abort(404)
    title = job.title
    db.session.delete(job)
    db.session.commit()
    flash(f"Job posting '{title}' and its applications have been safely removed.", 'info')
    return redirect(url_for('admin.jobs'))


@admin_bp.route('/applications/clear-all', methods=['POST'])
@admin_bp.route('/applications/delete-all', methods=['POST'])
@admin_required
def clear_all_applications():
    """
    Clear all candidate applications and related uploaded documents upon typing DELETE.
    Strictly preserves job postings, employees, templates, money transactions, and email logs.
    """
    confirmation = (request.form.get('confirmation') or '').strip()
    if confirmation != 'DELETE':
        flash('Deletion cancelled. You must type DELETE to confirm.', 'danger')
        return redirect(url_for('admin.applications'))

    total_apps = JobApplication.query.count()
    if total_apps == 0:
        flash('There are no candidate applications to delete.', 'info')
        return redirect(url_for('admin.applications'))

    try:
        # 1. Clean up candidate uploaded documents from disk
        apps = JobApplication.query.all()
        for app in apps:
            for path_attr in ['resume_path', 'aadhaar_path', 'pan_path', 'college_id_path']:
                fpath = getattr(app, path_attr, None)
                if fpath and os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass

        # 2. Preserve Employee, MoneyTransaction, and EmployeeDocument records
        Employee.query.filter(Employee.application_id.isnot(None)).update({'application_id': None})
        MoneyTransaction.query.filter(MoneyTransaction.application_id.isnot(None)).update({'application_id': None})
        EmployeeDocument.query.filter(EmployeeDocument.employee_id.isnot(None)).update({'application_id': None})

        # 3. Delete Payment and JobApplication records
        Payment.query.delete()
        JobApplication.query.delete()
        db.session.commit()
        flash('All candidate applications and associated files have been cleared successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error clearing candidate applications: {e}")
        flash('Unable to clear candidate applications. No changes were made.', 'danger')

    return redirect(url_for('admin.applications'))


@admin_bp.route('/applications')
@admin_required
def applications():
    job_id_filter = request.args.get('job_id', type=int)
    duration_filter = request.args.get('duration', '').strip()
    status_filter = request.args.get('status', 'all').strip()
    payment_filter = request.args.get('payment_status', 'all').strip()
    search_query = request.args.get('q', '').strip()

    # Query all applications (including new manual applications with pending payment)
    query = JobApplication.query.join(JobPosting)

    if job_id_filter:
        query = query.filter(JobApplication.job_id == job_id_filter)

    if duration_filter and duration_filter.lower() != 'all':
        query = query.filter(JobApplication.duration == duration_filter)

    if status_filter and status_filter.lower() != 'all':
        query = query.filter(JobApplication.status.ilike(status_filter))

    if payment_filter and payment_filter.lower() != 'all':
        if payment_filter.lower() == 'paid':
            query = query.filter(JobApplication.payment_status.in_(['paid', 'PAID', 'exempt']))
        elif payment_filter.lower() == 'pending':
            query = query.filter(JobApplication.payment_status.in_(['pending', 'PENDING']))
        elif payment_filter.lower() == 'failed':
            query = query.filter(JobApplication.payment_status.in_(['failed', 'FAILED']))
        else:
            query = query.filter(JobApplication.payment_status.ilike(payment_filter))

    if search_query:
        query = query.filter(
            (JobApplication.full_name.ilike(f'%{search_query}%')) |
            (JobApplication.email.ilike(f'%{search_query}%')) |
            (JobApplication.phone.ilike(f'%{search_query}%')) |
            (JobApplication.college.ilike(f'%{search_query}%')) |
            (JobApplication.skills.ilike(f'%{search_query}%')) |
            (JobApplication.application_code.ilike(f'%{search_query}%')) |
            (JobPosting.title.ilike(f'%{search_query}%')) |
            (JobPosting.job_code.ilike(f'%{search_query}%')) |
            (JobPosting.job_id.ilike(f'%{search_query}%')) |
            (JobPosting.department.ilike(f'%{search_query}%'))
        )

    all_applications = query.order_by(JobApplication.created_at.desc()).all()
    all_jobs = JobPosting.query.order_by(JobPosting.title.asc()).all()
    total_unfiltered_applications = JobApplication.query.count()

    return render_template(
        'admin/applications.html',
        applications=all_applications,
        all_jobs=all_jobs,
        total_unfiltered_applications=total_unfiltered_applications,
        selected_job_id=job_id_filter,
        selected_duration=duration_filter,
        selected_status=status_filter,
        selected_payment_status=payment_filter,
        search_query=search_query
    )


@admin_bp.route('/applications/<int:app_id>')
@admin_required
def application_detail(app_id):
    application = db.session.get(JobApplication, app_id) or abort(404)
    job = application.job

    # Normalize application stage to one of: 'APPLIED', 'UNDER_REVIEW', 'SHORTLISTED', 'OFFER_COMPLETED', 'HIRED'
    st_raw = (application.status or application.application_status or 'APPLIED').strip().upper()
    if st_raw in ['HIRED']:
        current_stage = 'HIRED'
    elif st_raw in ['OFFER_COMPLETED', 'OFFER_COMPLETE', 'COMPLETED', 'COMPLETE']:
        current_stage = 'OFFER_COMPLETED'
    elif st_raw in ['SHORTLISTED']:
        current_stage = 'SHORTLISTED'
    elif st_raw in ['UNDER_REVIEW', 'REVIEWED']:
        current_stage = 'UNDER_REVIEW'
    else:
        current_stage = 'APPLIED'

    app_email_preview = None
    shortlist_email_preview = None
    joining_email_preview = None
    offer_doc = application.offer_letter_doc
    new_employee_creds = None
    template_missing_error = None

    # Retrieve temporary credentials: check onboarding credential state
    secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
    cred = application.employee.onboarding_credential if application.employee else None
    if cred and cred.status == 'RESET':
        new_employee_creds = None
    elif application.employee and application.employee.is_temporary_password_active:
        decrypted_pwd = application.employee.get_temp_password(secret_key)
        if decrypted_pwd:
            new_employee_creds = {
                'app_id': application.id,
                'employee_id': application.employee.employee_id,
                'temp_password': decrypted_pwd
            }
    else:
        session_creds = session.get('new_employee_credentials')
        if session_creds and session_creds.get('app_id') == application.id and (not cred or cred.status == 'ACTIVE'):
            new_employee_creds = session_creds

    # If stage is UNDER_REVIEW: prepare Application Successful email preview with real candidate data
    if current_stage == 'UNDER_REVIEW':
        from services.email_service import render_application_successful_email
        app_email_preview = render_application_successful_email(application)

    # If stage is SHORTLISTED or OFFER_COMPLETED: prepare Offer Letter & Shortlist email preview
    if current_stage in ['SHORTLISTED', 'OFFER_COMPLETED']:
        from services.email_service import render_shortlisted_offer_email
        shortlist_email_preview = render_shortlisted_offer_email(application)

    # If stage is OFFER_COMPLETED or HIRED: prepare Joining & Credentials email preview
    if current_stage in ['OFFER_COMPLETED', 'HIRED']:
        from services.email_service import render_joining_credentials_email
        joining_email_preview = render_joining_credentials_email(application)

    # Auto-generate Offer Letter DOCX if missing or not generated when stage is SHORTLISTED, OFFER_COMPLETED, or HIRED
    if current_stage in ['SHORTLISTED', 'OFFER_COMPLETED', 'HIRED']:
        if not offer_doc or not offer_doc.file_path or not os.path.exists(offer_doc.file_path):
            try:
                offer_doc, _ = generate_offer_letter_docx(application)
            except (OfferLetterTemplateNotFoundError, OfferLetterTemplateFileMissingError) as tmpl_err:
                template_missing_error = str(tmpl_err)
            except Exception as gen_err:
                template_missing_error = f"Error generating Offer Letter: {str(gen_err)}"

    return render_template(
        'admin/application_detail.html',
        app=application,
        job=job,
        current_stage=current_stage,
        app_email_preview=app_email_preview,
        shortlist_email_preview=shortlist_email_preview,
        joining_email_preview=joining_email_preview,
        offer_doc=offer_doc,
        new_employee_creds=new_employee_creds,
        template_missing_error=template_missing_error
    )


@admin_bp.route('/applications/<int:app_id>/mark-under-review', methods=['POST'])
@admin_required
def mark_application_under_review(app_id):
    application = db.session.get(JobApplication, app_id) or abort(404)
    application.status = 'UNDER_REVIEW'
    application.application_status = 'UNDER_REVIEW'
    db.session.commit()
    flash(f"Application for candidate {application.full_name} is now Under Review.", 'success')
    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/send-application-email', methods=['GET', 'POST'])
@admin_required
def send_application_success_email_action(app_id):
    if request.method == 'GET':
        return redirect(url_for('admin.application_detail', app_id=app_id))

    application = db.session.get(JobApplication, app_id)
    if not application:
        flash("Candidate application record not found.", "danger")
        return redirect(url_for('admin.applications'))

    if application.application_success_email_status == 'SENT':
        sent_time = application.application_success_email_sent_at.strftime('%b %d, %Y') if application.application_success_email_sent_at else 'earlier'
        flash(f'Application Successful email has already been sent to this candidate on {sent_time}.', 'warning')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    try:
        from services.email_service import send_application_successful_email
        success, msg = send_application_successful_email(application)
        if success:
            flash(f"Application Successful email sent to {application.email} successfully.", 'success')
        else:
            flash(f"Failed to send email: {msg}", 'danger')
    except Exception as e:
        if current_app:
            current_app.logger.error(f"Error in send_application_success_email_action: {str(e)}", exc_info=True)
        flash(f"Unable to dispatch email: {str(e)}", 'danger')

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/mark-shortlisted', methods=['POST'])
@admin_bp.route('/applications/<int:app_id>/mark-shortlisted-send-offer', methods=['POST'])
@admin_required
def mark_application_shortlisted(app_id):
    """
    Unified Action: 'Mark as Shortlisted & Send Offer Email'.
    Performs the full 13-step workflow:
    1. Verify admin auth
    2. Verify application exists
    3. Verify payment is completed (paid or exempt)
    4. Mark application as SHORTLISTED
    5. Create/reuse Employee record
    6. Generate/reuse candidate Offer Letter DOCX
    7. Convert DOCX to PDF
    8. Load Shortlisted email template (template_type='offer_letter')
    9. Populate candidate variables
    10. Attach candidate Offer Letter PDF (<APPLICATION_ID>_Offer_Letter.pdf)
    11. Send email through Brevo REST API
    12. Update email status / EmailLog on Brevo response
    13. Update UI state
    """
    application = db.session.get(JobApplication, app_id) or abort(404)

    # Step 3: Verify payment is completed
    if application.payment_status not in ['paid', 'exempt']:
        flash(f"Payment is not completed (Current status: {application.payment_status}). Candidate cannot be shortlisted until payment is completed.", 'warning')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Step 4: Mark application as SHORTLISTED
    application.status = 'SHORTLISTED'
    application.application_status = 'SHORTLISTED'

    # Step 5: Create/reuse Employee record
    if not application.employee:
        try:
            emp_id = Employee.generate_unique_employee_id()
            plaintext_password = Employee.generate_secure_password(12)

            employee = Employee(
                employee_id=emp_id,
                application_id=application.id,
                account_status='active'
            )
            employee.set_password(plaintext_password)
            secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
            employee.set_temp_password(plaintext_password, secret_key)
            db.session.add(employee)
            db.session.flush()

            # Store credentials in session for immediate copy/display to admin
            session['new_employee_credentials'] = {
                'app_id': application.id,
                'employee_id': employee.employee_id,
                'temp_password': plaintext_password
            }
        except Exception as e:
            current_app.logger.warning(f"Error creating employee during shortlist: {str(e)}")

    # Step 6: Generate/reuse candidate Offer Letter DOCX
    offer_doc = None
    try:
        offer_doc, _ = generate_offer_letter_docx(application)
        if application.employee and offer_doc:
            offer_doc.employee_id = application.employee.id
        db.session.commit()
    except (OfferLetterTemplateNotFoundError, OfferLetterTemplateFileMissingError) as tmpl_err:
        db.session.commit()
        flash(str(tmpl_err), 'danger')
        return redirect(url_for('admin.application_detail', app_id=application.id))
    except Exception as e:
        db.session.commit()
        flash(f"Candidate marked as Shortlisted, but error generating Offer Letter DOCX: {str(e)}", 'danger')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Steps 7-12: Send Shortlisted & Offer Letter Email with PDF attachment via Brevo
    if offer_doc and offer_doc.email_status == 'sent':
        flash(f"Candidate {application.full_name} is already Shortlisted and the Offer Letter email was already delivered.", 'info')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    from services.email_service import send_offer_letter_shortlisted_email
    email_success, email_msg = send_offer_letter_shortlisted_email(application)

    emp_code = application.employee.employee_id if application.employee else ''
    if email_success:
        flash(
            f"Candidate {application.full_name} successfully marked as Shortlisted! "
            f"Employee ID ({emp_code}) generated and official Offer Letter email with PDF attachment dispatched "
            f"to {application.email} via Brevo.",
            'success'
        )
    else:
        # Candidate remains SHORTLISTED; email delivery failed
        flash(f"Candidate shortlisted, but email delivery failed: {email_msg}", 'danger')

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/mark-complete', methods=['POST'])
@admin_required
def mark_application_offer_complete(app_id):
    """
    Stage 4: Mark as Complete.
    Validates employee and offer letter exist, generates PDF, sends via Brevo,
    and ONLY sets status to OFFER_COMPLETED after successful email delivery.

    IMPORTANT: The status is NOT set to OFFER_COMPLETED if:
    - PDF conversion fails
    - Brevo delivery fails
    This prevents falsely reporting "Offer marked as Complete" when email was not sent.
    """
    application = db.session.get(JobApplication, app_id) or abort(404)

    # Ensure Offer Letter DOCX is generated
    from services.document_preview_service import _resolve_document_file_path
    offer_doc = application.offer_letter_doc
    docx_path = _resolve_document_file_path(offer_doc) if offer_doc else None
    if not offer_doc or not docx_path or not os.path.exists(docx_path):
        try:
            offer_doc, _ = generate_offer_letter_docx(application)
        except Exception as e:
            flash(f"Cannot complete offer: {str(e)}", 'danger')
            return redirect(url_for('admin.application_detail', app_id=application.id))

    # If email was already sent: simply mark as complete and commit
    if offer_doc and offer_doc.email_status == 'sent':
        application.status = 'OFFER_COMPLETED'
        application.application_status = 'OFFER_COMPLETED'
        application.offer_completed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"Application for {application.full_name} is marked as Offer Completed.", 'success')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Attempt to send Offer Letter email with PDF attachment via Brevo
    from services.offer_letter_service import send_offer_letter_email
    success, msg = send_offer_letter_email(application)

    if success:
        # Email sent successfully — NOW mark as OFFER_COMPLETED
        application.status = 'OFFER_COMPLETED'
        application.application_status = 'OFFER_COMPLETED'
        application.offer_completed_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(
            f"Offer marked as Complete! Offer Letter email with PDF attachment sent successfully to {application.email}.",
            'success'
        )
    else:
        # Email failed — do NOT change status to OFFER_COMPLETED
        # Status remains SHORTLISTED; email_status on offer_doc is already set to 'failed'
        # by send_offer_letter_email. Commit that failure status only.
        try:
            db.session.commit()
        except Exception as db_e:
            db.session.rollback()
            current_app.logger.error(f"DB error saving email failure state for app {app_id}: {db_e}")
        flash(
            f"Offer email was NOT sent. {msg} "
            f"The offer stage has not been marked as complete. "
            f"Please use the Retry button after the issue is resolved.",
            'danger'
        )

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/mark-hired', methods=['POST'])
@admin_required
def mark_application_hired(app_id):
    """
    Stage 5: Mark as Hired / Mark as Joining.
    Validates joining_date, updates status to HIRED, and automatically dispatches
    the Joining & Employee Credentials Email via Brevo REST API.
    """
    application = db.session.get(JobApplication, app_id) or abort(404)

    joining_date = (request.form.get('joining_date') or '').strip()
    if joining_date:
        application.joining_date = joining_date
    elif not application.joining_date:
        application.joining_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    application.status = 'HIRED'
    application.application_status = 'HIRED'
    application.hired_at = datetime.now(timezone.utc)

    # Automatically dispatch Joining & Employee Credentials Email if not already sent
    if application.joining_email_status != 'SENT':
        from services.email_service import send_joining_credentials_email
        success, msg = send_joining_credentials_email(application, joining_date=application.joining_date)
        if success:
            db.session.commit()
            flash(f"Candidate {application.full_name} marked as HIRED! Joining details and employee credentials email sent successfully to {application.email}.", 'success')
        else:
            db.session.commit()
            flash(f"Candidate {application.full_name} marked as HIRED. Notice on joining email: {msg}", 'warning')
    else:
        db.session.commit()
        flash(f"Candidate {application.full_name} is marked as HIRED.", 'success')

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/send-joining-email', methods=['POST'])
@admin_required
def send_joining_email_action(app_id):
    """Explicit action to send/resend Joining & Employee Credentials email via Brevo."""
    application = db.session.get(JobApplication, app_id) or abort(404)

    joining_date = (request.form.get('joining_date') or '').strip() or application.joining_date
    if not joining_date:
        joining_date = datetime.now(timezone.utc).strftime("%d/%m/%Y")
        application.joining_date = joining_date

    # Allow resending
    from services.email_service import send_joining_credentials_email
    application.joining_email_status = 'PENDING'
    success, msg = send_joining_credentials_email(application, joining_date=joining_date)
    if success:
        db.session.commit()
        flash(f"Joining & Employee Credentials email sent successfully to {application.email}.", 'success')
    else:
        db.session.commit()
        flash(f"Failed to send Joining email: {msg}", 'danger')

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/retry-shortlist-offer', methods=['POST'])
@admin_bp.route('/applications/<int:app_id>/send-shortlist-offer', methods=['POST'])
@admin_required
def retry_shortlist_offer_email(app_id):
    """
    Admin Retry Action: Resends the Shortlisted & Offer Letter email with PDF attachment via Brevo.
    Reuses existing Employee, Application ID, DOCX, and regenerated PDF.
    """
    from services.document_preview_service import _resolve_document_file_path
    from services.offer_letter_service import send_offer_letter_email
    application = db.session.get(JobApplication, app_id) or abort(404)

    # Ensure status is SHORTLISTED or OFFER_COMPLETED or HIRED
    st = (application.status or application.application_status or '').upper()
    if st not in ['SHORTLISTED', 'OFFER_COMPLETED', 'HIRED']:
        flash('Application must be Shortlisted before sending the Offer Letter.', 'danger')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Ensure Offer Letter is generated
    offer_doc = application.offer_letter_doc
    docx_path = _resolve_document_file_path(offer_doc) if offer_doc else None
    if not offer_doc or not docx_path or not os.path.exists(docx_path):
        try:
            offer_doc, _ = generate_offer_letter_docx(application)
        except Exception as e:
            flash(f"Cannot send Offer Letter: {str(e)}", 'danger')
            return redirect(url_for('admin.application_detail', app_id=application.id))

    # Check duplicate send
    if offer_doc.email_status == 'sent':
        flash('Offer Letter email has already been sent to this candidate.', 'warning')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Send Shortlisted email + Offer Letter attachment via Brevo
    from services.offer_letter_service import send_offer_letter_email
    success, msg = send_offer_letter_email(application)

    if not success:
        if any(phrase in str(msg) for phrase in [
            "PDF could not be generated",
            "PDF conversion failed",
            "LibreOffice is not available",
            "conversion timed out",
            "invalid output"
        ]):
            flash(f"Offer Letter PDF could not be generated. The email was not sent. ({msg})", 'danger')
        else:
            flash(f"Failed to send Offer Letter email: {msg}", 'danger')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    # Auto-generate Employee credentials if not already existing
    if not application.employee:
        try:
            emp_id = Employee.generate_unique_employee_id()
            plaintext_password = Employee.generate_secure_password(12)

            employee = Employee(
                employee_id=emp_id,
                application_id=application.id,
                account_status='active'
            )
            employee.set_password(plaintext_password)
            secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
            employee.set_temp_password(plaintext_password, secret_key)
            db.session.add(employee)
            db.session.flush()

            # Link Offer Letter doc to employee
            if offer_doc:
                offer_doc.employee_id = employee.id

            db.session.commit()

            # Save temporary credentials in session for immediate display to admin
            session['new_employee_credentials'] = {
                'app_id': application.id,
                'employee_id': employee.employee_id,
                'temp_password': plaintext_password
            }
            flash(f"Offer Letter sent successfully! Employee account ({employee.employee_id}) created automatically.", 'success')
        except Exception as e:
            db.session.rollback()
            flash(f"Offer Letter sent, but error creating employee account: {str(e)}", 'warning')
    else:
        flash(f"Offer Letter sent successfully to candidate {application.full_name}.", 'success')

    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/offer-letter/download', methods=['GET'])
@admin_required
def download_application_offer_letter(app_id):
    """Download candidate-specific generated Offer Letter DOCX."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    offer_doc = application.offer_letter_doc

    if not offer_doc:
        flash('Offer Letter has not been generated yet.', 'warning')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    fpath = offer_doc.file_path
    if not fpath or not os.path.exists(fpath):
        basename = os.path.basename(fpath or offer_doc.file_name or '')
        local_path = os.path.join(current_app.root_path, 'uploads', 'generated_documents', basename)
        if os.path.exists(local_path):
            fpath = local_path
        else:
            flash('Offer Letter has not been generated yet.', 'warning')
            return redirect(url_for('admin.application_detail', app_id=application.id))

    return send_from_directory(
        os.path.dirname(fpath),
        os.path.basename(fpath),
        as_attachment=True,
        download_name=offer_doc.file_name
    )


@admin_bp.route('/applications/<int:app_id>/offer-letter/preview/file', methods=['GET'])
@admin_bp.route('/applications/<int:app_id>/offer-letter/preview-file', methods=['GET'])
@admin_required
def preview_application_offer_letter_file(app_id):
    """
    Admin-only endpoint: serves the raw candidate generated Offer Letter DOCX binary.
    Strictly enforces admin authentication and read-only access.
    """
    application = db.session.get(JobApplication, app_id) or abort(404)
    offer_doc = application.offer_letter_doc

    if not offer_doc:
        abort(404)

    fpath = offer_doc.file_path
    if not fpath or not os.path.exists(fpath):
        basename = os.path.basename(fpath or offer_doc.file_name or '')
        local_path = os.path.join(current_app.root_path, 'uploads', 'generated_documents', basename)
        if os.path.exists(local_path):
            fpath = local_path
        else:
            abort(404)

    return send_from_directory(
        os.path.dirname(fpath),
        os.path.basename(fpath),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=False,
        download_name=offer_doc.file_name
    )


@admin_bp.route('/applications/<int:app_id>/offer-letter/preview/pdf', methods=['GET'])
@admin_required
def preview_application_offer_letter_pdf(app_id):
    """
    Admin-only endpoint: converts the candidate's generated Offer Letter DOCX to PDF
    using LibreOffice headless and streams the PDF for inline browser preview.
    """
    from services.document_preview_service import convert_offer_letter_to_pdf

    application = db.session.get(JobApplication, app_id) or abort(404)
    offer_doc = application.offer_letter_doc

    if not offer_doc:
        st = (application.status or application.application_status or '').upper()
        if st in ['SHORTLISTED', 'OFFER_COMPLETED', 'HIRED']:
            try:
                offer_doc, _ = generate_offer_letter_docx(application)
            except Exception as e:
                current_app.logger.error(f"Failed to generate offer doc on preview: {e}")
                abort(404)
        else:
            abort(404)

    success, pdf_path, err_msg = convert_offer_letter_to_pdf(application)
    if not success or not pdf_path or not os.path.exists(pdf_path):
        current_app.logger.warning(
            f"Offer letter PDF conversion unavailable for app {app_id} ({err_msg})."
        )
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'error',
                'error_code': 'CONVERSION_FAILED',
                'message': err_msg or 'Offer letter preview could not be generated right now. Please use Download DOCX.'
            }), 503

        return render_template(
            'admin/preview_error.html',
            app=application,
            download_url=url_for('admin.download_application_offer_letter', app_id=app_id),
            error_message="The Offer Letter preview could not be generated right now. Please use Download DOCX to view the file."
        ), 503

    offer_doc = application.offer_letter_doc
    base_stem = os.path.splitext(offer_doc.file_name)[0] if (offer_doc and offer_doc.file_name) else f"{application.formatted_code}_Offer_Letter"
    pdf_filename = f"{base_stem}.pdf"
    return send_from_directory(
        os.path.dirname(pdf_path),
        os.path.basename(pdf_path),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=pdf_filename
    )


@admin_bp.route('/applications/<int:app_id>/offer-letter/preview', methods=['GET'])
@admin_required
def preview_application_offer_letter(app_id):
    """
    Admin-only endpoint:
    - If format=pdf: redirects/serves the PDF preview.
    - If format=raw/file/docx: serves the raw DOCX binary.
    - If format=json (or AJAX): returns metadata (candidate name, app code, pdf_url, file_url, download_url).
    - If direct browser GET: renders standalone document_preview.html with embedded PDF viewer.
    Does NOT modify the original DOCX or database records.
    """
    from services.document_preview_service import get_application_offer_letter_preview

    application = db.session.get(JobApplication, app_id) or abort(404)
    offer_doc = application.offer_letter_doc

    if not offer_doc or not offer_doc.file_path:
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'error',
                'error_code': 'DOC_NOT_GENERATED',
                'message': 'Offer Letter has not been generated for this application yet.'
            }), 400
        flash('Offer Letter has not been generated for this application yet.', 'warning')
        return redirect(url_for('admin.application_detail', app_id=app_id))

    # Resolve local path if needed
    fpath = offer_doc.file_path
    if not os.path.exists(fpath):
        basename = os.path.basename(fpath or offer_doc.file_name or '')
        local_path = os.path.join(current_app.root_path, 'uploads', 'generated_documents', basename)
        if os.path.exists(local_path):
            fpath = local_path
        else:
            if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'status': 'error',
                    'error_code': 'DOC_NOT_GENERATED',
                    'message': 'Offer Letter file not found on server.'
                }), 400
            flash('Offer Letter file not found on server.', 'warning')
            return redirect(url_for('admin.application_detail', app_id=app_id))

    # Serve PDF if requested
    if request.args.get('format') == 'pdf':
        return redirect(url_for('admin.preview_application_offer_letter_pdf', app_id=app_id))

    # Serve raw binary if requested
    if request.args.get('format') in ['raw', 'file', 'docx', 'binary']:
        return send_from_directory(
            os.path.dirname(fpath),
            os.path.basename(fpath),
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=False,
            download_name=offer_doc.file_name
        )

    pdf_url = url_for('admin.preview_application_offer_letter_pdf', app_id=app_id)
    file_url = url_for('admin.preview_application_offer_letter_file', app_id=app_id)
    download_url = url_for('admin.download_application_offer_letter', app_id=app_id)
    preview_data = get_application_offer_letter_preview(app_id)

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
        request.args.get('format') == 'json' or
        request.accept_mimetypes.best == 'application/json'
    )

    if is_ajax:
        return jsonify(preview_data), 200

    # Standalone full-page preview for direct browser requests
    return render_template(
        'admin/document_preview.html',
        preview=preview_data,
        app=application,
        offer_doc=offer_doc,
        pdf_url=pdf_url,
        file_url=file_url,
        download_url=download_url,
        back_url=url_for('admin.application_detail', app_id=app_id)
    )


@admin_bp.route('/documents/<int:doc_id>/preview/file', methods=['GET'])
@admin_required
def preview_document_file_by_id(doc_id):
    """
    Admin-only endpoint: serves raw EmployeeDocument DOCX binary.
    """
    document = db.session.get(EmployeeDocument, doc_id) or abort(404)
    fpath = document.file_path
    if not fpath or not os.path.exists(fpath):
        abort(404)

    return send_from_directory(
        os.path.dirname(fpath),
        os.path.basename(fpath),
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=False,
        download_name=document.file_name
    )


@admin_bp.route('/documents/<int:doc_id>/preview/pdf', methods=['GET'])
@admin_required
def preview_document_pdf_by_id(doc_id):
    """
    Admin-only endpoint: converts EmployeeDocument DOCX to PDF using LibreOffice headless
    and streams PDF for inline viewing.
    """
    from services.document_preview_service import convert_docx_to_pdf

    document = db.session.get(EmployeeDocument, doc_id) or abort(404)
    fpath = document.file_path
    if not fpath or not os.path.exists(fpath):
        abort(404)

    success, pdf_path, err_msg = convert_docx_to_pdf(fpath)
    if not success or not pdf_path or not os.path.exists(pdf_path):
        if request.args.get('format') == 'json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'status': 'error',
                'error_code': 'CONVERSION_FAILED',
                'message': err_msg or 'Preview is temporarily unavailable. Please download the document to view it.'
            }), 503
        download_url = f"/admin/documents/{doc_id}/download" if hasattr(document, 'id') else "#"
        return render_template(
            'admin/preview_error.html',
            app=document.application if document.application else None,
            download_url=download_url,
            error_message="The document preview could not be generated right now. Please download the document to view it."
        ), 503

    pdf_filename = f"{os.path.splitext(document.file_name)[0]}.pdf"
    return send_from_directory(
        os.path.dirname(pdf_path),
        os.path.basename(pdf_path),
        mimetype='application/pdf',
        as_attachment=False,
        download_name=pdf_filename
    )


@admin_bp.route('/documents/<int:doc_id>/preview', methods=['GET'])
@admin_required
def preview_document_by_id(doc_id):
    """
    Admin-only endpoint: returns preview metadata for any EmployeeDocument by ID.
    """
    from services.document_preview_service import get_document_preview_by_id

    preview_data = get_document_preview_by_id(doc_id)
    if preview_data.get('status') == 'error':
        if preview_data.get('error_code') == 'NOT_FOUND':
            abort(404)
        return jsonify(preview_data), 400

    return jsonify(preview_data), 200


@admin_bp.route('/applications/<int:app_id>/status', methods=['POST'])
@admin_required
def update_application_status(app_id):
    application = db.session.get(JobApplication, app_id) or abort(404)
    new_status = request.form.get('status', '').strip()
    valid_statuses = [
        'New', 'Reviewed', 'Shortlisted', 'Offer Completed', 'Hired', 'Rejected',
        'APPLIED', 'UNDER_REVIEW', 'SHORTLISTED', 'OFFER_COMPLETED', 'HIRED', 'REJECTED'
    ]

    if new_status in valid_statuses:
        status_map = {
            'New': 'APPLIED',
            'APPLIED': 'APPLIED',
            'Reviewed': 'UNDER_REVIEW',
            'UNDER_REVIEW': 'UNDER_REVIEW',
            'Shortlisted': 'SHORTLISTED',
            'SHORTLISTED': 'SHORTLISTED',
            'Offer Completed': 'OFFER_COMPLETED',
            'OFFER_COMPLETED': 'OFFER_COMPLETED',
            'Hired': 'HIRED',
            'HIRED': 'HIRED',
            'Rejected': 'REJECTED',
            'REJECTED': 'REJECTED'
        }
        mapped_status = status_map.get(new_status, new_status.upper())
        application.status = mapped_status
        application.application_status = mapped_status
        db.session.commit()
        flash(f"Status for candidate {application.full_name} updated to '{application.status_display}'.", 'success')
    else:
        flash('Invalid status provided.', 'danger')

    return redirect(request.referrer or url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/applications/<int:app_id>/document/<string:doc_type>')
@admin_required
def download_document(app_id, doc_type):
    """Secure, authenticated document download route protecting sensitive candidate documents."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    as_attachment = request.args.get('download', '0') == '1'

    if doc_type == 'resume':
        folder = current_app.config.get('UPLOAD_FOLDER_RESUMES', current_app.config.get('UPLOAD_FOLDER', os.path.join(current_app.root_path, 'uploads', 'resumes')))
        filename = application.resume_filename
        if application.resume_path and os.path.exists(application.resume_path):
            folder = os.path.dirname(application.resume_path)
            filename = os.path.basename(application.resume_path)
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
        flash(f"No {doc_type} file found for candidate {application.full_name}.", 'warning')
        return redirect(url_for('admin.application_detail', app_id=application.id))

    safe_filename = os.path.basename(filename)
    return send_from_directory(
        folder,
        safe_filename,
        as_attachment=as_attachment
    )


@admin_bp.route('/applications/<int:app_id>/resume')
@admin_required
def download_resume(app_id):
    """Resume download legacy alias."""
    return download_document(app_id, 'resume')


@admin_bp.route('/employees', methods=['GET'])
@admin_required
def employees():
    """List all registered employee accounts with search and filtering."""
    search_query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all').strip()

    query = Employee.query.join(JobApplication).join(JobPosting)

    if status_filter and status_filter.lower() != 'all':
        query = query.filter(Employee.account_status.ilike(status_filter))

    if search_query:
        query = query.filter(
            (Employee.employee_id.ilike(f'%{search_query}%')) |
            (JobApplication.full_name.ilike(f'%{search_query}%')) |
            (JobApplication.email.ilike(f'%{search_query}%')) |
            (JobApplication.application_code.ilike(f'%{search_query}%')) |
            (JobPosting.title.ilike(f'%{search_query}%'))
        )

    all_employees = query.order_by(Employee.created_at.desc()).all()
    return render_template(
        'admin/employees.html',
        employees=all_employees,
        search_query=search_query,
        selected_status=status_filter
    )


@admin_bp.route('/applications/<int:app_id>/update-payment-status', methods=['POST'])
@admin_required
def update_application_payment_status(app_id):
    """Admin action to update payment status for an application (e.g. after manual Google Form / QR verification)."""
    application = db.session.get(JobApplication, app_id) or abort(404)
    new_payment_status = (request.form.get('payment_status') or '').strip().lower()
    valid_statuses = ['pending', 'paid', 'failed']
    if new_payment_status in valid_statuses:
        application.payment_status = new_payment_status
        db.session.commit()
        flash(f"Payment status for candidate {application.full_name} updated to '{new_payment_status.upper()}'.", 'success')
    else:
        flash('Invalid payment status provided.', 'danger')
    return redirect(url_for('admin.application_detail', app_id=application.id))


@admin_bp.route('/employees/create', methods=['GET', 'POST'])
@admin_required
def create_employee():
    """
    Admin Manual Employee Creation Workflow:
    - Select an existing Application ID from the database
    - Displays candidate details (Application ID, Name, Email, Job, Job Code, Department, Duration, College)
    - If employee already exists: shows existing Employee ID and prevents duplicate creation
    - If new: generates unique Employee ID (AM####) and secure temporary password
    - Encrypts and securely stores temporary credentials in EmployeeOnboardingCredential for Internship Portal activation
    - Displays credentials strictly to authorized Admin
    """
    selected_app_id = request.args.get('app_id', type=int)
    
    # Retrieve all applications ordered by newest first
    all_applications = JobApplication.query.order_by(JobApplication.created_at.desc()).all()
    
    selected_app = None
    if selected_app_id:
        selected_app = db.session.get(JobApplication, selected_app_id)
    elif all_applications:
        selected_app = all_applications[0]

    existing_employee = None
    if selected_app and selected_app.employee:
        existing_employee = selected_app.employee

    if request.method == 'POST':
        app_id = request.form.get('application_id', type=int)
        if not app_id:
            flash('Please select an application record.', 'danger')
            return redirect(url_for('admin.create_employee'))

        application = db.session.get(JobApplication, app_id)
        if not application:
            flash('Selected application record not found.', 'danger')
            return redirect(url_for('admin.create_employee'))

        # Idempotency / Duplicate Employee Check
        existing_emp = Employee.query.filter_by(application_id=application.id).first()
        if existing_emp:
            flash(f"Employee Already Exists for this application. Employee ID: {existing_emp.employee_id}.", 'info')
            return redirect(url_for('admin.create_employee', app_id=application.id))

        try:
            # Generate unique Employee ID in format AM####
            emp_id = Employee.generate_unique_employee_id()
            # Generate cryptographically secure temporary password
            temp_password = Employee.generate_secure_password(12)

            employee = Employee(
                employee_id=emp_id,
                application_id=application.id,
                account_status='active'
            )
            employee.set_password(temp_password)
            secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
            employee.set_temp_password(temp_password, secret_key)
            db.session.add(employee)

            # Sync with candidate user account if present
            if application.user_id:
                cand_user = db.session.get(User, application.user_id)
                if cand_user:
                    cand_user.set_password(temp_password)
            elif application.email:
                cand_user = User.query.filter(User.email.ilike(application.email)).first()
                if cand_user:
                    application.user_id = cand_user.id
                    cand_user.set_password(temp_password)

            db.session.commit()

            # Store result in session strictly for authorized Admin one-time view
            session['new_employee_result'] = {
                'application_id': application.id,
                'application_code': application.formatted_code,
                'employee_id': emp_id,
                'temp_password': temp_password,
                'candidate_name': application.full_name,
                'job_title': application.job.title if application.job else '',
                'job_code': application.job_code or ''
            }
            flash(f"Employee {emp_id} created successfully for candidate {application.full_name}!", 'success')
            return redirect(url_for('admin.create_employee', app_id=application.id))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating employee for application {app_id}: {str(e)}", exc_info=True)
            flash(f"Failed to create employee: {str(e)}", 'danger')
            return redirect(url_for('admin.create_employee', app_id=app_id))

    new_cred_result = session.pop('new_employee_result', None)

    return render_template(
        'admin/create_employee.html',
        all_applications=all_applications,
        selected_app=selected_app,
        existing_employee=existing_employee,
        new_cred_result=new_cred_result
    )


@admin_bp.route('/employees/<string:employee_id>', methods=['GET'])
@admin_required
def view_employee(employee_id):
    """View employee details (Application ID, Candidate, Job, Duration, Status, Created Date). Never reveals password_hash."""
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    secret_key = current_app.config.get('SECRET_KEY', 'default-secret-key')
    temp_password = employee.get_temp_password(secret_key) if employee.is_temporary_password_active else ""
    return render_template(
        'admin/employee_detail.html',
        employee=employee,
        app=employee.application,
        job=employee.application.job if employee.application else None,
        temp_password=temp_password,
        onboarding_credential=employee.onboarding_credential
    )


@admin_bp.route('/employees/<string:employee_id>/reset-password', methods=['POST'])
@admin_required
def admin_reset_employee_password(employee_id):
    """
    Admin action to reset an employee's password.
    Securely updates the password hash, permanently purges the temporary password, and marks temporary_password_active = False.
    """
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    new_password = request.form.get('new_password', '').strip()
    if not new_password:
        new_password = Employee.generate_secure_password(12)
    elif len(new_password) < 6:
        flash('New password must be at least 6 characters long.', 'danger')
        return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))

    employee.reset_password(new_password)

    # Sync with linked User account if present
    if employee.candidate_email:
        user = User.query.filter(User.email.ilike(employee.candidate_email)).first()
        if user:
            user.set_password(new_password)
            user.must_change_password = False
            user.password_changed_at = datetime.now(timezone.utc)

    db.session.commit()
    flash(f"Password for employee {employee.employee_id} has been reset successfully. Temporary password is now deactivated.", 'success')
    return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))


# =====================================================================
# =====================================================================
# TEMPLATE MANAGEMENT (EMAIL & DOCUMENT TEMPLATES)
# =====================================================================

@admin_bp.route('/templates', methods=['GET'])
@admin_required
def templates():
    """Template Management Hub for Email and Dynamic Role/Job Based Document Templates."""
    # Ensure standard email templates exist
    app_success_email = EmailTemplate.query.filter_by(template_type='application_successful').first()
    offer_letter_email = EmailTemplate.query.filter_by(template_type='offer_letter').first()
    joining_email = EmailTemplate.query.filter_by(template_type='joining_credentials').first()

    # Active Job Postings for Job Code selection dropdown
    active_jobs = JobPosting.query.filter_by(is_active=True).order_by(JobPosting.job_id.asc(), JobPosting.id.asc()).all()

    # Query all templates (Offer Letter, Email, and master documents)
    all_templates = DocumentTemplate.query.order_by(DocumentTemplate.is_active.desc(), DocumentTemplate.id.desc()).all()
    offer_templates = [t for t in all_templates if t.template_type == 'offer_letter' or t.template_type.startswith('offer_letter_')]

    # Other master templates (Experience Letter, Certificate)
    exp_doc_template = DocumentTemplate.query.filter_by(template_type='experience_letter', is_active=True).order_by(DocumentTemplate.id.desc()).first()
    exp_template_file_exists = bool(exp_doc_template and exp_doc_template.file_path and os.path.exists(exp_doc_template.file_path))

    cert_doc_template = DocumentTemplate.query.filter_by(template_type='certificate', is_active=True).order_by(DocumentTemplate.id.desc()).first()
    cert_template_file_exists = bool(cert_doc_template and cert_doc_template.file_path and os.path.exists(cert_doc_template.file_path))

    # Dynamically compile available Job / Domain options from DB
    domain_set = set()
    for d in ['AI & ML', 'Application Development', 'Data Analytics', 'Full Stack Development']:
        domain_set.add(d)
    for jp in JobPosting.query.all():
        if jp.department and jp.department.strip():
            domain_set.add(jp.department.strip())
    for ot in offer_templates:
        if ot.job_domain and ot.job_domain.strip():
            domain_set.add(ot.job_domain.strip())
    available_domains = sorted(list(domain_set))

    return render_template(
        'admin/templates.html',
        app_success_email=app_success_email,
        offer_letter_email=offer_letter_email,
        joining_email=joining_email,
        active_jobs=active_jobs,
        all_templates=all_templates,
        offer_templates=offer_templates,
        available_domains=available_domains,
        exp_doc_template=exp_doc_template,
        exp_template_file_exists=exp_template_file_exists,
        cert_doc_template=cert_doc_template,
        cert_template_file_exists=cert_template_file_exists,
        categories=OFFER_LETTER_CATEGORIES
    )


@admin_bp.route('/templates/email/<string:template_type>', methods=['POST'])
@admin_required
def update_email_template(template_type):
    """Update subject and body for an Email Template."""
    valid_types = ['application_successful', 'offer_letter', 'joining_credentials']
    if template_type not in valid_types:
        flash('Invalid email template type.', 'danger')
        return redirect(url_for('admin.templates'))

    subject = (request.form.get('subject') or '').strip()
    body = (request.form.get('body') or '').strip()

    if not subject or not body:
        flash('Subject and Body are required for email templates.', 'danger')
        return redirect(url_for('admin.templates'))

    email_tmpl = EmailTemplate.query.filter_by(template_type=template_type).first()
    if not email_tmpl:
        name_map = {
            'application_successful': 'Application Successful Confirmation',
            'offer_letter': 'Offer Letter Delivery',
            'joining_credentials': 'Joining & Employee Credentials'
        }
        email_tmpl = EmailTemplate(
            template_type=template_type,
            name=name_map.get(template_type, template_type.title()),
            subject=subject,
            body=body
        )
        db.session.add(email_tmpl)
    else:
        email_tmpl.subject = subject
        email_tmpl.body = body

    db.session.commit()
    flash(f"Email template '{email_tmpl.name}' updated successfully.", 'success')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/email/<string:template_type>/preview', methods=['GET'])
@admin_required
def preview_email_template(template_type):
    """Preview rendered HTML email with sample preview values."""
    valid_types = ['application_successful', 'offer_letter', 'joining_credentials']
    if template_type not in valid_types:
        return jsonify({'error': 'Invalid template type'}), 400

    from services.email_service import render_sample_email_preview
    preview_data = render_sample_email_preview(template_type)
    return jsonify(preview_data)


@admin_bp.route('/templates/email/<string:template_type>/test', methods=['POST'])
@admin_required
def send_test_email_route(template_type):
    """Send a sample test email to an admin-specified recipient without modifying live records."""
    valid_types = ['application_successful', 'offer_letter', 'joining_credentials']
    if template_type not in valid_types:
        flash('Invalid template type.', 'danger')
        return redirect(url_for('admin.templates'))

    recipient_email = (request.form.get('test_recipient') or '').strip()
    if not recipient_email:
        flash('Please specify a recipient email address for testing.', 'danger')
        return redirect(url_for('admin.templates'))

    from services.email_service import send_test_email
    success, msg = send_test_email(template_type, recipient_email)
    if success:
        flash(f"Test email sent to {recipient_email}: {msg}", 'success')
    else:
        flash(f"Failed to send test email: {msg}", 'danger')

    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/document/offer-letter/upload', methods=['POST'])
@admin_bp.route('/templates/document/<string:template_type>/upload', methods=['POST'])
@admin_required
def upload_document_template(template_type='offer_letter'):
    """
    Upload / replace a master DOCX template.
    For Offer Letters: dynamically maps to Job/Domain and Duration with duplicate protection.
    For other documents (Experience Letter, Certificate): maintains single active master file.
    """
    doc_type = (request.form.get('document_type') or template_type or 'offer_letter').strip()
    
    uploaded_file = request.files.get('template_file')
    if not uploaded_file or not uploaded_file.filename:
        flash('Please select a DOCX template file to upload.', 'danger')
        return redirect(url_for('admin.templates'))

    original_filename = secure_filename(uploaded_file.filename) or uploaded_file.filename
    if not original_filename.lower().endswith('.docx'):
        flash('Only .docx Microsoft Word template files are accepted.', 'danger')
        return redirect(url_for('admin.templates'))

    templates_dir = os.path.join(current_app.root_path, 'uploads', 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    unique_suffix = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"

    if doc_type == 'offer_letter' or doc_type.startswith('offer_letter'):
        job_domain = (request.form.get('job_domain') or '').strip()
        custom_domain = (request.form.get('custom_job_domain') or '').strip()
        if custom_domain and (job_domain == '__custom__' or not job_domain):
            job_domain = custom_domain

        if not job_domain:
            flash('Please select or specify a Job / Domain for the Offer Letter template.', 'danger')
            return redirect(url_for('admin.templates'))

        duration = (request.form.get('duration') or 'Both').strip()
        if duration not in ['Both', '1 Month', '3 Months']:
            duration = 'Both'

        template_name = (request.form.get('template_name') or '').strip()
        if not template_name:
            template_name = f"{job_domain} Offer Letter Template"

        slug = re.sub(r'[^a-zA-Z0-9_]+', '_', job_domain.lower()).strip('_')
        target_filename = f"offer_letter_{slug}_{unique_suffix}.docx"
        target_path = os.path.join(templates_dir, target_filename)

        uploaded_file.save(target_path)

        # DUPLICATE PROTECTION:
        # Deactivate any currently active template with the exact same Job/Domain + Duration
        DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            job_domain=job_domain,
            duration=duration,
            is_active=True
        ).update({'is_active': False})

        # Also deactivate any legacy category active template if matching
        cat_key = determine_job_category(job_domain)
        if cat_key and cat_key in OFFER_LETTER_CATEGORIES:
            legacy_type = OFFER_LETTER_CATEGORIES[cat_key]['type']
            DocumentTemplate.query.filter_by(template_type=legacy_type, is_active=True).update({'is_active': False})

        new_doc_tmpl = DocumentTemplate(
            template_type='offer_letter',
            name=template_name,
            job_domain=job_domain,
            duration=duration,
            filename=uploaded_file.filename,
            file_path=target_path,
            is_active=True,
            created_by=getattr(current_user, 'username', 'Admin') if current_user and current_user.is_authenticated else 'Admin'
        )
        db.session.add(new_doc_tmpl)
        db.session.commit()

        flash(f"Offer Letter template '{template_name}' uploaded successfully and activated for {job_domain} ({duration}).", 'success')
        return redirect(url_for('admin.templates'))

    else:
        # Experience Letter or Certificate
        valid_types = ['experience_letter', 'certificate']
        if doc_type not in valid_types:
            flash('Invalid document template type.', 'danger')
            return redirect(url_for('admin.templates'))

        target_filename = f"{doc_type}_{unique_suffix}.docx"
        target_path = os.path.join(templates_dir, target_filename)
        uploaded_file.save(target_path)

        name_map = {
            'experience_letter': 'Anti-Matrix Master Experience Letter',
            'certificate': 'Anti-Matrix Master Internship Certificate'
        }

        DocumentTemplate.query.filter_by(template_type=doc_type, is_active=True).update({'is_active': False})

        new_doc_tmpl = DocumentTemplate(
            template_type=doc_type,
            name=name_map.get(doc_type, doc_type.replace('_', ' ').title()),
            filename=uploaded_file.filename,
            file_path=target_path,
            is_active=True,
            created_by=getattr(current_user, 'username', 'Admin') if current_user and current_user.is_authenticated else 'Admin'
        )
        db.session.add(new_doc_tmpl)
        db.session.commit()

        flash(f"Template '{uploaded_file.filename}' uploaded and set as ACTIVE for {name_map.get(doc_type, doc_type)}.", 'success')
        return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/create', methods=['POST'])
@admin_required
def create_template():
    """
    Create a new Template assigned directly to a Job Code (JB####).
    Supports:
    - Template Type: 'offer_letter' (DOCX) or 'email' (HTML / Markdown / Text / DOCX)
    - Job Code: Selected from dropdown of active jobs
    - Template Name: descriptive name
    - File upload: validated for extension and size (<= 16MB)
    - Enforces single active template versioning rule per (job_code, template_type)
    """
    template_type = (request.form.get('template_type') or 'offer_letter').strip().lower()
    if template_type not in ['offer_letter', 'email']:
        flash("Invalid template type. Must be 'Offer Letter' or 'Email'.", 'danger')
        return redirect(url_for('admin.templates'))

    job_posting_id = request.form.get('job_posting_id')
    if not job_posting_id:
        flash("Please select a Job Code for the template.", 'danger')
        return redirect(url_for('admin.templates'))

    job = db.session.get(JobPosting, int(job_posting_id))
    if not job:
        flash("Selected Job Posting was not found.", 'danger')
        return redirect(url_for('admin.templates'))

    job_code = (getattr(job, 'job_code', None) or getattr(job, 'job_id', None) or f"JB{job.id}").strip().upper()

    uploaded_file = request.files.get('template_file')
    if not uploaded_file or not uploaded_file.filename:
        flash("Please select a template file to upload.", 'danger')
        return redirect(url_for('admin.templates'))

    original_filename = secure_filename(uploaded_file.filename) or uploaded_file.filename
    ext = os.path.splitext(original_filename)[1].lower()

    if template_type == 'offer_letter':
        if ext != '.docx':
            flash("Offer Letter templates must be Microsoft Word (.docx) files.", 'danger')
            return redirect(url_for('admin.templates'))
    elif template_type == 'email':
        if ext not in ['.html', '.htm', '.md', '.txt', '.docx']:
            flash("Email templates must be .html, .md, .txt, or .docx files.", 'danger')
            return redirect(url_for('admin.templates'))

    template_name = (request.form.get('template_name') or '').strip()
    if not template_name:
        type_label = "Offer Letter" if template_type == 'offer_letter' else "Email"
        template_name = f"{job_code} — {job.title} {type_label} Template"

    duration = (request.form.get('duration') or 'Both').strip()
    if duration not in ['Both', '1 Month', '3 Months']:
        duration = 'Both'

    templates_dir = os.path.join(current_app.root_path, 'uploads', 'templates')
    os.makedirs(templates_dir, exist_ok=True)

    unique_suffix = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    target_filename = f"{template_type}_{job_code.lower()}_{unique_suffix}{ext}"
    target_path = os.path.join(templates_dir, target_filename)

    uploaded_file.save(target_path)

    # Extract subject for email templates if provided or in file
    subject_val = None
    if template_type == 'email':
        subject_val = (request.form.get('subject') or '').strip()
        if not subject_val and ext in ['.html', '.htm', '.md', '.txt']:
            try:
                with open(target_path, 'r', encoding='utf-8', errors='ignore') as f:
                    first_line = f.readline().strip()
                    if first_line.lower().startswith('subject:'):
                        subject_val = first_line.split(':', 1)[1].strip()
            except Exception:
                pass
        if not subject_val:
            subject_val = f"Congratulations! You Have Been Shortlisted — {job.title} | Anti Matrix"

    # VERSIONING RULE: Deactivate any existing active template for this same (job_code, template_type)
    DocumentTemplate.query.filter_by(
        template_type=template_type,
        job_code=job_code,
        is_active=True
    ).update({'is_active': False})

    # Also deactivate if matching by job_posting_id
    DocumentTemplate.query.filter_by(
        template_type=template_type,
        job_posting_id=job.id,
        is_active=True
    ).update({'is_active': False})

    new_tmpl = DocumentTemplate(
        template_type=template_type,
        job_posting_id=job.id,
        job_code=job_code,
        name=template_name,
        filename=uploaded_file.filename,
        file_path=target_path,
        duration=duration,
        job_domain=job.department or job.title,
        subject=subject_val,
        is_active=True,
        created_by=getattr(current_user, 'username', 'Admin') if current_user and current_user.is_authenticated else 'Admin'
    )
    db.session.add(new_tmpl)
    db.session.commit()

    type_name = "Offer Letter" if template_type == 'offer_letter' else "Email"
    flash(f"{type_name} template '{template_name}' successfully created and activated for Job Code {job_code} ({job.title}).", 'success')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/<int:template_id>/assign-job', methods=['POST'])
@admin_required
def assign_job_to_template(template_id):
    """Assign or reassign an existing template to a specific Job Code."""
    tmpl = DocumentTemplate.query.get_or_404(template_id)
    job_posting_id = request.form.get('job_posting_id')
    if not job_posting_id:
        flash("Please select a Job Code to assign.", 'danger')
        return redirect(url_for('admin.templates'))

    job = db.session.get(JobPosting, int(job_posting_id))
    if not job:
        flash("Selected Job Posting was not found.", 'danger')
        return redirect(url_for('admin.templates'))

    job_code = (getattr(job, 'job_code', None) or getattr(job, 'job_id', None) or f"JB{job.id}").strip().upper()
    tmpl.job_posting_id = job.id
    tmpl.job_code = job_code
    tmpl.job_domain = job.department or job.title
    tmpl.updated_at = datetime.now(timezone.utc)

    make_active = request.form.get('make_active') == '1'
    if make_active:
        DocumentTemplate.query.filter_by(
            template_type=tmpl.template_type,
            job_code=job_code,
            is_active=True
        ).update({'is_active': False})
        DocumentTemplate.query.filter_by(
            template_type=tmpl.template_type,
            job_posting_id=job.id,
            is_active=True
        ).update({'is_active': False})
        tmpl.is_active = True

    db.session.commit()

    flash(f"Template '{tmpl.name}' is now assigned to Job Code {job_code} ({job.title}).", 'success')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/document/<int:template_id>/activate', methods=['POST'])
@admin_required
def activate_document_template(template_id):
    """Activates a template, enforcing single active template rule for (job_code, template_type)."""
    tmpl = DocumentTemplate.query.get_or_404(template_id)

    if tmpl.job_code:
        # Deactivate any other active template with the same (job_code, template_type)
        DocumentTemplate.query.filter(
            DocumentTemplate.id != tmpl.id,
            DocumentTemplate.template_type == tmpl.template_type,
            DocumentTemplate.job_code == tmpl.job_code,
            DocumentTemplate.is_active == True
        ).update({'is_active': False})
        if tmpl.job_posting_id:
            DocumentTemplate.query.filter(
                DocumentTemplate.id != tmpl.id,
                DocumentTemplate.template_type == tmpl.template_type,
                DocumentTemplate.job_posting_id == tmpl.job_posting_id,
                DocumentTemplate.is_active == True
            ).update({'is_active': False})
    elif tmpl.template_type == 'offer_letter' and tmpl.job_domain:
        # Deactivate conflicting active template for the same job_domain + duration
        DocumentTemplate.query.filter(
            DocumentTemplate.id != tmpl.id,
            DocumentTemplate.template_type == 'offer_letter',
            DocumentTemplate.job_domain == tmpl.job_domain,
            DocumentTemplate.duration == tmpl.duration,
            DocumentTemplate.is_active == True
        ).update({'is_active': False})
    else:
        # Deactivate other active templates of same template_type
        DocumentTemplate.query.filter(
            DocumentTemplate.id != tmpl.id,
            DocumentTemplate.template_type == tmpl.template_type,
            DocumentTemplate.is_active == True
        ).update({'is_active': False})

    tmpl.is_active = True
    tmpl.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    flash(f"Template '{tmpl.name}' is now ACTIVE.", 'success')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/document/<int:template_id>/deactivate', methods=['POST'])
@admin_required
def deactivate_document_template(template_id):
    """Deactivates an active template."""
    tmpl = DocumentTemplate.query.get_or_404(template_id)
    tmpl.is_active = False
    tmpl.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    flash(f"Template '{tmpl.name}' has been deactivated.", 'info')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/document/<int:template_id>/delete', methods=['POST'])
@admin_required
def delete_document_template(template_id):
    """
    Safely deletes a template record only if not referenced by existing generated documents.
    Protects historical candidate documents.
    """
    tmpl = DocumentTemplate.query.get_or_404(template_id)

    # Check historical reference protection
    ref_count = EmployeeDocument.query.filter_by(template_id=tmpl.id).count()
    if ref_count > 0:
        flash(
            f"Cannot delete template '{tmpl.name}' because {ref_count} previously generated offer letter(s) reference it. "
            "Please deactivate the template instead to preserve historical candidate documents.",
            'danger'
        )
        return redirect(url_for('admin.templates'))

    # If file exists on disk and is not shared, remove safely
    if tmpl.file_path and os.path.exists(tmpl.file_path):
        try:
            # Check if any other template uses the exact same path
            shared = DocumentTemplate.query.filter(DocumentTemplate.id != tmpl.id, DocumentTemplate.file_path == tmpl.file_path).count()
            if shared == 0:
                os.remove(tmpl.file_path)
        except Exception:
            pass

    tmpl_name = tmpl.name
    db.session.delete(tmpl)
    db.session.commit()

    flash(f"Template '{tmpl_name}' deleted successfully.", 'success')
    return redirect(url_for('admin.templates'))


@admin_bp.route('/templates/document/<int:template_id>/download', methods=['GET'])
@admin_required
def download_document_template_by_id(template_id):
    """Download the specific master DOCX template file by ID."""
    tmpl = DocumentTemplate.query.get_or_404(template_id)

    if not tmpl.file_path or not os.path.exists(tmpl.file_path):
        flash('Template file is not available on storage.', 'warning')
        return redirect(url_for('admin.templates'))

    return send_from_directory(
        os.path.dirname(tmpl.file_path),
        os.path.basename(tmpl.file_path),
        as_attachment=True,
        download_name=tmpl.filename or f"{tmpl.name}.docx"
    )


@admin_bp.route('/templates/document/<int:template_id>/preview-info', methods=['GET'])
@admin_required
def preview_document_template_info(template_id):
    """Returns template metadata and detected placeholders as JSON for the admin preview modal."""
    tmpl = DocumentTemplate.query.get_or_404(template_id)

    detected_placeholders = []
    paragraphs_preview = []
    file_exists = bool(tmpl.file_path and os.path.exists(tmpl.file_path))

    if file_exists:
        try:
            doc = docx.Document(tmpl.file_path)
            all_text = " ".join([p.text for p in doc.paragraphs])
            for t in doc.tables:
                for row in t.rows:
                    for cell in row.cells:
                        all_text += " " + cell.text

            # Find placeholders in square brackets or double curly braces
            sq_matches = re.findall(r'\[[A-Za-z0-9_\s/]+\]', all_text)
            curly_matches = re.findall(r'\{\{[A-Za-z0-9_\s/]+\}\}', all_text)
            detected_placeholders = sorted(list(set(sq_matches + curly_matches)))

            for p in doc.paragraphs[:6]:
                if p.text.strip():
                    paragraphs_preview.append(p.text.strip())
        except Exception as e:
            paragraphs_preview.append(f"Could not inspect document text: {str(e)}")

    return jsonify({
        'id': tmpl.id,
        'name': tmpl.name,
        'job_domain': tmpl.job_domain or 'General',
        'duration': tmpl.duration or 'Both',
        'is_active': tmpl.is_active,
        'filename': tmpl.filename,
        'file_exists': file_exists,
        'created_at': tmpl.created_at.strftime('%d %b %Y, %I:%M %p') if tmpl.created_at else None,
        'created_by': tmpl.created_by or 'Admin',
        'detected_placeholders': detected_placeholders,
        'paragraphs_preview': paragraphs_preview
    })


@admin_bp.route('/templates/document/<string:template_type>/download', methods=['GET'])
@admin_required
def download_document_template(template_type):
    """Download / preview the active master DOCX template file by type (backward compatibility)."""
    doc_tmpl = DocumentTemplate.query.filter_by(template_type=template_type, is_active=True).order_by(DocumentTemplate.id.desc()).first()
    if not doc_tmpl and template_type == 'offer_letter_ai_ml':
        doc_tmpl = DocumentTemplate.query.filter_by(template_type='offer_letter', is_active=True).order_by(DocumentTemplate.id.desc()).first()

    if not doc_tmpl or not doc_tmpl.file_path or not os.path.exists(doc_tmpl.file_path):
        flash('Requested master template file is not available on storage. Please upload a template.', 'warning')
        return redirect(url_for('admin.templates'))

    return send_from_directory(
        os.path.dirname(doc_tmpl.file_path),
        os.path.basename(doc_tmpl.file_path),
        as_attachment=True,
        download_name=doc_tmpl.filename
    )


# =====================================================================
# OFFER LETTER GENERATION, PREVIEW, VERIFICATION & SENDING
# =====================================================================

@admin_bp.route('/employees/<string:employee_id>/offer-letter/generate', methods=['GET', 'POST'])
@admin_required
def generate_offer_letter(employee_id):
    """Generate personalized Offer Letter DOCX for selected Employee using dynamic template mapping."""
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    app_record = employee.application
    job = employee.job

    if not app_record or not job:
        flash('Employee is missing linked application or job posting data.', 'danger')
        return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))

    # Determine internship duration
    internship_duration = app_record.duration_display or (f"{job.duration.replace('_', ' ').title()}" if job.duration else "1 Month")

    # Dynamic template lookup by employee's job/domain + duration
    active_template = None
    template_exists = False
    template_error_msg = None
    try:
        active_template = get_active_offer_letter_template(employee, duration=internship_duration)
        template_exists = bool(active_template and active_template.file_path and os.path.exists(active_template.file_path))
    except (OfferLetterTemplateNotFoundError, OfferLetterTemplateFileMissingError) as tmpl_err:
        active_template = None
        template_exists = False
        template_error_msg = str(tmpl_err)

    if request.method == 'POST':
        if not active_template or not template_exists:
            err = template_error_msg or f"No active Offer Letter template is configured for {job.department or job.title} — {internship_duration}. Please upload or activate the appropriate template."
            flash(err, 'danger')
            return redirect(url_for('admin.generate_offer_letter', employee_id=employee.employee_id))

        custom_params = {
            'job_title': (request.form.get('job_title') or '').strip() or job.title,
            'responsibilities': (request.form.get('responsibilities') or '').strip() or None,
            'key_tasks': (request.form.get('key_tasks') or '').strip() or None,
            'joining_date': (request.form.get('joining_date') or '').strip() or 'Immediate / As mutually agreed',
            'work_mode': (request.form.get('work_mode') or '').strip() or (job.location if job.location else 'Remote'),
            'conditions': (request.form.get('conditions') or '').strip() or 'satisfactory verification of academic credentials and submission of government identity documentation',
            'acceptance_deadline': (request.form.get('acceptance_deadline') or '').strip() or None
        }

        try:
            emp_doc, output_path = generate_offer_letter_docx(employee, custom_params)
            flash(f"Offer Letter for {employee.candidate_name} ({employee.employee_id}) generated successfully using {active_template.name}!", 'success')
            return redirect(url_for('admin.verify_offer_letter', employee_id=employee.employee_id))
        except (OfferLetterTemplateNotFoundError, OfferLetterTemplateFileMissingError) as e:
            flash(str(e), 'danger')
            return redirect(url_for('admin.generate_offer_letter', employee_id=employee.employee_id))
        except Exception as e:
            flash(f"Error generating Offer Letter: {str(e)}", 'danger')
            return redirect(url_for('admin.generate_offer_letter', employee_id=employee.employee_id))

    # GET request - Show parameter review form before generating
    return render_template(
        'admin/offer_letter_generate.html',
        employee=employee,
        app=app_record,
        job=job,
        active_template=active_template,
        template_exists=template_exists,
        template_error_msg=template_error_msg
    )


@admin_bp.route('/employees/<string:employee_id>/offer-letter/preview', methods=['GET'])
@admin_required
def preview_offer_letter(employee_id):
    """Download / preview the generated employee-specific Offer Letter DOCX."""
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    emp_doc = employee.offer_letter_doc

    if not emp_doc or not os.path.exists(emp_doc.file_path):
        flash('Offer Letter has not been generated yet. Please generate it first.', 'warning')
        return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))

    return send_from_directory(
        os.path.dirname(emp_doc.file_path),
        os.path.basename(emp_doc.file_path),
        as_attachment=True,
        download_name=emp_doc.file_name
    )


@admin_bp.route('/employees/<string:employee_id>/offer-letter/verify', methods=['GET'])
@admin_required
def verify_offer_letter(employee_id):
    """Pre-send verification view with email preview, locked recipient, and confirm button."""
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    app_record = employee.application
    job = employee.job
    emp_doc = employee.offer_letter_doc

    if not emp_doc or not os.path.exists(emp_doc.file_path):
        flash('Offer Letter has not been generated yet. Please generate it first.', 'warning')
        return redirect(url_for('admin.generate_offer_letter', employee_id=employee.employee_id))

    # Load email template to preview formatted email
    from services.email_service import replace_variables, markdown_to_html_email, DEFAULT_OFFER_LETTER_SUBJECT, DEFAULT_OFFER_LETTER_BODY
    email_tmpl = EmailTemplate.query.filter_by(template_type='offer_letter').first()
    
    company_email = current_app.config.get('CONTACT_EMAIL', 'info@antimatrix.co.in')
    website = 'www.antimatrix.co.in'
    duration = app_record.duration_display or (f"{job.duration.replace('_', ' ').title()}" if job and job.duration else "3 Months")
    joining_date = 'Immediate / As mutually agreed'

    variables = {
        'Student Name': employee.candidate_name,
        'Internship Role': job.title if job else 'Internship Position',
        'Application ID': app_record.formatted_code,
        'Internship Duration': duration,
        'Start Date': joining_date,
        'Company Email': company_email,
        'Website': website,
        'employee_name': employee.candidate_name,
        'employee_id': employee.employee_id,
        'job_title': job.title if job else '',
        'department': job.department if job else '',
        'application_id': app_record.formatted_code,
        'internship_duration': duration,
        'start_date': joining_date,
        'company_email': company_email,
        'website': website
    }

    raw_subject = email_tmpl.subject if email_tmpl else DEFAULT_OFFER_LETTER_SUBJECT
    raw_body = email_tmpl.body if email_tmpl else DEFAULT_OFFER_LETTER_BODY

    subject_preview = replace_variables(raw_subject, variables)
    body_preview = replace_variables(raw_body, variables)
    body_html_preview = markdown_to_html_email(body_preview, title=subject_preview)

    return render_template(
        'admin/offer_letter_verify.html',
        employee=employee,
        app=app_record,
        job=job,
        emp_doc=emp_doc,
        subject_preview=subject_preview,
        body_preview=body_preview,
        body_html_preview=body_html_preview
    )


@admin_bp.route('/employees/<string:employee_id>/offer-letter/send', methods=['POST'])
@admin_required
def send_offer_letter(employee_id):
    """Explicit Verify & Send action sending the Offer Letter email with attachment."""
    employee = Employee.query.filter_by(employee_id=employee_id).first_or_404()
    emp_doc = employee.offer_letter_doc

    if not emp_doc:
        flash('No Offer Letter found for this employee. Please generate it first.', 'danger')
        return redirect(url_for('admin.generate_offer_letter', employee_id=employee.employee_id))

    # ONE-TIME SEND PROTECTION
    if emp_doc.email_status == 'sent':
        flash('Offer Letter already sent. Duplicate sending is prevented.', 'warning')
        return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))

    success, message = send_offer_letter_email(employee)
    if success:
        flash(message, 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('admin.view_employee', employee_id=employee.employee_id))


# ==============================================================================
# MONEY MANAGEMENT & REVENUE DASHBOARD
# ==============================================================================

@admin_bp.route('/money-management')
@admin_required
def money_management():
    """
    Main Admin Money Management & Revenue Dashboard.
    Displays Google Pay-style chronological transactions, summaries, and filters.
    """
    from services.money_service import (
        get_financial_summary, filter_transactions,
        STANDARD_INCOME_CATEGORIES, STANDARD_EXPENSE_CATEGORIES, PAYMENT_METHODS
    )

    type_filter = (request.args.get('type') or 'all').strip().lower()
    env_filter = (request.args.get('env') or 'all').strip().lower()
    date_filter = (request.args.get('date') or 'all').strip().lower()
    start_date = (request.args.get('start_date') or '').strip() or None
    end_date = (request.args.get('end_date') or '').strip() or None
    category_filter = (request.args.get('category') or 'all').strip()
    search_query = (request.args.get('q') or '').strip()
    sort_by = (request.args.get('sort') or 'newest').strip().lower()

    # Dynamic backend summary calculations (database-driven)
    summary = get_financial_summary(
        env_filter=env_filter,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        category_filter=category_filter,
        search_query=search_query
    )

    # Filtered transaction list
    transactions = filter_transactions(
        type_filter=type_filter,
        env_filter=env_filter,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        category_filter=category_filter,
        search_query=search_query,
        sort_by=sort_by
    ).all()

    # Aggregate distinct categories for filter dropdown
    db_categories = db.session.query(MoneyTransaction.category).distinct().all()
    all_categories = sorted(list(set(
        STANDARD_INCOME_CATEGORIES + 
        STANDARD_EXPENSE_CATEGORIES + 
        [c[0] for c in db_categories if c[0]]
    )))

    # Base counts for admin navigation badges
    total_jobs = JobPosting.query.count()
    total_applications = JobApplication.query.count()
    new_applications = JobApplication.query.filter_by(status='New').count()
    total_employees = Employee.query.count()

    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    return render_template(
        'admin/money_management.html',
        summary=summary,
        transactions=transactions,
        type_filter=type_filter,
        env_filter=env_filter,
        date_filter=date_filter,
        start_date=start_date,
        end_date=end_date,
        category_filter=category_filter,
        search_query=search_query,
        sort_by=sort_by,
        categories=all_categories,
        income_categories=STANDARD_INCOME_CATEGORIES,
        expense_categories=STANDARD_EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        today_date_str=today_date_str,
        total_jobs=total_jobs,
        total_applications=total_applications,
        new_applications=new_applications,
        total_employees=total_employees
    )


@admin_bp.route('/money-management/add', methods=['GET', 'POST'])
@admin_required
def add_money_transaction():
    """
    Dedicated Add Transaction page for recording manual Income and Expense entries.
    GET: Displays the standalone executive Add Transaction form.
    POST: Processes and stores the manual transaction with audit logging.
    """
    from services.money_service import (
        STANDARD_INCOME_CATEGORIES, STANDARD_EXPENSE_CATEGORIES, PAYMENT_METHODS
    )

    if request.method == 'POST':
        txn_type = (request.form.get('transaction_type') or '').strip().upper()
        amount_str = (request.form.get('amount') or '').strip()
        txn_date_str = (request.form.get('transaction_date') or '').strip()
        txn_time = (request.form.get('transaction_time') or '').strip()
        category = (request.form.get('category') or '').strip()
        custom_category = (request.form.get('custom_category') or '').strip()
        purpose = (request.form.get('purpose') or '').strip()
        description = (request.form.get('description') or '').strip()
        payment_method = (request.form.get('payment_method') or 'Bank Transfer').strip()
        reference = (request.form.get('reference') or '').strip()

        # Handle custom category
        if category.lower() in ['other', 'custom', 'other income', 'other expense'] and custom_category:
            category = custom_category
        elif not category and custom_category:
            category = custom_category

        # Validate Transaction Type
        if txn_type not in ['INCOME', 'EXPENSE']:
            flash('Invalid transaction type. Must be Income or Expense.', 'danger')
            return redirect(url_for('admin.add_money_transaction'))

        # Validate Amount (must be positive numeric > 0)
        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError("Amount must be greater than zero.")
        except (ValueError, TypeError):
            flash('Please enter a valid numeric amount greater than zero.', 'danger')
            return redirect(url_for('admin.add_money_transaction'))

        # Validate Transaction Date (supports historical dates)
        if not txn_date_str:
            txn_date = datetime.now(timezone.utc).date()
        else:
            try:
                txn_date = datetime.strptime(txn_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format. Please select a valid date (YYYY-MM-DD).', 'danger')
                return redirect(url_for('admin.add_money_transaction'))

        # Default time if not entered
        if not txn_time:
            txn_time = datetime.now(timezone.utc).strftime('%I:%M %p')

        # Category is required
        if not category:
            category = "Other Income" if txn_type == 'INCOME' else "Other Expense"

        if not purpose:
            purpose = category

        now_utc = datetime.now(timezone.utc)

        try:
            new_txn = MoneyTransaction(
                transaction_type=txn_type,
                amount=amount,
                transaction_date=txn_date,
                transaction_time=txn_time,
                category=category,
                purpose=purpose,
                description=description,
                payment_method=payment_method,
                reference=reference,
                source='MANUAL',
                provider='MANUAL',
                environment='MANUAL',
                created_by_admin_id=current_user.id,
                created_at=now_utc,
                updated_at=now_utc
            )
            db.session.add(new_txn)
            db.session.commit()
            flash(f"Manual {txn_type.capitalize()} of ₹{amount:,.2f} recorded successfully!", 'success')
            return redirect(url_for('admin.money_management'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error saving transaction: {str(e)}", 'danger')
            return redirect(url_for('admin.add_money_transaction'))

    # GET Request: Prepare form context
    total_jobs = JobPosting.query.count()
    total_applications = JobApplication.query.count()
    new_applications = JobApplication.query.filter_by(status='New').count()
    total_employees = Employee.query.count()
    today_date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    return render_template(
        'admin/money_management_add.html',
        income_categories=STANDARD_INCOME_CATEGORIES,
        expense_categories=STANDARD_EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        today_date_str=today_date_str,
        total_jobs=total_jobs,
        total_applications=total_applications,
        new_applications=new_applications,
        total_employees=total_employees
    )


@admin_bp.route('/money-management/transactions/create', methods=['POST'])
@admin_required
def create_money_transaction():
    """
    Legacy / Direct endpoint for manually creating an Income or Expense transaction.
    Maintains full backward compatibility.
    """
    return add_money_transaction()


@admin_bp.route('/money-management/transactions/<int:txn_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_money_transaction(txn_id):
    """
    Edit an existing manual transaction.
    GET: Renders dedicated Edit Transaction page with pre-populated values.
    POST: Validates and updates the existing record in place, recalculating all metrics.
    Automatic Cashfree transactions are strictly locked and cannot be edited.
    """
    from services.money_service import (
        STANDARD_INCOME_CATEGORIES, STANDARD_EXPENSE_CATEGORIES, PAYMENT_METHODS,
        validate_manual_admin_mutation
    )

    txn = db.session.get(MoneyTransaction, txn_id)
    if not txn:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('admin.money_management'))

    allowed, err_msg = validate_manual_admin_mutation(current_user, txn=txn, action='edit')
    if not allowed:
        flash(err_msg or 'You are not authorized to edit this transaction.', 'danger')
        return redirect(url_for('admin.money_management'))

    if request.method == 'POST':
        txn_type = (request.form.get('transaction_type') or '').strip().upper()
        amount_str = (request.form.get('amount') or '').strip()
        txn_date_str = (request.form.get('transaction_date') or '').strip()
        txn_time = (request.form.get('transaction_time') or '').strip()
        category = (request.form.get('category') or '').strip()
        custom_category = (request.form.get('custom_category') or '').strip()
        purpose = (request.form.get('purpose') or '').strip()
        description = (request.form.get('description') or '').strip()
        payment_method = (request.form.get('payment_method') or txn.payment_method or 'Manual').strip()
        reference = (request.form.get('reference') or '').strip()

        if category.lower() in ['other', 'custom', 'other income', 'other expense'] and custom_category:
            category = custom_category
        elif not category and custom_category:
            category = custom_category

        # Validate Transaction Type
        if txn_type in ['INCOME', 'EXPENSE']:
            txn.transaction_type = txn_type

        # Validate Amount (must be positive numeric > 0)
        try:
            amount = float(amount_str)
            if amount <= 0:
                raise ValueError("Amount must be greater than zero.")
            txn.amount = amount
        except (ValueError, TypeError):
            flash('Please enter a valid numeric amount greater than zero.', 'danger')
            return redirect(url_for('admin.edit_money_transaction', txn_id=txn_id))

        # Validate Date
        if txn_date_str:
            try:
                txn.transaction_date = datetime.strptime(txn_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('Invalid date format. Please select a valid date (YYYY-MM-DD).', 'danger')
                return redirect(url_for('admin.edit_money_transaction', txn_id=txn_id))

        if txn_time:
            txn.transaction_time = txn_time

        if category:
            txn.category = category
        if purpose:
            txn.purpose = purpose
        txn.description = description
        txn.payment_method = payment_method
        txn.reference = reference
        txn.updated_at = datetime.now(timezone.utc)

        try:
            db.session.commit()
            flash('Transaction updated successfully.', 'success')
            return redirect(url_for('admin.money_management'))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating transaction: {str(e)}", 'danger')
            return redirect(url_for('admin.edit_money_transaction', txn_id=txn_id))

    # GET Request: Prepare pre-populated form context
    total_jobs = JobPosting.query.count()
    total_applications = JobApplication.query.count()
    new_applications = JobApplication.query.filter_by(status='New').count()
    total_employees = Employee.query.count()

    is_custom_category = (
        txn.category not in STANDARD_INCOME_CATEGORIES and 
        txn.category not in STANDARD_EXPENSE_CATEGORIES
    )

    return render_template(
        'admin/money_management_edit.html',
        txn=txn,
        is_custom_category=is_custom_category,
        income_categories=STANDARD_INCOME_CATEGORIES,
        expense_categories=STANDARD_EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        total_jobs=total_jobs,
        total_applications=total_applications,
        new_applications=new_applications,
        total_employees=total_employees
    )


@admin_bp.route('/money-management/transactions/<int:txn_id>/delete', methods=['POST'])
@admin_required
def delete_money_transaction(txn_id):
    """
    Delete a manually created transaction.
    Cashfree automatic transactions CANNOT be deleted.
    """
    txn = db.session.get(MoneyTransaction, txn_id)
    if not txn:
        flash('Transaction not found.', 'danger')
        return redirect(url_for('admin.money_management'))

    from services.money_service import validate_manual_admin_mutation
    allowed, err_msg = validate_manual_admin_mutation(current_user, txn=txn, action='delete')
    if not allowed:
        flash(err_msg or 'Cashfree automatic transactions cannot be deleted. They remain permanently linked to payment records.', 'danger')
        return redirect(url_for('admin.money_management'))

    try:
        amount = txn.amount
        txn_type = txn.transaction_type
        db.session.delete(txn)
        db.session.commit()
        flash(f"Manual {txn_type.capitalize()} of ₹{amount:,.2f} deleted successfully.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting transaction: {str(e)}", 'danger')

    return redirect(url_for('admin.money_management'))


@admin_bp.route('/money-management/transactions/<int:txn_id>', methods=['GET'])
@admin_required
def get_money_transaction_detail(txn_id):
    """Return full transaction details as JSON for the audit details modal."""
    txn = db.session.get(MoneyTransaction, txn_id)
    if not txn:
        return jsonify({'error': 'Transaction not found'}), 404
    return jsonify(txn.to_dict())


@admin_bp.route('/money-management/reconcile', methods=['POST'])
@admin_required
def reconcile_payments():
    """Admin tool to scan for any verified payments that might be missing from Money Management."""
    from services.money_service import reconcile_cashfree_payments
    try:
        count_added, total_checked = reconcile_cashfree_payments()
        if count_added > 0:
            flash(f"Reconciliation complete: {count_added} missing Cashfree payment(s) successfully recorded.", 'success')
        else:
            flash(f"Reconciliation complete: All {total_checked} paid transactions are fully up to date!", 'info')
    except Exception as e:
        flash(f"Reconciliation error: {str(e)}", 'danger')

    return redirect(url_for('admin.money_management'))


@admin_bp.route('/money-management/transactions/clear-all', methods=['POST'])
@admin_required
def clear_all_money_transactions():
    """
    Destructive Admin-Only action to clear all MoneyManagement ledger transactions.
    Requires explicit confirmation code ('CLEAR').
    Preserves all Payment, Application, Employee, and User records.
    """
    from services.money_service import clear_all_transactions

    confirmation = (request.form.get('confirmation') or '').strip()

    if confirmation.upper() != 'CLEAR':
        flash("Confirmation failed. You must type 'CLEAR' exactly to clear all transactions.", 'danger')
        return redirect(url_for('admin.money_management'))

    success, count, err = clear_all_transactions(admin_user=current_user)
    if success:
        flash("All transactions cleared successfully.", 'success')
    else:
        flash(f"Error clearing transactions: {err}", 'danger')

    return redirect(url_for('admin.money_management'))




