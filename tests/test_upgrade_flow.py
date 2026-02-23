import re
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app import app
from database import db, User, GameSession, CognitiveScore, StripeWebhookEvent


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

class StripeWebhookLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

        self.original_billing_provider = app.config.get('BILLING_PROVIDER')
        self.original_stripe_secret = app.config.get('STRIPE_SECRET_KEY')
        self.original_stripe_webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET')
        app.config['BILLING_PROVIDER'] = 'stripe'
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_local'
        app.config['STRIPE_WEBHOOK_SECRET'] = 'whsec_test_local'

        suffix = uuid.uuid4().hex[:10]
        self.user = User(
            username=f'webhook_{suffix}',
            email=f'webhook_{suffix}@example.com',
            is_admin=False,
            is_premium=False,
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

        self.client = app.test_client()

    def tearDown(self):
        app.config['BILLING_PROVIDER'] = self.original_billing_provider
        app.config['STRIPE_SECRET_KEY'] = self.original_stripe_secret
        app.config['STRIPE_WEBHOOK_SECRET'] = self.original_stripe_webhook_secret

        StripeWebhookEvent.query.delete(synchronize_session=False)
        CognitiveScore.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _post_webhook(self, event):
        fake_signature_error = type('FakeSignatureVerificationError', (Exception,), {})
        fake_stripe = SimpleNamespace(
            api_key='',
            Webhook=SimpleNamespace(
                construct_event=lambda payload, sig_header, secret: event
            ),
            error=SimpleNamespace(SignatureVerificationError=fake_signature_error),
        )

        with patch.dict('sys.modules', {'stripe': fake_stripe}):
            return self.client.post(
                '/api/billing/stripe/webhook',
                data=b'{}',
                headers={'Stripe-Signature': 't=1,v1=test'},
            )

    def test_checkout_completed_grants_premium_and_stores_ids(self):
        event = {
            'id': f'evt_{uuid.uuid4().hex[:12]}',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'user_id': str(self.user.id)},
                    'client_reference_id': str(self.user.id),
                    'payment_status': 'paid',
                    'status': 'complete',
                    'customer': 'cus_test_1',
                    'subscription': 'sub_test_1',
                }
            },
        }

        response = self._post_webhook(event)
        self.assertEqual(response.status_code, 200)

        refreshed = db.session.get(User, self.user.id)
        self.assertTrue(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'active')
        self.assertEqual(refreshed.stripe_customer_id, 'cus_test_1')
        self.assertEqual(refreshed.stripe_subscription_id, 'sub_test_1')
        self.assertEqual(
            StripeWebhookEvent.query.filter_by(event_id=event['id']).count(),
            1,
        )

    def test_subscription_deleted_revokes_premium(self):
        self.user.is_premium = True
        self.user.billing_status = 'active'
        self.user.stripe_customer_id = 'cus_test_2'
        self.user.stripe_subscription_id = 'sub_test_2'
        db.session.commit()

        event = {
            'id': f'evt_{uuid.uuid4().hex[:12]}',
            'type': 'customer.subscription.deleted',
            'data': {
                'object': {
                    'id': 'sub_test_2',
                    'customer': 'cus_test_2',
                    'status': 'canceled',
                }
            },
        }

        response = self._post_webhook(event)
        self.assertEqual(response.status_code, 200)

        refreshed = db.session.get(User, self.user.id)
        self.assertFalse(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'canceled')

    def test_invoice_payment_failed_revokes_premium(self):
        self.user.is_premium = True
        self.user.billing_status = 'active'
        self.user.stripe_customer_id = 'cus_test_3'
        self.user.stripe_subscription_id = 'sub_test_3'
        db.session.commit()

        event = {
            'id': f'evt_{uuid.uuid4().hex[:12]}',
            'type': 'invoice.payment_failed',
            'data': {
                'object': {
                    'id': f'in_{uuid.uuid4().hex[:8]}',
                    'customer': 'cus_test_3',
                    'subscription': 'sub_test_3',
                }
            },
        }

        response = self._post_webhook(event)
        self.assertEqual(response.status_code, 200)

        refreshed = db.session.get(User, self.user.id)
        self.assertFalse(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'payment_failed')

    def test_webhook_event_idempotency_ignores_duplicate_event_id(self):
        event_id = f'evt_{uuid.uuid4().hex[:12]}'
        grant_event = {
            'id': event_id,
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'user_id': str(self.user.id)},
                    'payment_status': 'paid',
                    'status': 'complete',
                    'customer': 'cus_test_4',
                    'subscription': 'sub_test_4',
                }
            },
        }
        duplicate_event = {
            'id': event_id,
            'type': 'invoice.payment_failed',
            'data': {
                'object': {
                    'customer': 'cus_test_4',
                    'subscription': 'sub_test_4',
                }
            },
        }

        first_response = self._post_webhook(grant_event)
        self.assertEqual(first_response.status_code, 200)

        second_response = self._post_webhook(duplicate_event)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue((second_response.get_json() or {}).get('duplicate', False))

        refreshed = db.session.get(User, self.user.id)
        self.assertTrue(refreshed.is_premium)
        self.assertEqual(
            StripeWebhookEvent.query.filter_by(event_id=event_id).count(),
            1,
        )


if __name__ == '__main__':
    unittest.main()
