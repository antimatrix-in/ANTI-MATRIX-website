import os
import sys
from sqlalchemy import text, inspect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db


def run_migration():
    """
    Safely creates database unique indexes on job_applications for email and phone.
    DATA INTEGRITY:
    - Additive-only.
    - Inspects existing records first.
    - If duplicates exist, it logs them and preserves all records (never deletes).
    - If no duplicates exist, it applies the unique indexes.
    - Never drops tables or resets data.
    """
    config_name = os.environ.get('FLASK_CONFIG', 'default')
    app = create_app(config_name)

    with app.app_context():
        print("Starting Candidate Uniqueness database migration...")
        inspector = inspect(db.engine)
        dialect_is_sqlite = (db.engine.dialect.name == 'sqlite')

        if 'job_applications' not in inspector.get_table_names():
            print("Table 'job_applications' does not exist yet. Run db.create_all() first.")
            return

        with db.engine.connect() as conn:
            dup_email_res = conn.execute(text('''
                SELECT LOWER(TRIM(email)), count(*) FROM job_applications
                GROUP BY LOWER(TRIM(email)) HAVING count(*) > 1
            ''')).fetchall()
            dup_phone_res = conn.execute(text('''
                SELECT TRIM(phone), count(*) FROM job_applications
                GROUP BY TRIM(phone) HAVING count(*) > 1
            ''')).fetchall()

            if dup_email_res:
                print(f"[WARNING] Existing duplicate emails detected: {dup_email_res}. Preserving all records and skipping unique email index.")
            else:
                if dialect_is_sqlite:
                    conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_email ON job_applications (email)'))
                else:
                    conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_email ON job_applications (LOWER(TRIM(email)))'))
                print("[SUCCESS] Unique index on candidate email created or verified.")

            if dup_phone_res:
                print(f"[WARNING] Existing duplicate phones detected: {dup_phone_res}. Preserving all records and skipping unique phone index.")
            else:
                conn.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_phone ON job_applications (phone)'))
                print("[SUCCESS] Unique index on candidate phone created or verified.")

            conn.commit()

        print("Candidate Uniqueness migration completed safely.")


if __name__ == '__main__':
    run_migration()
