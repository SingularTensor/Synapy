import re
import unittest
import uuid

from app import app
from database import db, User, GameSession, CognitiveScore


class UpgradeFlowTests(unittest.TestCase):
    CSRF_TOKEN_PATTERN = re.compile(
        r'name="csrf_token"\s+value="([^"]+)"'
    )

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

        self.original_billing_provider = app.config.get('BILLING_PROVIDER')
        app.config['BILLING_PROVIDER'] = 'dev'

        suffix = uuid.uuid4().hex[:10]
        self.user = User(
            username=f'upgrade_{suffix}',
            email=f'upgrade_{suffix}@example.com',
            is_admin=False,
            is_premium=False,
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

        self.client = app.test_client()

    def tearDown(self):
        app.config['BILLING_PROVIDER'] = self.original_billing_provider

        CognitiveScore.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _fetch_csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        match = self.CSRF_TOKEN_PATTERN.search(html)
        self.assertIsNotNone(match, msg=f'No CSRF token found on {path}')
        return match.group(1)

    def _login(self):
        csrf_token = self._fetch_csrf_token('/login')
        response = self.client.post(
            '/login',
            data={
                'username': self.user.username,
                'password': 'password',
                'csrf_token': csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def test_upgrade_requires_login(self):
        response = self.client.get('/upgrade', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_upgrade_checkout_grants_premium_in_dev_mode(self):
        self._login()
        csrf_token = self._fetch_csrf_token('/upgrade')
        response = self.client.post(
            '/upgrade/checkout',
            data={'csrf_token': csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        refreshed = db.session.get(User, self.user.id)
        self.assertTrue(refreshed.is_premium)

    def test_upgrade_checkout_rejects_missing_csrf_token(self):
        self._login()
        response = self.client.post(
            '/upgrade/checkout',
            data={},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        refreshed = db.session.get(User, self.user.id)
        self.assertFalse(refreshed.is_premium)


if __name__ == '__main__':
    unittest.main()
