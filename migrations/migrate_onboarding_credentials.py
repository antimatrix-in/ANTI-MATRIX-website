"""
Additive-Only Database Migration: Creates employee_onboarding_credentials table.
Preserves 100% of existing production rows, records, and IDs.
"""

import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db
from sqlalchemy import inspect, text

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger('migrate_onboarding_credentials')


def run_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine
        dialect_name = engine.dialect.name
        inspector = inspect(engine)

        logger.info(f"Target Database Dialect: {dialect_name}")

        # 1. Baseline Row Count Checks on Existing Production Tables
        baseline_tables = ['employees', 'job_applications', 'users', 'payments', 'applications', 'students']
        existing_tables = set(inspector.get_table_names())
        pre_counts = {}

        for tbl in baseline_tables:
            if tbl in existing_tables:
                count = db.session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                pre_counts[tbl] = count
                logger.info(f"[PRE-CHECK] Table '{tbl}': {count} records present.")

        # 2. Additive Table Creation
        table_name = 'employee_onboarding_credentials'
        if table_name in existing_tables:
            logger.info(f"Table '{table_name}' already exists. Skipping creation.")
        else:
            logger.info(f"Creating table '{table_name}'...")
            if dialect_name == 'postgresql':
                ddl = """
                CREATE TABLE IF NOT EXISTS employee_onboarding_credentials (
                    id SERIAL PRIMARY KEY,
                    employee_id VARCHAR(20) NOT NULL UNIQUE REFERENCES employees(employee_id) ON DELETE CASCADE,
                    temporary_password_encrypted TEXT,
                    temporary_password_hash VARCHAR(256) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    password_reset_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_employee_onboarding_credentials_emp_id 
                    ON employee_onboarding_credentials(employee_id);
                CREATE INDEX IF NOT EXISTS idx_employee_onboarding_credentials_status 
                    ON employee_onboarding_credentials(status);
                """
                db.session.execute(text(ddl))
                db.session.commit()
                logger.info("Table 'employee_onboarding_credentials' created successfully in PostgreSQL.")
            else:
                # SQLite fallback
                ddl = """
                CREATE TABLE IF NOT EXISTS employee_onboarding_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id VARCHAR(20) NOT NULL UNIQUE REFERENCES employees(employee_id) ON DELETE CASCADE,
                    temporary_password_encrypted TEXT,
                    temporary_password_hash VARCHAR(256) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
                    password_reset_at DATETIME,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_employee_onboarding_credentials_emp_id 
                    ON employee_onboarding_credentials(employee_id);
                CREATE INDEX IF NOT EXISTS idx_employee_onboarding_credentials_status 
                    ON employee_onboarding_credentials(status);
                """
                db.session.execute(text(ddl))
                db.session.commit()
                logger.info("Table 'employee_onboarding_credentials' created successfully in SQLite.")

        # 3. Post-Check Verification of Baseline Tables
        post_inspector = inspect(engine)
        post_tables = set(post_inspector.get_table_names())
        assert table_name in post_tables, f"Verification failed: '{table_name}' not found after migration."

        columns = {c['name']: str(c['type']) for c in post_inspector.get_columns(table_name)}
        logger.info(f"Verified columns in '{table_name}': {columns}")

        expected_columns = [
            'id', 'employee_id', 'temporary_password_encrypted', 'temporary_password_hash',
            'status', 'password_reset_at', 'created_at', 'updated_at'
        ]
        for col in expected_columns:
            assert col in columns, f"Missing expected column '{col}' in '{table_name}'."

        for tbl, pre_count in pre_counts.items():
            post_count = db.session.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
            logger.info(f"[POST-CHECK] Table '{tbl}': {post_count} records (Pre: {pre_count}).")
            assert post_count == pre_count, f"CRITICAL: Row count mismatch in '{tbl}'! Pre={pre_count}, Post={post_count}"

        logger.info("SUCCESS: Additive migration completed. Zero data modified or dropped.")


if __name__ == '__main__':
    run_migration()
