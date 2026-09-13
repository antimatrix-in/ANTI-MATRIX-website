import unittest
from app import create_app
from models import db, JobPosting, JobApplication, Payment


class CareersFeeDisplayTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()
        # Ensure at least one active internship posting exists
        self.job = JobPosting.query.filter_by(employment_type='Internship').first()
        if not self.job:
            self.job = JobPosting(
                job_id='JB1001',
                job_code='JB1001',
                title='Software Development Intern',
                department='Engineering',
                location='Remote',
                employment_type='Internship',
                duration='1_month',
                short_description='Exciting full-stack development internship.',
                description='Work on real-world web applications.',
                is_active=True
            )
            db.session.add(self.job)
            db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def test_careers_page_displays_fee_without_gst(self):
        """Verify that /careers displays 'Fee: ₹199 / ₹399' and has no '+ 18% GST' or '(+ 18% GST)'."""
        res = self.client.get('/careers')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Required change verification
        self.assertIn('Fee: ₹199 / ₹399', html)
        self.assertIn('₹199 / ₹399', html)

        # Removed text verification
        self.assertNotIn('(+ 18% GST)', html)
        self.assertNotIn('+ 18% GST', html)

    def test_application_page_displays_fee_without_gst(self):
        """Verify that application pages display clean fees without GST text."""
        res = self.client.get(f'/careers/apply/{self.job.id}')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertNotIn('18% GST', html)
        self.assertNotIn('+ 18% GST', html)
        self.assertNotIn('(+ 18% GST)', html)
        self.assertIn('₹199', html)
        self.assertIn('₹399', html)


if __name__ == '__main__':
    unittest.main()
