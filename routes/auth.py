import re
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, Employee, JobApplication
from services.oauth_service import (
    oauth,
    is_google_configured,
    is_github_configured,
    get_google_redirect_uri,
    get_github_redirect_uri,
    find_or_create_oauth_user
)

auth_bp = Blueprint('auth', __name__)

EMAIL_REGEX = re.compile(r'^\S+@\S+\.\S+$')


def get_safe_redirect(target_url, default='/'):
    """
    Validate redirect URL to prevent Open Redirect vulnerabilities.
    Only allows internal, relative application paths.
    """
    if not default:
        default = '/'
    if not target_url or not isinstance(target_url, str):
        return default
    target_url = target_url.strip()
    if not target_url.startswith('/') or target_url.startswith('//') or '\\' in target_url:
        return default
    try:
        parsed = urlparse(target_url)
        if parsed.netloc or parsed.scheme:
            return default
        return target_url
    except Exception:
        return default


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    raw_target = (
        request.args.get('next') or
        request.args.get('redirect') or
        request.form.get('redirect') or
        request.form.get('next')
    )
    redirect_target = get_safe_redirect(raw_target)
    
    if current_user.is_authenticated:
        return redirect(redirect_target)

    if request.method == 'POST':
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        identifier = (data.get('email') or data.get('identifier') or '').strip()
        password = data.get('password') or ''
        remember = bool(data.get('remember', False))
        if isinstance(data.get('remember'), str):
            remember = data.get('remember') in ('true', '1', 'on', 'yes')

        # Check for redirect inside POST payload
        post_target = data.get('redirect') or data.get('next') or raw_target
        redirect_target = get_safe_redirect(post_target)

        errors = {}
        if not identifier:
            errors['email'] = 'Email or Employee ID is required'

        if not password:
            errors['password'] = 'Password is required'
        elif len(password) < 6:
            errors['password'] = 'Password must be at least 6 characters'

        if errors:
            if is_json:
                return jsonify({'status': 'error', 'errors': errors}), 400
            for field, err in errors.items():
                flash(err, 'error')
            return render_template('auth/login.html', errors=errors, email=identifier, redirect_target=redirect_target)

        authenticated_user = None

        # 1. Check if identifier is an Employee ID (e.g. AM4827)
        emp_match = Employee.query.filter(Employee.employee_id.ilike(identifier)).first()
        if emp_match:
            is_valid = emp_match.check_password(password) or (
                emp_match.onboarding_credential is not None and emp_match.onboarding_credential.verify_password(password)
            )
            if is_valid:
                # Valid Employee ID & Password -> Sync or create User account for candidate
                cand_email = emp_match.candidate_email.lower()
                user = User.query.filter_by(email=cand_email).first()
                if not user:
                    user = User(
                        name=emp_match.candidate_name or f"Employee {emp_match.employee_id}",
                        email=cand_email,
                        role='member'
                    )
                    user.set_password(password)
                    db.session.add(user)
                    db.session.commit()
                else:
                    user.set_password(password)
                    db.session.commit()
                authenticated_user = user
            else:
                errors['password'] = 'Invalid Employee ID or password'
                if is_json:
                    return jsonify({'status': 'error', 'errors': errors}), 401
                flash('Invalid Employee ID or password', 'error')
                return render_template('auth/login.html', errors=errors, email=identifier, redirect_target=redirect_target)

        # 2. Check if identifier is an Email Address
        elif EMAIL_REGEX.match(identifier):
            user = User.query.filter_by(email=identifier.lower()).first()
            emp_by_email = Employee.query.join(JobApplication).filter(JobApplication.email.ilike(identifier.lower())).first()

            if user and user.check_password(password):
                authenticated_user = user
            elif emp_by_email and emp_by_email.check_password(password):
                if not user:
                    user = User(
                        name=emp_by_email.candidate_name or identifier.split('@')[0].capitalize(),
                        email=identifier.lower(),
                        role='member'
                    )
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                authenticated_user = user
            elif not user:
                # For seamless demo and standard user creation
                user = User(
                    name=identifier.split('@')[0].capitalize(),
                    email=identifier.lower()
                )
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                authenticated_user = user
            else:
                errors['password'] = 'Invalid email or password'
                if is_json:
                    return jsonify({'status': 'error', 'errors': errors}), 401
                flash('Invalid email or password', 'error')
                return render_template('auth/login.html', errors=errors, email=identifier, redirect_target=redirect_target)

        else:
            errors['email'] = 'Enter a valid email address or Employee ID (e.g. AM4827)'
            if is_json:
                return jsonify({'status': 'error', 'errors': errors}), 400
            flash('Enter a valid email address or Employee ID (e.g. AM4827)', 'error')
            return render_template('auth/login.html', errors=errors, email=identifier, redirect_target=redirect_target)

        login_user(authenticated_user, remember=remember)

        if is_json:
            return jsonify({
                'status': 'success',
                'message': 'Welcome back!',
                'redirect': redirect_target,
                'user': authenticated_user.to_dict()
            })

        return redirect(redirect_target)

    return render_template('auth/login.html', redirect_target=redirect_target, errors={})


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    raw_target = (
        request.args.get('next') or
        request.args.get('redirect') or
        request.form.get('redirect') or
        request.form.get('next')
    )
    redirect_target = get_safe_redirect(raw_target)

    if current_user.is_authenticated:
        return redirect(redirect_target)

    if request.method == 'POST':
        is_json = request.is_json
        data = request.get_json() if is_json else request.form

        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip()
        password = data.get('password') or ''
        confirm = data.get('confirm') or ''
        terms = bool(data.get('terms', False))
        if isinstance(data.get('terms'), str):
            terms = data.get('terms') in ('true', '1', 'on', 'yes')

        post_target = data.get('redirect') or data.get('next') or raw_target
        redirect_target = get_safe_redirect(post_target)

        errors = {}
        if not name:
            errors['name'] = 'Full name is required'

        if not email:
            errors['email'] = 'Email is required'
        elif not EMAIL_REGEX.match(email):
            errors['email'] = 'Enter a valid email address'

        if not password:
            errors['password'] = 'Password is required'
        elif len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters'

        if not confirm:
            errors['confirm'] = 'Please confirm your password'
        elif confirm != password:
            errors['confirm'] = 'Passwords do not match'

        if not terms:
            errors['terms'] = 'You must accept the terms to continue'

        if errors:
            if is_json:
                return jsonify({'status': 'error', 'errors': errors}), 400
            for field, err in errors.items():
                flash(err, 'error')
            return render_template('auth/signup.html', errors=errors, name=name, email=email, redirect_target=redirect_target)

        # Check existing user
        user = User.query.filter_by(email=email.lower()).first()
        if user:
            user.name = name
            user.set_password(password)
        else:
            user = User(
                name=name,
                email=email.lower()
            )
            user.set_password(password)
            db.session.add(user)

        db.session.commit()
        login_user(user)

        if is_json:
            return jsonify({
                'status': 'success',
                'message': 'Account created successfully!',
                'redirect': redirect_target,
                'user': user.to_dict()
            })

        return redirect(redirect_target)

    return render_template('auth/signup.html', redirect_target=redirect_target, errors={})


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    if current_user.is_authenticated:
        logout_user()
    return redirect(url_for('main.home'))


# ============================================================================
# Google OAuth 2.0 Authentication Routes
# ============================================================================

@auth_bp.route('/auth/google')
@auth_bp.route('/login/google')
def google_login():
    """Initiate Google OAuth 2.0 authorization redirect."""
    if current_user.is_authenticated:
        return redirect(get_safe_redirect(request.args.get('next') or request.args.get('redirect')))

    if not is_google_configured():
        flash("Google Login is currently not configured. Please sign in with your email or contact support.", "warning")
        return redirect(url_for('auth.login'))

    target_url = get_safe_redirect(request.args.get('next') or request.args.get('redirect'))
    session['oauth_next'] = target_url
    redirect_uri = get_google_redirect_uri()

    try:
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception as e:
        current_app.logger.error(f"Failed to initiate Google OAuth redirect: {str(e)}")
        flash("Unable to initiate Google sign-in. Please try again or use email login.", "error")
        return redirect(url_for('auth.login'))


@auth_bp.route('/auth/google/callback')
def google_callback():
    """Handle Google OAuth 2.0 callback, verify token, and create/link session."""
    # Check for authorization error or user cancellation
    error = request.args.get('error')
    if error:
        if error in ('access_denied', 'user_cancelled_authorize'):
            flash("Google sign-in was cancelled.", "info")
        else:
            flash("Google authorization was not completed. Please try again.", "error")
        return redirect(url_for('auth.login'))

    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        current_app.logger.warning(f"Google OAuth token exchange failed: {str(e)}")
        flash("Unable to sign you in with Google. Please try again.", "error")
        return redirect(url_for('auth.login'))

    # Extract user profile from OpenID token or userinfo endpoint
    user_info = token.get('userinfo')
    if not user_info:
        try:
            user_info = oauth.google.userinfo()
        except Exception as e:
            current_app.logger.warning(f"Failed to fetch Google userinfo: {str(e)}")
            flash("Unable to retrieve your Google profile. Please try again.", "error")
            return redirect(url_for('auth.login'))

    email = user_info.get('email')
    if not email:
        flash("Google account did not provide an email address. Please sign in with another method.", "error")
        return redirect(url_for('auth.login'))

    name = user_info.get('name') or user_info.get('given_name')
    picture = user_info.get('picture')
    provider_id = user_info.get('sub')

    try:
        user = find_or_create_oauth_user(
            provider='google',
            provider_id=provider_id,
            email=email,
            name=name,
            picture=picture
        )
        login_user(user, remember=True)
        flash(f"Welcome back, {user.name}!", "success")
    except Exception as e:
        current_app.logger.error(f"Error saving Google OAuth user: {str(e)}")
        flash("An error occurred during sign-in. Please try again.", "error")
        return redirect(url_for('auth.login'))

    redirect_target = get_safe_redirect(session.pop('oauth_next', None) or '/')
    return redirect(redirect_target)


# ============================================================================
# GitHub OAuth 2.0 Authentication Routes
# ============================================================================

@auth_bp.route('/auth/github')
@auth_bp.route('/login/github')
def github_login():
    """Initiate GitHub OAuth authorization redirect."""
    if current_user.is_authenticated:
        return redirect(get_safe_redirect(request.args.get('next') or request.args.get('redirect')))

    if not is_github_configured():
        flash("GitHub Login is currently not configured. Please sign in with your email or contact support.", "warning")
        return redirect(url_for('auth.login'))

    target_url = get_safe_redirect(request.args.get('next') or request.args.get('redirect'))
    session['oauth_next'] = target_url
    redirect_uri = get_github_redirect_uri()

    try:
        return oauth.github.authorize_redirect(redirect_uri)
    except Exception as e:
        current_app.logger.error(f"Failed to initiate GitHub OAuth redirect: {str(e)}")
        flash("Unable to initiate GitHub sign-in. Please try again or use email login.", "error")
        return redirect(url_for('auth.login'))


@auth_bp.route('/auth/github/callback')
def github_callback():
    """Handle GitHub OAuth callback, retrieve verified profile/email, and create/link session."""
    error = request.args.get('error')
    if error:
        if error in ('access_denied', 'user_cancelled_authorize'):
            flash("GitHub sign-in was cancelled.", "info")
        else:
            flash("GitHub authorization was not completed. Please try again.", "error")
        return redirect(url_for('auth.login'))

    try:
        token = oauth.github.authorize_access_token()
    except Exception as e:
        current_app.logger.warning(f"GitHub OAuth token exchange failed: {str(e)}")
        flash("Unable to sign you in with GitHub. Please try again.", "error")
        return redirect(url_for('auth.login'))

    # Fetch GitHub user profile
    try:
        resp = oauth.github.get('user', token=token)
        profile = resp.json()
    except Exception as e:
        current_app.logger.warning(f"Failed to fetch GitHub profile: {str(e)}")
        flash("Unable to retrieve your GitHub profile. Please try again.", "error")
        return redirect(url_for('auth.login'))

    provider_id = profile.get('id')
    name = profile.get('name') or profile.get('login')
    picture = profile.get('avatar_url')
    email = profile.get('email')

    # If email is private in GitHub user profile, fetch from /user/emails endpoint
    if not email:
        try:
            emails_resp = oauth.github.get('user/emails', token=token)
            emails_data = emails_resp.json()
            if isinstance(emails_data, list):
                for em in emails_data:
                    if em.get('primary') and em.get('verified'):
                        email = em.get('email')
                        break
                if not email and emails_data:
                    for em in emails_data:
                        if em.get('verified'):
                            email = em.get('email')
                            break
                    if not email:
                        email = emails_data[0].get('email')
        except Exception as e:
            current_app.logger.warning(f"Failed to fetch GitHub emails: {str(e)}")

    if not email:
        flash("GitHub account does not have a verified email address. Please sign in with another method.", "error")
        return redirect(url_for('auth.login'))

    try:
        user = find_or_create_oauth_user(
            provider='github',
            provider_id=provider_id,
            email=email,
            name=name,
            picture=picture
        )
        login_user(user, remember=True)
        flash(f"Welcome back, {user.name}!", "success")
    except Exception as e:
        current_app.logger.error(f"Error saving GitHub OAuth user: {str(e)}")
        flash("An error occurred during sign-in. Please try again.", "error")
        return redirect(url_for('auth.login'))

    redirect_target = get_safe_redirect(session.pop('oauth_next', None) or '/')
    return redirect(redirect_target)

