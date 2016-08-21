from django.test import TestCase, Client
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User

from mygpoauth.applications.models import Application


class RegistrationTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.app = Application.objects.create(
            name='Test App',
            client_id='test_app',
            website_url='http://www.app.com/',
        )

    def tearDown(self):
        User.objects.all().delete()
        self.app.delete()

    def test_access_registration_page(self):
        url = reverse('registration:register')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_register(self):
        url = reverse('registration:register')
        response = self.client.post(url, {
            'username': 'john',
            'email': 'john@example.com',
            'password': 'smith',
            'client_id': self.app.client_id,
        }, follow=False)

        # successful registration redirects to website url
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.app.website_url)

    def test_invalid_form(self):
        url = reverse('registration:register')
        response = self.client.post(url, {
            'username': 'john',
            'email': 'this-is-not-an-email-address',
            'password': 'smith',
            'client_id': self.app.client_id,
        }, follow=False)

        # registration form is shown again
        self.assertEqual(response.status_code, 400)

    def test_duplicate_case_insensitive_username(self):
        url = reverse('registration:register')
        response = self.client.post(url, {
            'username': 'john',
            'email': 'john@example.com',
            'password': 'smith',
            'client_id': self.app.client_id,
        }, follow=False)

        # successful registration redirects to website url
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.app.website_url)

        response = self.client.post(url, {
            'username': 'JOHN',
            'email': 'john@example.com',
            'password': 'smith',
            'client_id': self.app.client_id,
        }, follow=False)

        # duplicate username
        self.assertEqual(response.status_code, 400)
