import logging
import os
import sys
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from config import config, INTERNSHIP_FEES, INTERNSHIP_PRICING
from models import db, User, JobPosting, JobApplication, Payment
from routes import main_bp, auth_bp, contact_bp, admin_bp

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger('anti_matrix')

csrf = CSRFProtect()
login_manager = LoginManager()


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', 'default')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Ensure upload directories exist
    upload_resumes = app.config.get('UPLOAD_FOLDER_RESUMES', os.path.join(app.root_path, 'uploads', 'resumes'))
    upload_documents = app.config.get('UPLOAD_FOLDER_DOCUMENTS', os.path.join(app.root_path, 'uploads', 'documents'))
    os.makedirs(upload_resumes, exist_ok=True)
    os.makedirs(upload_documents, exist_ok=True)


    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    # Initialize OAuth (Google & GitHub)
    from services.oauth_service import init_oauth
    init_oauth(app)

    # Reverse proxy header support (ensures correct HTTPS redirects behind proxies)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Exempt Cashfree webhook endpoint from CSRF
    from routes.main import cashfree_webhook
    csrf.exempt(cashfree_webhook)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'


    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (ValueError, TypeError):
            return None

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(contact_bp)
    app.register_blueprint(admin_bp)

    # Global context processors for Jinja templates
    @app.context_processor
    def inject_globals():
        return {
            'current_year': datetime.now().year,
            'app_name': 'Anti-Matrix'
        }

    @app.route('/api/health', methods=['GET'])
    def health_check():
        return jsonify({
            'status': 'OK',
            'message': 'Your API is running',
            'timestamp': datetime.now(timezone.utc).isoformat()
        })


    # Error Handlers
    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/404.html'), 500

    # Auto-initialize database tables and seed default data
    with app.app_context():
        db.create_all()
        
        # Log database backend safely without exposing credentials or hosts
        backend_name = db.engine.dialect.name.upper()
        logger.info(f"DATABASE CONFIGURATION DETECTED: {backend_name}")

        # Ensure database schema is updated for user_id on job_applications
        try:
            from sqlalchemy import inspect, text
            inspector = inspect(db.engine)
            dialect_is_sqlite = (db.engine.dialect.name == 'sqlite')

            if 'job_applications' in inspector.get_table_names():
                cols = [c['name'] for c in inspector.get_columns('job_applications')]
                if 'user_id' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text('ALTER TABLE job_applications ADD COLUMN user_id INTEGER REFERENCES users(id)'))
                        try:
                            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_job_applications_user_id ON job_applications (user_id)'))
                        except Exception:
                            pass
                        conn.commit()

                if 'application_success_email_status' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE job_applications ADD COLUMN application_success_email_status VARCHAR(30) DEFAULT 'PENDING' NOT NULL"))
                        conn.commit()

                if 'application_success_email_sent_at' not in cols:
                    with db.engine.connect() as conn:
                        type_str = "DATETIME" if dialect_is_sqlite else "TIMESTAMP"
                        conn.execute(text(f"ALTER TABLE job_applications ADD COLUMN application_success_email_sent_at {type_str}"))
                        conn.commit()

                if 'joining_date' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE job_applications ADD COLUMN joining_date VARCHAR(100)"))
                        conn.commit()

                if 'joining_email_status' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE job_applications ADD COLUMN joining_email_status VARCHAR(30) DEFAULT 'NOT_SENT' NOT NULL"))
                        conn.commit()

                if 'joining_email_sent_at' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE job_applications ADD COLUMN joining_email_sent_at {type_str}"))
                        conn.commit()

                if 'offer_completed_at' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE job_applications ADD COLUMN offer_completed_at {type_str}"))
                        conn.commit()

                if 'hired_at' not in cols:
                    with db.engine.connect() as conn:
                        conn.execute(text(f"ALTER TABLE job_applications ADD COLUMN hired_at {type_str}"))
                        conn.commit()
                
                # Auto-link existing applications where user email matches
                with db.engine.connect() as conn:
                    conn.execute(text('''
                        UPDATE job_applications
                        SET user_id = (
                            SELECT id FROM users WHERE LOWER(users.email) = LOWER(job_applications.email) LIMIT 1
                        )
                        WHERE user_id IS NULL AND EXISTS (
                            SELECT 1 FROM users WHERE LOWER(users.email) = LOWER(job_applications.email)
                        )
                    '''))
                    conn.commit()

            if 'employee_documents' in inspector.get_table_names():
                emp_doc_col_objs = inspector.get_columns('employee_documents')
                emp_doc_cols = [c['name'] for c in emp_doc_col_objs]
                emp_id_col = next((c for c in emp_doc_col_objs if c['name'] == 'employee_id'), None)

                # If employee_id is NOT NULL in SQLite table definition, migrate it non-destructively (SQLite only)
                if dialect_is_sqlite and emp_id_col and not emp_id_col.get('nullable', True):
                    with db.engine.connect() as conn:
                        conn.execute(text('''
                            CREATE TABLE IF NOT EXISTS employee_documents_new (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                application_id INTEGER REFERENCES job_applications(id) ON DELETE CASCADE,
                                employee_id INTEGER REFERENCES employees(id) ON DELETE CASCADE,
                                template_id INTEGER REFERENCES document_templates(id) ON DELETE SET NULL,
                                document_type VARCHAR(50) NOT NULL DEFAULT 'offer_letter',
                                file_name VARCHAR(255) NOT NULL,
                                file_path VARCHAR(500) NOT NULL,
                                status VARCHAR(30) NOT NULL DEFAULT 'GENERATED',
                                email_status VARCHAR(30) NOT NULL DEFAULT 'not_sent',
                                email_error TEXT,
                                generated_at DATETIME NOT NULL,
                                verified_at DATETIME,
                                sent_at DATETIME,
                                created_at DATETIME NOT NULL,
                                updated_at DATETIME NOT NULL
                            )
                        '''))
                        existing_cols = set(emp_doc_cols)
                        target_cols = [c for c in ['id', 'employee_id', 'document_type', 'file_name', 'file_path', 'status', 'email_status', 'email_error', 'generated_at', 'verified_at', 'sent_at', 'created_at', 'updated_at', 'template_id', 'application_id'] if c in existing_cols]
                        cols_str = ', '.join(target_cols)
                        conn.execute(text(f'INSERT INTO employee_documents_new ({cols_str}) SELECT {cols_str} FROM employee_documents'))
                        conn.execute(text('DROP TABLE employee_documents'))
                        conn.execute(text('ALTER TABLE employee_documents_new RENAME TO employee_documents'))
                        try:
                            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_employee_documents_application_id ON employee_documents (application_id)'))
                            conn.execute(text('CREATE INDEX IF NOT EXISTS ix_employee_documents_employee_id ON employee_documents (employee_id)'))
                        except Exception:
                            pass
                        conn.commit()
                else:
                    if 'template_id' not in emp_doc_cols:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE employee_documents ADD COLUMN template_id INTEGER REFERENCES document_templates(id)'))
                            conn.commit()
                    if 'application_id' not in emp_doc_cols:
                        with db.engine.connect() as conn:
                            conn.execute(text('ALTER TABLE employee_documents ADD COLUMN application_id INTEGER REFERENCES job_applications(id)'))
                            try:
                                conn.execute(text('CREATE INDEX IF NOT EXISTS ix_employee_documents_application_id ON employee_documents (application_id)'))
                            except Exception:
                                pass
                            conn.commit()

                # Backfill application_id for existing employee_documents from employees table
                with db.engine.connect() as conn:
                    conn.execute(text('''
                        UPDATE employee_documents
                        SET application_id = (
                            SELECT application_id FROM employees WHERE employees.id = employee_documents.employee_id LIMIT 1
                        )
                        WHERE application_id IS NULL AND employee_id IS NOT NULL
                    '''))
                    conn.commit()

            if 'employees' in inspector.get_table_names():
                emp_cols = [c['name'] for c in inspector.get_columns('employees')]
                if 'temp_password_encrypted' not in emp_cols:
                    with db.engine.connect() as conn:
                        conn.execute(text("ALTER TABLE employees ADD COLUMN temp_password_encrypted VARCHAR(500)"))
                        conn.commit()

            # Ensure users table has OAuth & profile columns
            if 'users' in inspector.get_table_names():
                user_cols = [c['name'] for c in inspector.get_columns('users')]
                with db.engine.connect() as conn:
                    if 'profile_picture' not in user_cols:
                        conn.execute(text("ALTER TABLE users ADD COLUMN profile_picture VARCHAR(500)"))
                    if 'provider' not in user_cols:
                        conn.execute(text("ALTER TABLE users ADD COLUMN provider VARCHAR(50) DEFAULT 'email' NOT NULL"))
                    if 'provider_id' not in user_cols:
                        conn.execute(text("ALTER TABLE users ADD COLUMN provider_id VARCHAR(255)"))
                        try:
                            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_provider_id ON users (provider_id)"))
                        except Exception:
                            pass
                    if 'phone' not in user_cols:
                        conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(50)"))
                    if 'last_login' not in user_cols:
                        type_str = "DATETIME" if dialect_is_sqlite else "TIMESTAMP"
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN last_login {type_str}"))
                    conn.commit()
        except Exception as e:
            app.logger.warning(f"Database auto-migration note: {str(e)}")

        # Seed default admin user if none exists
        admin_user = User.query.filter_by(role='admin').first()
        if not admin_user:
            default_admin = User(
                name='Anti-Matrix Admin',
                email=os.environ.get('ADMIN_EMAIL', 'admin@antimatrix.ai'),
                role='admin',
                is_active=True
            )
            default_admin.set_password(os.environ.get('ADMIN_PASSWORD', 'Admin@AntiMatrix2026!'))
            db.session.add(default_admin)
            db.session.commit()

        logger.info("APPLICATION IMPORT SUCCESS | SERVER READY")

    return app


port_env = os.environ.get('PORT', '10000')
concurrency_env = os.environ.get('WEB_CONCURRENCY', '1')
logger.info(f"STARTING ANTI-MATRIX CONTAINER | PORT={port_env} | WEB_CONCURRENCY={concurrency_env} | GUNICORN STARTING")

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)
