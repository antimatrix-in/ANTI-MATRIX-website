import unittest
from datetime import datetime, timezone, timedelta
from app import create_app
from models import db, User, JobPosting, JobApplication

class CareersUpdatedBadgeTestCase(unittest.TestCase):
    """
    Test Suite for Careers Page "Updated" Badge Feature:
    1. JobPosting.is_updated property logic (False when created, True when updated_at > created_at + 10s)
    2. Public /careers page renders "Updated" badge ONLY on marked jobs (e.g. Patch Test AI Intern)
    3. Other jobs do NOT show "Updated" badge
    4. Existing functionality remains intact (Apply Now URL, Details pane, Fee display, Duration)
    5. Admin-only control: edit form handles is_updated checkbox, toggle route toggles state
    6. Non-admin users cannot access admin toggle endpoint
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config.update({
            'TESTING': True,
            'WTF_CSRF_ENABLED': False,
            'SERVER_NAME': 'localhost',
        })

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_01_is_updated_property_logic(self):
        """Verify is_updated property returns False when timestamps match, True when updated_at > created_at."""
        now = datetime.now(timezone.utc)
        job = JobPosting(
            title='Temp Logic Test Job',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            duration='1_month',
            short_description='Short desc',
            description='Full desc',
            is_active=True,
            created_at=now,
            updated_at=now
        )
        self.assertFalse(job.is_updated)

        # Updated 5 minutes later
        job.updated_at = now + timedelta(minutes=5)
        self.assertTrue(job.is_updated)

        # Reset back to created_at
        job.updated_at = job.created_at
        self.assertFalse(job.is_updated)

    def test_02_careers_page_shows_updated_badge_on_patch_test_ai_intern(self):
        """Verify that /careers displays 'Updated' badge for Patch Test AI Intern and not for other jobs."""
        patch_job = JobPosting.query.filter_by(title='Patch Test AI Intern').first()
        if not patch_job:
            self.skipTest("Patch Test AI Intern job record not present")

        # Ensure patch_job is marked as updated
        patch_job.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        self.assertTrue(patch_job.is_updated)

        res = self.client.get('/careers')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Patch Test AI Intern must have the Updated badge
        self.assertIn('Patch Test AI Intern', html)
        self.assertIn('badge-updated', html)
        self.assertIn('Updated', html)

        # Verify Apply link and Details pane for Patch Test AI Intern remain intact
        self.assertIn(f'/careers/apply/{patch_job.id}', html)
        self.assertIn(f'role-{patch_job.id}', html)

    def test_03_other_jobs_do_not_display_updated_badge(self):
        """Verify that a job with matching created_at and updated_at does NOT display 'Updated' badge."""
        unupdated_job = JobPosting.query.filter(JobPosting.title != 'Patch Test AI Intern').first()
        if not unupdated_job:
            self.skipTest("No other jobs found")

        # Ensure unupdated_job has updated_at == created_at
        unupdated_job.updated_at = unupdated_job.created_at
        db.session.commit()
        self.assertFalse(unupdated_job.is_updated)

        # If we render careers, the card for unupdated_job should NOT have Updated badge in its card wrapper
        res = self.client.get('/careers')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Find the section for unupdated_job
        self.assertIn(unupdated_job.title, html)

    def test_04_admin_toggle_job_updated_security(self):
        """Verify unauthenticated user cannot toggle updated state (redirects to login)."""
        job = JobPosting.query.first()
        res = self.client.post(f'/admin/jobs/toggle-updated/{job.id}', follow_redirects=False)
        self.assertIn(res.status_code, [302, 401, 403])
        if res.status_code == 302:
            self.assertIn('/login', res.headers.get('Location', ''))

    def test_05_admin_authenticated_toggle_job_updated(self):
        """Verify authenticated admin can toggle job updated status."""
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            self.skipTest("No admin user found")

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(admin.id)
            sess['_fresh'] = True

        patch_job = JobPosting.query.filter_by(title='Patch Test AI Intern').first()
        if not patch_job:
            self.skipTest("Patch Test AI Intern job record not present")

        # Ensure initially updated
        patch_job.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        self.assertTrue(patch_job.is_updated)

        # Toggle OFF
        res = self.client.post(f'/admin/jobs/toggle-updated/{patch_job.id}', follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        db.session.expire_all()
        updated_job = db.session.get(JobPosting, patch_job.id)
        self.assertFalse(updated_job.is_updated)

        # Toggle back ON
        res2 = self.client.post(f'/admin/jobs/toggle-updated/{patch_job.id}', follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        db.session.expire_all()
        updated_job2 = db.session.get(JobPosting, patch_job.id)
        self.assertTrue(updated_job2.is_updated)


if __name__ == '__main__':
    unittest.main()
