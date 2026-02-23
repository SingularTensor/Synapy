import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app import app
from database import db, User, GameSession, CognitiveScore


class FakeInvalidRequestError(Exception):
    pass


class FakeSubscriptionAPI:
    def __init__(self, *, retrieve_map=None, list_map=None):
        self.retrieve_map = retrieve_map or {}
        self.list_map = list_map or {}

    def retrieve(self, subscription_id):
        subscription = self.retrieve_map.get(subscription_id)
        if subscription is None:
            raise FakeInvalidRequestError(f"No such subscription: '{subscription_id}'")
        return subscription

    def list(self, customer=None, status=None, limit=None):
        return {'data': self.list_map.get(customer, [])}


class BillingReconcileCommandTests(unittest.TestCase):
    def setUp(self):
        self.ctx = app.app_context()
        self.ctx.push()

        self.original_provider = app.config.get('BILLING_PROVIDER')
        self.original_secret = app.config.get('STRIPE_SECRET_KEY')
        app.config['BILLING_PROVIDER'] = 'stripe'
        app.config['STRIPE_SECRET_KEY'] = 'sk_test_local'

        suffix = uuid.uuid4().hex[:10]
        self.user = User(
            username=f'reconcile_{suffix}',
            email=f'reconcile_{suffix}@example.com',
            is_admin=False,
            is_premium=False,
            billing_status='inactive',
            stripe_customer_id=None,
            stripe_subscription_id='sub_active_test',
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

        self.runner = app.test_cli_runner()

    def tearDown(self):
        app.config['BILLING_PROVIDER'] = self.original_provider
        app.config['STRIPE_SECRET_KEY'] = self.original_secret

        CognitiveScore.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _run_reconcile(self, fake_subscription_api, *extra_args):
        fake_stripe = SimpleNamespace(
            api_key='',
            Subscription=fake_subscription_api,
            error=SimpleNamespace(InvalidRequestError=FakeInvalidRequestError),
        )
        args = ['billing', 'reconcile', '--user-id', str(self.user.id), *extra_args]
        with patch.dict('sys.modules', {'stripe': fake_stripe}):
            return self.runner.invoke(args=args)

    def test_reconcile_updates_user_to_active_subscription(self):
        subscription_api = FakeSubscriptionAPI(
            retrieve_map={
                'sub_active_test': {
                    'id': 'sub_active_test',
                    'status': 'active',
                    'customer': 'cus_active_test',
                    'created': 123,
                }
            }
        )
        result = self._run_reconcile(subscription_api)
        self.assertEqual(result.exit_code, 0)
        self.assertIn('updated=1', result.output)

        refreshed = db.session.get(User, self.user.id)
        self.assertTrue(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'active')
        self.assertEqual(refreshed.stripe_customer_id, 'cus_active_test')
        self.assertEqual(refreshed.stripe_subscription_id, 'sub_active_test')

    def test_reconcile_downgrades_when_subscription_missing(self):
        self.user.is_premium = True
        self.user.billing_status = 'active'
        self.user.stripe_customer_id = None
        self.user.stripe_subscription_id = 'sub_missing_test'
        db.session.commit()

        subscription_api = FakeSubscriptionAPI(retrieve_map={})
        result = self._run_reconcile(subscription_api)
        self.assertEqual(result.exit_code, 0)
        self.assertIn('updated=1', result.output)

        refreshed = db.session.get(User, self.user.id)
        self.assertFalse(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'inactive')
        self.assertIsNone(refreshed.stripe_subscription_id)

    def test_reconcile_dry_run_does_not_persist(self):
        self.user.is_premium = True
        self.user.billing_status = 'active'
        self.user.stripe_subscription_id = 'sub_missing_test'
        db.session.commit()

        subscription_api = FakeSubscriptionAPI(retrieve_map={})
        result = self._run_reconcile(subscription_api, '--dry-run')
        self.assertEqual(result.exit_code, 0)
        self.assertIn('dry_run=true', result.output)

        refreshed = db.session.get(User, self.user.id)
        self.assertTrue(refreshed.is_premium)
        self.assertEqual(refreshed.billing_status, 'active')
        self.assertEqual(refreshed.stripe_subscription_id, 'sub_missing_test')


if __name__ == '__main__':
    unittest.main()
