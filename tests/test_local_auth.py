"""Run inside the app container: docker compose exec -T app python < tests/test_local_auth.py."""
import json
import re
import unittest
from unittest.mock import patch
from osvc_app import create_app

class LocalAuthTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True})
        self.client = self.app.test_client()

    def token(self, response=None):
        response = response or self.client.get('/login')
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text).group(1)

    def login(self, password='osvc', username='osvc'):
        return self.client.post('/login', data={'csrf_token': self.token(), 'username': username, 'password': password})

    def test_flow(self):
        self.assertEqual(self.client.get('/settings').location, '/login')
        with patch('osvc_app.routes.query', side_effect=AssertionError('Authentication used database')), patch('osvc_app.db.query', side_effect=AssertionError('Authentication used database')):
            bad = self.login('wrong')
            self.assertEqual(bad.status_code, 200)
            self.assertIn('Nesprávné uživatelské jméno nebo heslo.', bad.text)
            self.assertEqual(self.client.get('/settings').location, '/login')
            self.assertIn('Nesprávné', self.login(username='other').text)
            good = self.login()
            self.assertEqual(good.status_code, 302)
            cookie = good.headers['Set-Cookie']
            self.assertIn('HttpOnly', cookie)
            self.assertIn('SameSite=Lax', cookie)
        for path in [good.location, good.location, '/settings', '/documents', '/events']:
            self.assertEqual(self.client.get(path).status_code, 200, path)
        settings = self.client.get('/settings')
        self.assertNotIn('Ověřovací e-mail', settings.text)
        logout = self.client.post('/logout', data={'csrf_token': self.token(settings)})
        self.assertEqual(logout.location, '/login')
        self.assertIn('Max-Age=0', logout.headers['Set-Cookie'])
        self.assertEqual(self.client.get('/settings').location, '/login')

    def test_every_protected_route(self):
        token = self.token()
        checked = []
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint in ('static', 'main.login', 'obnova.zapomenute', 'obnova.nove') or rule.endpoint.startswith('pruvodce.'):
                continue   # zapomenuté heslo (1.0.3) je před přihlášením záměrně (tests/test_obnova_hesla.py); průvodce prvním spuštěním (I3) je jen pro instalaci bez účtu – s účtem nic nedělá (tests/test_i3_pruvodce.py)
            view = self.app.view_functions[rule.endpoint]
            self.assertTrue(hasattr(view, '__wrapped__'), rule.rule)
            path = re.sub(r'<(?:[^:>]+:)?([^>]+)>', '1', rule.rule)
            for method in sorted(rule.methods - {'HEAD', 'OPTIONS'}):
                token = self.token()
                response = self.client.open(path, method=method, data={'csrf_token': token})
                self.assertEqual(response.status_code, 302, (path, method))
                self.assertEqual(response.location, '/login')
                checked.append([method, rule.rule])
        print(json.dumps({'protected_route_methods': len(checked), 'routes': checked}, ensure_ascii=False))

    def test_removed_routes_and_csrf(self):
        for path in ['/forgot-password', '/reset-password', '/verify-email', '/settings/account/email', '/settings/account/email/resend', '/settings/account/username', '/settings/account/password']:
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post('/login', data={'username': 'osvc', 'password': 'osvc'}).status_code, 400)
        self.login()
        self.assertEqual(self.client.post('/logout').status_code, 400)

    def test_old_and_forged_sessions_rejected(self):
        with self.client.session_transaction() as sess:
            sess['user'] = 'osvc'
            sess['account_id'] = 1
            sess['auth_version'] = 1
        self.assertEqual(self.client.get('/settings').location, '/login')
        self.client.set_cookie('session', 'forged-cookie')
        self.assertEqual(self.client.get('/settings').location, '/login')

unittest.main(verbosity=2)
