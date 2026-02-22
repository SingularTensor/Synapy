import unittest
import uuid

from app import app
from database import db, User, GameType, GameSession


class SessionPayloadValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls._created_game_ids = []
        cls.free_slug = f'api-free-{uuid.uuid4().hex[:10]}'
        cls.premium_slug = f'api-premium-{uuid.uuid4().hex[:10]}'

        with cls.app.app_context():
            cls._ensure_game(
                slug=cls.free_slug,
                name='API Validation Free',
                access_level='free',
            )
            cls._ensure_game(
                slug=cls.premium_slug,
                name='API Validation Premium',
                access_level='premium',
            )

    @classmethod
    def _ensure_game(cls, slug, name, access_level):
        game = GameType.query.filter_by(slug=slug).first()
        if game:
            return game

        game = GameType(
            slug=slug,
            name=name,
            description='Session payload validation test game',
            cognitive_domain='working_memory',
            icon='test',
            color='#111111',
            industry='General',
            access_level=access_level,
            is_active=True,
        )
        db.session.add(game)
        db.session.commit()
        cls._created_game_ids.append(game.id)
        return game

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            if cls._created_game_ids:
                ids = list(cls._created_game_ids)
                GameSession.query.filter(GameSession.game_type_id.in_(ids)).delete(synchronize_session=False)
                GameType.query.filter(GameType.id.in_(ids)).delete(synchronize_session=False)
                db.session.commit()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

        suffix = uuid.uuid4().hex[:10]
        self.user = User(
            username=f'api_{suffix}',
            email=f'api_{suffix}@example.com',
            is_admin=False,
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

        self.client = self.app.test_client()
        login_response = self.client.post(
            '/login',
            data={
                'username': self.user.username,
                'password': 'password',
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def tearDown(self):
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _start_free_session(self):
        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        return payload['session_id']

    def _valid_end_payload(self):
        return {
            'score': 7,
            'accuracy': 0.8,
            'rounds_completed': 7,
            'avg_response_time_ms': 450,
            'raw_data': {'response_samples': 9},
        }

    def test_start_rejects_non_object_payload(self):
        response = self.client.post(
            '/api/session/start',
            data='[]',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('JSON object', (response.get_json() or {}).get('error', ''))

    def test_start_rejects_out_of_range_difficulty(self):
        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 99},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('difficulty', (response.get_json() or {}).get('error', ''))

    def test_start_premium_gating_matches_end_premium_gating(self):
        premium_start = self.client.post(
            '/api/session/start',
            json={'game_slug': self.premium_slug, 'difficulty': 1},
        )
        self.assertEqual(premium_start.status_code, 403)

        premium_game = GameType.query.filter_by(slug=self.premium_slug).first()
        session = GameSession(
            user_id=self.user.id,
            game_type_id=premium_game.id,
            difficulty_level=1,
        )
        db.session.add(session)
        db.session.commit()

        premium_end = self.client.post(
            f'/api/session/{session.id}/end',
            json=self._valid_end_payload(),
        )
        self.assertEqual(premium_end.status_code, 403)

    def test_start_and_end_allow_premium_user_on_premium_game(self):
        self.user.is_premium = True
        db.session.commit()

        start_response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.premium_slug, 'difficulty': 1},
        )
        self.assertEqual(start_response.status_code, 200)
        session_id = (start_response.get_json() or {}).get('session_id')
        self.assertIsNotNone(session_id)

        end_response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
        )
        self.assertEqual(end_response.status_code, 200)

    def test_end_requires_expected_metrics(self):
        session_id = self._start_free_session()
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json={
                'score': 4,
                'rounds_completed': 4,
                'avg_response_time_ms': 500,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('accuracy', (response.get_json() or {}).get('error', ''))

    def test_end_rejects_out_of_range_accuracy(self):
        session_id = self._start_free_session()
        payload = self._valid_end_payload()
        payload['accuracy'] = 1.2
        response = self.client.post(f'/api/session/{session_id}/end', json=payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('accuracy', (response.get_json() or {}).get('error', ''))

    def test_end_accepts_null_avg_response_time(self):
        session_id = self._start_free_session()
        payload = self._valid_end_payload()
        payload['avg_response_time_ms'] = None

        response = self.client.post(f'/api/session/{session_id}/end', json=payload)
        self.assertEqual(response.status_code, 200)

        session_row = db.session.get(GameSession, session_id)
        self.assertIsNone(session_row.avg_response_time_ms)
        self.assertEqual(session_row.score, payload['score'])
        self.assertEqual(session_row.rounds_completed, payload['rounds_completed'])


if __name__ == '__main__':
    unittest.main()
