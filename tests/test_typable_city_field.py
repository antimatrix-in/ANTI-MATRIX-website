import io
import unittest
from app import create_app
from models import db, User, JobPosting, JobApplication


class TypableCityFieldTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Candidate user
        self.candidate = User(name='Pooja Candidate', email='pooja_city_test@antimatrix.ai', role='member', is_active=True)
        self.candidate.set_password('CityTestPass123!')
        db.session.add(self.candidate)

        # Internship Job
        self.job = JobPosting(
            job_code='JB1088',
            title='Full Stack Intern',
            department='Engineering',
            location='Remote',
            employment_type='Internship',
            salary='Performance Based',
            short_description='Full stack internship role.',
            description='Build web systems.',
            requirements='Python, Flask, HTML/CSS',
            responsibilities='Write code and review PRs',
            is_active=True
        )
        db.session.add(self.job)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def login_candidate(self):
        return self.client.post('/login', data={'email': self.candidate.email, 'password': 'CityTestPass123!'}, follow_redirects=True)

    def _get_valid_application_payload(self, state='Tamil Nadu', city='Chennai'):
        return {
            'first_name': 'Pooja',
            'last_name': 'Candidate',
            'email': self.candidate.email,
            'phone': '9876543210',
            'address': '123 Anna Salai',
            'state': state,
            'city': city,
            'pincode': '600001',
            'education_level': "Bachelor's Degree",
            'degree': 'B.Tech',
            'major': 'Computer Science',
            'graduation_year': '2025',
            'duration': '1_month',
            'resume': (io.BytesIO(b'%PDF-1.4 sample resume content'), 'resume.pdf'),
        }

    # ----------------------------------------------------------------------
    # 1. UI Verification: City is a text input, not a dropdown; State is dropdown
    # ----------------------------------------------------------------------
    def test_01_city_is_text_input_and_state_is_dropdown(self):
        self.login_candidate()
        res = self.client.get(f'/careers/apply/{self.job.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Confirm City is text input
        self.assertIn('<input type="text" id="city" name="city"', html)
        self.assertIn('placeholder="Enter your city"', html)
        self.assertNotIn('<select id="city"', html)
        self.assertNotIn('Select City</option>', html)

        # Confirm State remains a select dropdown
        self.assertIn('<select id="state" name="state"', html)
        self.assertIn('Tamil Nadu', html)

        # Confirm broken / obsolete city dropdown scripts are gone
        self.assertNotIn('handleStateChange', html)
        self.assertNotIn('populateCities', html)
        self.assertNotIn('stateCityMap', html)

    # ----------------------------------------------------------------------
    # 2. State: Tamil Nadu, City: Chennai -> Accepted and saved as Chennai
    # ----------------------------------------------------------------------
    def test_02_tamil_nadu_chennai_accepted(self):
        self.login_candidate()
        data = self._get_valid_application_payload(state='Tamil Nadu', city='Chennai')
        res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 302)
        self.assertIn('/careers/apply/review/', res.headers['Location'])

        app_rec = JobApplication.query.filter_by(job_id=self.job.id, email=self.candidate.email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.state, 'Tamil Nadu')
        self.assertEqual(app_rec.city, 'Chennai')

    # ----------------------------------------------------------------------
    # 3. State: Tamil Nadu, City: Coimbatore -> Accepted and saved as Coimbatore
    # ----------------------------------------------------------------------
    def test_03_tamil_nadu_coimbatore_accepted(self):
        self.login_candidate()
        data = self._get_valid_application_payload(state='Tamil Nadu', city='Coimbatore')
        res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 302)
        app_rec = JobApplication.query.filter_by(job_id=self.job.id, email=self.candidate.email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.city, 'Coimbatore')

    # ----------------------------------------------------------------------
    # 4. City left empty -> Rejected with validation error
    # ----------------------------------------------------------------------
    def test_04_empty_city_rejected(self):
        self.login_candidate()
        data = self._get_valid_application_payload(state='Tamil Nadu', city='')
        res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=True, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('City is required.', html)

        # Ensure no application created
        count = JobApplication.query.filter_by(job_id=self.job.id).count()
        self.assertEqual(count, 0)

    # ----------------------------------------------------------------------
    # 5. City with whitespace only -> Rejected with validation error
    # ----------------------------------------------------------------------
    def test_05_whitespace_only_city_rejected(self):
        self.login_candidate()
        data = self._get_valid_application_payload(state='Tamil Nadu', city='     ')
        res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=True, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('City is required.', html)

        count = JobApplication.query.filter_by(job_id=self.job.id).count()
        self.assertEqual(count, 0)

    # ----------------------------------------------------------------------
    # 6. City with leading/trailing whitespace -> Trimmed and saved as "Chennai"
    # ----------------------------------------------------------------------
    def test_06_whitespace_trimmed_before_saving(self):
        self.login_candidate()
        data = self._get_valid_application_payload(state='Tamil Nadu', city='  Chennai  ')
        res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')

        self.assertEqual(res.status_code, 302)
        app_rec = JobApplication.query.filter_by(job_id=self.job.id, email=self.candidate.email).first()
        self.assertIsNotNone(app_rec)
        self.assertEqual(app_rec.city, 'Chennai')

    # ----------------------------------------------------------------------
    # 7. City with spaces, hyphens, periods, apostrophes -> Accepted
    # ----------------------------------------------------------------------
    def test_07_special_character_city_names_accepted(self):
        self.login_candidate()
        test_cities = [
            ('Tamil Nadu', 'St. Thomas Mount'),
            ('Tamil Nadu', 'Dharapuram-South'),
            ('Delhi', 'New Delhi'),
            ('Kerala', "St. John's")
        ]

        for idx, (st, ct) in enumerate(test_cities):
            # Clean db applications
            JobApplication.query.filter_by(job_id=self.job.id).delete()
            db.session.commit()

            data = self._get_valid_application_payload(state=st, city=ct)
            res = self.client.post(f'/careers/apply/{self.job.id}', data=data, follow_redirects=False, content_type='multipart/form-data')
            self.assertEqual(res.status_code, 302, f"Failed for {st} - {ct}")

            app_rec = JobApplication.query.filter_by(job_id=self.job.id).first()
            self.assertIsNotNone(app_rec)
            self.assertEqual(app_rec.city, ct.strip())


if __name__ == '__main__':
    unittest.main()
