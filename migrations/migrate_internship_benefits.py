import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db, InternshipBenefit
from services.internship_benefit_service import ensure_default_internship_benefits


def run_migration():
    """
    Safely creates the 'internship_benefits' table if it does not exist,
    and seeds default 1-Month and 3-Month benefits only if table is empty.
    DATA SAFETY: Additive-only, never drops tables or touches existing records.
    """
    config_name = os.environ.get('FLASK_CONFIG', 'development')
    app = create_app(config_name)

    with app.app_context():
        print("Starting Internship Benefits database migration...")
        
        # 1. Create table if missing (additive only)
        db.create_all()
        print("Ensured 'internship_benefits' table exists.")

        # 2. Seed defaults ONLY if empty
        ensure_default_internship_benefits()

        count = InternshipBenefit.query.count()
        print(f"Migration completed successfully. Active benefit configs in database: {count}")


if __name__ == '__main__':
    run_migration()
