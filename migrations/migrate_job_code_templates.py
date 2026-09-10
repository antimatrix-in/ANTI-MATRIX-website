import os
import sys
from sqlalchemy import text, inspect

# Add project root to sys.path
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app, db
from models import JobPosting, DocumentTemplate

def run_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        dialect_name = engine.dialect.name
        print(f"[*] Running database migration for dialect: {dialect_name}")

        with engine.connect() as conn:
            # 1. job_postings: Add job_code column if missing
            job_postings_cols = [c['name'] for c in inspector.get_columns('job_postings')]
            if 'job_code' not in job_postings_cols:
                print("[*] Adding 'job_code' column to job_postings...")
                if dialect_name == 'postgresql':
                    conn.execute(text("ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS job_code VARCHAR(20);"))
                else:
                    conn.execute(text("ALTER TABLE job_postings ADD COLUMN job_code VARCHAR(20);"))
                conn.commit()
                print("[+] 'job_code' column added to job_postings.")
            else:
                print("[=] 'job_code' column already exists on job_postings.")

            # 2. Populate job_code = job_id for existing records where job_code is NULL
            print("[*] Ensuring all job_postings have job_code populated...")
            conn.execute(text("UPDATE job_postings SET job_code = job_id WHERE job_code IS NULL AND job_id IS NOT NULL;"))
            conn.commit()

            # Ensure every job has a valid JB#### code
            jobs = JobPosting.query.order_by(JobPosting.id.asc()).all()
            used_codes = set()
            for j in jobs:
                code = (j.job_code or j.job_id or '').strip().upper()
                if code.startswith('JB') and len(code) == 6 and code[2:].isdigit():
                    used_codes.add(code)

            next_num = 1001
            for j in jobs:
                code = (j.job_code or j.job_id or '').strip().upper()
                if not (code.startswith('JB') and len(code) == 6 and code[2:].isdigit()):
                    while f"JB{next_num:04d}" in used_codes:
                        next_num += 1
                    code = f"JB{next_num:04d}"
                    used_codes.add(code)
                    print(f"[*] Assigning new Job Code {code} to Job ID={j.id} ('{j.title}')")
                    j.job_code = code
                    if not j.job_id:
                        j.job_id = code
                else:
                    j.job_code = code
                    if not j.job_id:
                        j.job_id = code
                print(f"[+] Job ID={j.id} | Code={j.job_code} | Title='{j.title}'")
            db.session.commit()

            # 3. Add UNIQUE indexes/constraints on job_postings(job_code) and job_postings(job_id)
            print("[*] Creating unique indexes on job_postings(job_code) and job_postings(job_id)...")
            if dialect_name == 'postgresql':
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_postings_job_code ON job_postings(job_code);"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_postings_job_id ON job_postings(job_id);"))
                conn.commit()
            else:
                # SQLite
                try:
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_postings_job_code ON job_postings(job_code);"))
                    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_postings_job_id ON job_postings(job_id);"))
                    conn.commit()
                except Exception as e:
                    print(f"Index notice: {e}")

            # 4. document_templates: Add job_posting_id, job_code, subject columns
            doc_cols = [c['name'] for c in inspector.get_columns('document_templates')]
            
            if 'job_posting_id' not in doc_cols:
                print("[*] Adding 'job_posting_id' column to document_templates...")
                if dialect_name == 'postgresql':
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN IF NOT EXISTS job_posting_id INTEGER REFERENCES job_postings(id) ON DELETE SET NULL;"))
                else:
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN job_posting_id INTEGER REFERENCES job_postings(id) ON DELETE SET NULL;"))
                conn.commit()
                print("[+] 'job_posting_id' added to document_templates.")
            else:
                print("[=] 'job_posting_id' already exists on document_templates.")

            if 'job_code' not in doc_cols:
                print("[*] Adding 'job_code' column to document_templates...")
                if dialect_name == 'postgresql':
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN IF NOT EXISTS job_code VARCHAR(20);"))
                else:
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN job_code VARCHAR(20);"))
                conn.commit()
                print("[+] 'job_code' added to document_templates.")
            else:
                print("[=] 'job_code' already exists on document_templates.")

            if 'subject' not in doc_cols:
                print("[*] Adding 'subject' column to document_templates...")
                if dialect_name == 'postgresql':
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN IF NOT EXISTS subject VARCHAR(255);"))
                else:
                    conn.execute(text("ALTER TABLE document_templates ADD COLUMN subject VARCHAR(255);"))
                conn.commit()
                print("[+] 'subject' added to document_templates.")
            else:
                print("[=] 'subject' already exists on document_templates.")

            # Create indexes on document_templates
            print("[*] Creating indexes on document_templates(job_posting_id, job_code)...")
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_templates_job_posting_id ON document_templates(job_posting_id);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_doc_templates_job_code ON document_templates(job_code);"))
                conn.commit()
            except Exception as e:
                print(f"Index notice: {e}")

        print("\n[SUCCESS] Migration completed successfully.")

if __name__ == '__main__':
    run_migration()
