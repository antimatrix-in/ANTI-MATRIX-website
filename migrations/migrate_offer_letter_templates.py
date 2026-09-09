"""
Non-destructive database migration and seeder for Role/Job Based Offer Letter Template Mapping.
Extends document_templates with:
  - job_domain (VARCHAR(100))
  - duration (VARCHAR(50))
  - created_by (VARCHAR(100))
Seeds the 4 official Microsoft Word master templates from Desktop:
  1. AI & ML (offer letter - AI&ML.docx) -> AI & ML Offer Letter Template
  2. Application Development (offer letter - App dev.docx) -> Application Development Offer Letter Template
  3. Data Analytics (offer letter - Data Analytics.docx) -> Data Analytics Offer Letter Template
  4. Full Stack Development (offer letter - Full stack dev.docx) -> Full Stack Development Offer Letter Template

Guarantees 100% production data safety: zero deletions, drops, or table resets.
"""
import sys
import os
import shutil
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, DocumentTemplate
from sqlalchemy import text, inspect


INITIAL_TEMPLATES = [
    {
        'desktop_filename': 'offer letter - AI&ML.docx',
        'target_filename': 'offer_letter_ai_ml_master.docx',
        'template_name': 'AI & ML Offer Letter Template',
        'job_domain': 'AI & ML',
        'duration': 'Both',
        'created_by': 'System Migration'
    },
    {
        'desktop_filename': 'offer letter - App dev.docx',
        'target_filename': 'offer_letter_app_development_master.docx',
        'template_name': 'Application Development Offer Letter Template',
        'job_domain': 'Application Development',
        'duration': 'Both',
        'created_by': 'System Migration'
    },
    {
        'desktop_filename': 'offer letter - Data Analytics.docx',
        'target_filename': 'offer_letter_data_analytics_master.docx',
        'template_name': 'Data Analytics Offer Letter Template',
        'job_domain': 'Data Analytics',
        'duration': 'Both',
        'created_by': 'System Migration'
    },
    {
        'desktop_filename': 'offer letter - Full stack dev.docx',
        'target_filename': 'offer_letter_full_stack_dev_master.docx',
        'template_name': 'Full Stack Development Offer Letter Template',
        'job_domain': 'Full Stack Development',
        'duration': 'Both',
        'created_by': 'System Migration'
    }
]


def run_migration():
    app = create_app(os.environ.get('FLASK_CONFIG', 'development'))
    with app.app_context():
        print("[MIGRATION] Checking document_templates table schema...")
        inspector = inspect(db.engine)
        existing_cols = [c['name'] for c in inspector.get_columns('document_templates')]
        print(f"[MIGRATION] Existing columns: {existing_cols}")

        with db.engine.connect() as conn:
            # 1. Add job_domain if missing
            if 'job_domain' not in existing_cols:
                print("[MIGRATION] Adding column 'job_domain' to document_templates...")
                conn.execute(text("ALTER TABLE document_templates ADD COLUMN job_domain VARCHAR(100);"))
                conn.commit()

            # 2. Add duration if missing
            if 'duration' not in existing_cols:
                print("[MIGRATION] Adding column 'duration' to document_templates...")
                conn.execute(text("ALTER TABLE document_templates ADD COLUMN duration VARCHAR(50) DEFAULT 'Both';"))
                conn.commit()

            # 3. Add created_by if missing
            if 'created_by' not in existing_cols:
                print("[MIGRATION] Adding column 'created_by' to document_templates...")
                conn.execute(text("ALTER TABLE document_templates ADD COLUMN created_by VARCHAR(100) DEFAULT 'Admin';"))
                conn.commit()

            # Create indices if sqlite/postgres allows
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_document_templates_job_domain ON document_templates (job_domain);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_document_templates_duration ON document_templates (duration);"))
                conn.commit()
                print("[MIGRATION] Verified database indexes on job_domain and duration.")
            except Exception as idx_err:
                print(f"[MIGRATION] Note on index creation: {idx_err}")

        templates_dir = os.path.join(app.root_path, 'uploads', 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        desktop_dir = os.path.join(os.path.expanduser('~'), 'Desktop')

        print("[MIGRATION] Ensuring 4 Job-Specific Master DOCX Templates are in place...")

        for item in INITIAL_TEMPLATES:
            target_path = os.path.join(templates_dir, item['target_filename'])
            desktop_src = os.path.join(desktop_dir, item['desktop_filename'])

            # Copy file from desktop if target doesn't exist or if desktop copy exists
            if os.path.exists(desktop_src):
                shutil.copy2(desktop_src, target_path)
                print(f"[MIGRATION] Copied '{item['desktop_filename']}' -> '{item['target_filename']}'")
            elif not os.path.exists(target_path):
                print(f"[MIGRATION] WARNING: Master template file '{desktop_src}' not found on Desktop!")

            # Check if an active template record already exists for this job_domain and duration
            existing_tmpl = DocumentTemplate.query.filter_by(
                template_type='offer_letter',
                job_domain=item['job_domain'],
                duration=item['duration'],
                is_active=True
            ).first()

            if not existing_tmpl:
                # Also check by name or file path
                fallback_tmpl = DocumentTemplate.query.filter_by(
                    job_domain=item['job_domain'],
                    duration=item['duration']
                ).first()

                if fallback_tmpl:
                    fallback_tmpl.name = item['template_name']
                    fallback_tmpl.template_type = 'offer_letter'
                    fallback_tmpl.filename = item['desktop_filename']
                    fallback_tmpl.file_path = target_path
                    fallback_tmpl.is_active = True
                    fallback_tmpl.created_by = item['created_by']
                    print(f"[MIGRATION] Updated and activated template for {item['job_domain']}.")
                else:
                    new_tmpl = DocumentTemplate(
                        template_type='offer_letter',
                        name=item['template_name'],
                        job_domain=item['job_domain'],
                        duration=item['duration'],
                        filename=item['desktop_filename'],
                        file_path=target_path,
                        is_active=True,
                        created_by=item['created_by']
                    )
                    db.session.add(new_tmpl)
                    print(f"[MIGRATION] Seeded active template record for {item['job_domain']} ({item['duration']}).")
            else:
                # Update file_path and filename in case it was updated
                existing_tmpl.file_path = target_path
                existing_tmpl.filename = item['desktop_filename']
                existing_tmpl.name = item['template_name']
                print(f"[MIGRATION] Template for {item['job_domain']} is already active.")

        # If there is an old legacy offer_letter with no job_domain (like ID 1), deactivate it
        legacy_tmpl = DocumentTemplate.query.filter_by(
            template_type='offer_letter',
            job_domain=None,
            is_active=True
        ).all()
        for lt in legacy_tmpl:
            lt.is_active = False
            print(f"[MIGRATION] Deactivated legacy unmapped offer_letter template ID {lt.id}.")

        db.session.commit()
        print("[MIGRATION] SUCCESS: Role/Job Based Offer Letter Template migration completed successfully.")


if __name__ == '__main__':
    run_migration()
