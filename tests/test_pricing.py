import unittest
from app import create_app, db
from models import User


class PricingRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_unauthenticated_pricing_locked(self):
        """Unauthenticated visitor should see the locked gate with Google/Email sign-in and INR preview."""
        response = self.client.get('/pricing')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Sign in to View Pricing & Packages', html)
        self.assertIn('Continue with Google', html)
        self.assertIn('Sign In with Email', html)
        self.assertIn('4,999', html)
        self.assertIn('14,999', html)
        self.assertIn('29,999', html)

    def test_authenticated_pricing_view_pdf_revisions(self):
        """Authenticated user should see the full revised PDF pricing packages, matrix, and add-ons in INR."""
        user = User.query.filter_by(role='admin').first()
        if not user:
            user = User(name='Test User', email='test_pricing@antimatrix.ai', role='member')
            user.set_password('TestPass123!')
            db.session.add(user)
            db.session.commit()

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

        response = self.client.get('/pricing')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        # 1. Packages & Prices
        self.assertIn('Standard Package', html)
        self.assertIn('4,999', html)
        self.assertIn('onwards', html)
        self.assertIn('Professional Package', html)
        self.assertIn('14,999', html)
        self.assertIn('Pro Package', html)
        self.assertIn('29,999', html)

        # 2. Key PDF Features & Transparency
        self.assertIn('Single Web Page', html)
        self.assertIn('Advanced Competitor SEO', html)
        self.assertIn('Appointment Booking', html)
        self.assertIn('Admin Dashboard', html)
        self.assertIn('Central Database', html)

        # 3. PDF Add-ons Catalog & Comparisons
        self.assertIn('Package Comparison at a Glance', html)
        self.assertIn('Add-Ons that Turn Your Site into a Sales Engine', html)
        self.assertIn('Who Should Choose Which?', html)
        self.assertIn('Never lead with price', html)


if __name__ == '__main__':
    unittest.main()
