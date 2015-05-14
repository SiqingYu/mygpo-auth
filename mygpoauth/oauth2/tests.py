import urllib.parse
import uuid
import json

from django.test import TestCase, Client
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User

from mygpoauth.applications.models import Application
from mygpoauth.authorization.models import Authorization


class OAuthTestBase(TestCase):
    """ Provides test data for OAuth tests """

    def setUp(self):
        self.app = Application.objects.create(
            name='Test',
            redirect_url='https://example.com/test?test=true',
        )
        self.user = User.objects.create(
            username='username',
            email='user@example.com',
        )
        self.client = Client()

    def tearDown(self):
        Authorization.objects.filter(application=self.app).delete()
        self.app.delete()
        self.user.delete()


class OAuth2Flow(OAuthTestBase):
    """ Test the OAuth flow """

    def test_login(self):
        """ Test a successful login """
        auth_url = reverse('oauth2:authorize')

        query = urllib.parse.urlencode([
            ('client_id', self.app.client_id),
            ('response_type', 'code'),
            ('state', 'some_state'),
            ('scope', 'subscriptions apps:get'),
        ])

        # Verify that the Authorization server redirects back correctly
        response = self.client.get(auth_url + '?' + query, follow=False)
        self.assertEquals(response.status_code, 302)

        redir_url = response['Location']
        urlparts = urllib.parse.urlsplit(redir_url)
        scheme, netloc, path, query, fragment = urlparts
        self.assertEquals(scheme, 'https')
        self.assertEquals(netloc, 'example.com')
        self.assertEquals(path, '/test')
        self.assertEquals(fragment, '')

        queries = urllib.parse.parse_qs(query)
        self.assertEquals(queries['test'], ['true'],)
        self.assertEquals(queries['state'], ['some_state'])
        self.assertIn('code', queries.keys())
        self.assertEquals(len(queries['code']), 1)

        code = queries['code'][0]

        # Request access token from authorization_code
        req = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': self.app.redirect_url,
        }
        resp = self.token_request(req, True)

        # Request access token from refresh_token
        refresh_token = resp['refresh_token']
        req = {
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
        }
        resp = self.token_request(req, False)  # no real scopes provided yet

    def token_request(self, req, validate_scopes):
        """ Carry out (and verify) a successful token request """
        token_url = reverse('oauth2:token')
        response = self.client.post(
            token_url,
            urllib.parse.urlencode(req),
            content_type='application/x-www-form-urlencoded',
            HTTP_AUTHORIZATION=app_auth(self.app),
        )

        self.assertEquals(response.status_code, 200, response.content)
        resp = json.loads(response.content.decode('ascii'))
        self.assertIn('refresh_token', resp)
        self.assertEquals(resp['token_type'], 'Bearer')
        self.assertIn('access_token', resp)

        # from http://tools.ietf.org/html/rfc6749#section-5.1
        # The authorization server MUST include the HTTP "Cache-Control"
        # response header field [RFC2616] with a value of "no-store" in any
        # response containing tokens, credentials, or other sensitive
        # information, as well as the "Pragma" response header field [RFC2616]
        # with a value of "no-cache".
        self.assertEquals(response['Cache-Control'], 'no-store')
        self.assertEquals(response['Pragma'], 'no-cache')

        if validate_scopes:
            self.assertEquals(set(resp['scope'].split()),
                              {'subscriptions', 'apps:get'})
        self.assertIn('expires_in', resp)
        return resp

    def test_cors(self):
        """ Test CORS headers """
        token_url = reverse('oauth2:token')
        response = self.client.options(token_url)
        self.assertEqual(response['Access-Control-Allow-Origin'], '*')


class InvalidOAuth2Flow(OAuthTestBase):
    """ Test various error cases during the OAuth flow """

    def test_missing_token_auth(self):
        """ Test missing Basic Auth for Token Endpoint """
        app = Application(client_id='unknown', client_secret='unknown')
        resp = self._do_invalid_token_request({}, 401, 'invalid_client',
                                              auth=app_auth(app))
        self.assertTrue(resp['WWW-Authenticate'].startswith('Basic realm="'))

    def test_unknown_client_token_auth(self):
        """ Unknown client when authenticating for Token Endpoint """
        resp = self._do_invalid_token_request({}, 401, 'invalid_client',
                                              auth='')
        self.assertTrue(resp['WWW-Authenticate'].startswith('Basic realm="'))

    def test_invalid_grant_type(self):
        """ Invalid grant type: 400, error = unsupported_grant_type """
        req = {
            'grant_type': 'new_fancy_grant',
        }
        self._do_invalid_token_request(req, 400, 'unsupported_grant_type')

    def test_missing_grant_type(self):
        """ No grant_type results in 400 w/ error = unsupported_grant_type """
        req = {
            'asdf': 'test',
        }
        self._do_invalid_token_request(req, 400, 'unsupported_grant_type')

    def test_missing_grant(self):
        """ No grant results in 400 w/ error = invalid_request """
        req = {
            'grant_type': 'authorization_code',
        }
        self._do_invalid_token_request(req, 400, 'invalid_request')

    def test_invalid_grant(self):
        """ The auth code is not a valid UUID

        This is not a requirement by the spec, but by the implementation. This
        should be treated as if the auth code would not exist """

        req = {
            'grant_type': 'authorization_code',
            'code': 'some_invalid_code',
            'redirect_uri': self.app.redirect_url,
        }
        self._do_invalid_token_request(req, 400, 'invalid_grant')

    def test_noexisting_grant(self):
        """ The auth code is a valid UUID but does not exist """
        req = {
            'grant_type': 'authorization_code',
            'code': uuid.uuid4().hex,
            'redirect_uri': self.app.redirect_url,
        }
        self._do_invalid_token_request(req, 400, 'invalid_grant')

    def test_invalid_scope(self):
        """ Test a request for aninvalid scope """
        self._do_invalid_auth_request(scope='invalid scope',
                                      error='invalid_scope')

    def test_invalid_response_type(self):
        self._do_invalid_auth_request(response_type='magic_response',
                                      error='unsupported_response_type')

    def _do_invalid_auth_request(self, response_type='code', scope='',
                                 status=400, error=''):
        auth_url = reverse('oauth2:authorize')

        query = urllib.parse.urlencode([
            ('client_id', self.app.client_id),
            ('response_type', response_type),
            ('state', 'some_state'),
            ('scope', scope),
        ])

        # Verify that the Authorization server redirects back correctly
        response = self.client.get(auth_url + '?' + query, follow=False)

        self.assertEquals(response.status_code, status)
        resp = json.loads(response.content.decode('ascii'))
        self.assertEquals(resp['error'], error)
        return response

    def _do_invalid_token_request(self, req, status, error, auth=None):
        """ Performs an invalid token requests and verifies the result

        If auth is None, the default (correct) authentication information is
        sent. If no authentication header should be sent, an empty string
        should be provided instead. """

        if auth is None:
            auth = app_auth(self.app)

        headers = {}

        if auth:
            headers['HTTP_AUTHORIZATION'] = auth

        token_url = reverse('oauth2:token')
        response = self.client.post(
            token_url,
            urllib.parse.urlencode(req),
            content_type='application/x-www-form-urlencoded',
            **headers
        )

        self.assertEquals(response.status_code, status)
        resp = json.loads(response.content.decode('ascii'))
        self.assertEquals(resp['error'], error)
        return response


def app_auth(app):
    return create_auth_string(app.client_id, app.client_secret)


def create_auth_string(username, password):
    import base64
    credentials = ("%s:%s" % (username, password)).encode('ascii')
    credentials = base64.b64encode(credentials).decode('ascii')
    auth_string = 'Basic %s' % credentials
    return auth_string
