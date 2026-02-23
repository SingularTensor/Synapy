import unittest
import uuid
import re

from app import app
from database import db, User, GameSession, CognitiveScore, StripeWebhookEvent


class AdminPremiumControlsTests(unittest.TestCase):
    CSRF_TOKEN_PATTERN = re.compile(
        r'name="csrf_token"\s+value="([^"]+)"'
    )

    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

        suffix = uuid.uuid4().hex[:10]
        self.admin_user = User(
            username=f'admin_{suffix}',
            email=f'admin_{suffix}@example.com',
            is_admin=True,
            is_premium=False,
        )
        self.admin_user.set_password('password')

        self.regular_user = User(
            username=f'user_{suffix}',
            email=f'user_{suffix}@example.com',
            is_admin=False,
            is_premium=False,
        )
        self.regular_user.set_password('password')

        self.non_admin_user = User(
            username=f'member_{suffix}',
            email=f'member_{suffix}@example.com',
            is_admin=False,
            is_premium=False,
        )
        self.non_admin_user.set_password('password')

        db.session.add_all([self.admin_user, self.regular_user, self.non_admin_user])
        db.session.commit()

        self.client = app.test_client()
        self.csrf_token = self._fetch_csrf_token('/login')

    def tearDown(self):
        user_ids = [self.admin_user.id, self.regular_user.id, self.non_admin_user.id]
        StripeWebhookEvent.query.delete(synchronize_session=False)
        CognitiveScore.query.filter(CognitiveScore.user_id.in_(user_ids)).delete(synchronize_session=False)
        GameSession.query.filter(GameSession.user_id.in_(user_ids)).delete(synchronize_session=False)
        User.query.filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _login(self, username):
        response = self.client.post(
            '/login',
            data={
                'username': username,
                'password': 'password',
                'csrf_token': self.csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

    def _fetch_csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        match = self.CSRF_TOKEN_PATTERN.search(html)
        self.assertIsNotNone(match, msg=f'No CSRF token found on {path}')
        return match.group(1)

    def test_non_admin_cannot_update_premium(self):
        self._login(self.non_admin_user.username)
        response = self.client.post(
            f'/admin/users/{self.regular_user.id}/premium',
            data={'is_premium': 'true', 'csrf_token': self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

        refreshed = db.session.get(User, self.regular_user.id)
        self.assertFalse(refreshed.is_premium)

    def test_admin_can_grant_and_revoke_premium(self):
        self._login(self.admin_user.username)

        grant_response = self.client.post(
            f'/admin/users/{self.regular_user.id}/premium',
            data={'is_premium': 'true', 'csrf_token': self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(grant_response.status_code, 302)
        self.assertTrue(db.session.get(User, self.regular_user.id).is_premium)

        revoke_response = self.client.post(
            f'/admin/users/{self.regular_user.id}/premium',
            data={'is_premium': 'false', 'csrf_token': self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(revoke_response.status_code, 302)
        self.assertFalse(db.session.get(User, self.regular_user.id).is_premium)

    def test_admin_route_rejects_invalid_premium_flag(self):
        self._login(self.admin_user.username)
        response = self.client.post(
            f'/admin/users/{self.regular_user.id}/premium',
            data={'is_premium': 'maybe', 'csrf_token': self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(db.session.get(User, self.regular_user.id).is_premium)

    def test_admin_route_rejects_missing_csrf_token(self):
        self._login(self.admin_user.username)
        response = self.client.post(
            f'/admin/users/{self.regular_user.id}/premium',
            data={'is_premium': 'true'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(db.session.get(User, self.regular_user.id).is_premium)

    def test_admin_panel_shows_billing_diagnostics(self):
        self._login(self.admin_user.username)

        self.regular_user.billing_status = 'active'
        self.regular_user.stripe_customer_id = 'cus_diag_test'
        self.regular_user.stripe_subscription_id = 'sub_diag_test'
        db.session.add(
            StripeWebhookEvent(
                event_id='evt_diag_test',
                event_type='checkout.session.completed',
            )
        )
        db.session.commit()

        response = self.client.get('/admin')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Billing Diagnostics', html)
        self.assertIn('active', html)
        self.assertIn('cus_diag_test', html)
        self.assertIn('sub_diag_test', html)
        self.assertIn('evt_diag_test', html)


if __name__ == '__main__':
    unittest.main()
