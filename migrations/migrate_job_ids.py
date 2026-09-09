"""
Migration: Add job_id column to job_postings and assign unique JB#### IDs.
- Preserves all existing jobs (no delete, no recreate, no PK changes).
- Assigns JB1234 to AI & ML job (AI Research Intern, ID 126).
- Assigns JB1001 to Frontend Engineer Intern (ID 125).
- Ensures uniqueness across all jobs.
"""
import sys
import os

# Add root directory to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from models import db
from models.job import JobPosting
from sqlalchemy import text, inspect


def run_migration():
    app = create_app()
    with app.app_context():
        print("Starting Job ID migration...")
        engine = db.engine
        inspector = inspect(engine)

        columns = [c['name'] for c in inspector.get_columns('job_postings')]
        print(f"Existing columns in job_postings: {columns}")

        if 'job_id' not in columns:
            print("Adding 'job_id' column to 'job_postings' table...")
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE job_postings ADD COLUMN job_id VARCHAR(20);"))
                conn.commit()
            print("Column 'job_id' successfully added.")
        else:
            print("Column 'job_id' already exists.")

        # Query all existing jobs
        jobs = JobPosting.query.order_by(JobPosting.id.asc()).all()
        print(f"Found {len(jobs)} existing job(s) in database.")

        used_ids = {j.job_id.upper() for j in jobs if j.job_id}

        # Step 1: Assign AI & ML job (AI Research Intern, ID 126)
        ai_ml_job = next((j for j in jobs if 'AI' in (j.title or '').upper() or 'AI' in (j.department or '').upper() or j.id == 126), None)
        if ai_ml_job:
            if not ai_ml_job.job_id:
                target_id = 'JB1234'
                if target_id not in used_ids:
                    ai_ml_job.job_id = target_id
                    used_ids.add(target_id)
                    print(f"Assigned Job {ai_ml_job.id} ('{ai_ml_job.title}') -> Job ID: {target_id}")
                else:
                    new_id = JobPosting.generate_unique_job_id()
                    ai_ml_job.job_id = new_id
                    used_ids.add(new_id)
                    print(f"JB1234 was taken; Assigned Job {ai_ml_job.id} ('{ai_ml_job.title}') -> Job ID: {new_id}")
            else:
                print(f"Job {ai_ml_job.id} already has Job ID: {ai_ml_job.job_id}")

        # Step 2: Assign other existing jobs
        counter = 1001
        for job in jobs:
            if job.job_id:
                continue
            # Pick next available JB####
            while True:
                candidate = f"JB{counter:04d}"
                if candidate not in used_ids:
                    job.job_id = candidate
                    used_ids.add(candidate)
                    print(f"Assigned Job {job.id} ('{job.title}') -> Job ID: {candidate}")
                    break
                counter += 1

        db.session.commit()
        print("Job ID migration committed successfully.")

        # Verification print
        print("\nCurrent Jobs in Database:")
        all_jobs = JobPosting.query.order_by(JobPosting.id.asc()).all()
        for j in all_jobs:
            print(f"  [ID: {j.id}] Job ID: {j.job_id} | Title: {j.title} | Dept: {j.department} | Duration: {j.duration}")


if __name__ == '__main__':
    run_migration()
