import unittest
import uuid
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app import app
from database import db, User, GameType, GameSession
from routes import update_user_streak


class SessionPayloadValidationTests(unittest.TestCase):
    CSRF_TOKEN_PATTERN = re.compile(
        r'name="csrf_token"\s+value="([^"]+)"'
    )

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
        self.original_streak_timezone = self.app.config.get('STREAK_TIMEZONE')
        self.app.config['STREAK_TIMEZONE'] = 'UTC'

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
        self.csrf_token = self._fetch_csrf_token('/login')
        login_response = self.client.post(
            '/login',
            data={
                'username': self.user.username,
                'password': 'password',
                'csrf_token': self.csrf_token,
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)

    def tearDown(self):
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.app.config['STREAK_TIMEZONE'] = self.original_streak_timezone
        self.ctx.pop()

    def _start_free_session(self):
        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        return payload['session_id']

    def _csrf_headers(self):
        return {'X-CSRFToken': self.csrf_token}

    def _fetch_csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        match = self.CSRF_TOKEN_PATTERN.search(html)
        self.assertIsNotNone(match, msg=f'No CSRF token found on {path}')
        return match.group(1)

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
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('JSON object', (response.get_json() or {}).get('error', ''))

    def test_start_rejects_out_of_range_difficulty(self):
        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 99},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('difficulty', (response.get_json() or {}).get('error', ''))

    def test_start_rejects_missing_csrf_token(self):
        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
        )
        self.assertEqual(response.status_code, 400)

    def test_end_initializes_streak_on_first_completed_session(self):
        self.user.current_streak = 0
        self.user.longest_streak = 0
        self.user.last_played = None
        db.session.commit()

        session_id = self._start_free_session()
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('current_streak'), 1)
        self.assertEqual(payload.get('longest_streak'), 1)

        refreshed = db.session.get(User, self.user.id)
        self.assertEqual(refreshed.current_streak, 1)
        self.assertEqual(refreshed.longest_streak, 1)
        self.assertIsNotNone(refreshed.last_played)

    def test_end_same_day_keeps_streak_count(self):
        self.user.current_streak = 3
        self.user.longest_streak = 5
        self.user.last_played = datetime.utcnow()
        db.session.commit()

        session_id = self._start_free_session()
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('current_streak'), 3)
        self.assertEqual(payload.get('longest_streak'), 5)

    def test_end_next_day_increments_streak(self):
        self.user.current_streak = 3
        self.user.longest_streak = 4
        self.user.last_played = datetime.utcnow() - timedelta(days=1, minutes=5)
        db.session.commit()

        session_id = self._start_free_session()
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('current_streak'), 4)
        self.assertEqual(payload.get('longest_streak'), 4)

    def test_end_missed_day_resets_streak(self):
        self.user.current_streak = 6
        self.user.longest_streak = 7
        self.user.last_played = datetime.utcnow() - timedelta(days=3)
        db.session.commit()

        session_id = self._start_free_session()
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('current_streak'), 1)
        self.assertEqual(payload.get('longest_streak'), 7)

    def test_user_timezone_sync_accepts_valid_timezone(self):
        response = self.client.post(
            '/api/user/timezone',
            json={'timezone': 'UTC'},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('timezone'), 'UTC')

        refreshed = db.session.get(User, self.user.id)
        self.assertEqual(refreshed.timezone, 'UTC')

    def test_user_timezone_sync_rejects_invalid_timezone(self):
        response = self.client.post(
            '/api/user/timezone',
            json={'timezone': 'Not/ARealTimezone'},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json() or {}
        self.assertIn('timezone', payload.get('error', ''))

    def test_update_user_streak_prefers_user_timezone_over_app_timezone(self):
        self.app.config['STREAK_TIMEZONE'] = 'UTC'
        self.user.timezone = 'Pacific/Kiritimati'
        self.user.current_streak = 2
        self.user.longest_streak = 2
        self.user.last_played = datetime(2026, 1, 1, 23, 30, 0)
        db.session.commit()

        # In UTC this crosses into the next day, but in UTC+14 it does not.
        with patch('routes.ZoneInfo', return_value=timezone(timedelta(hours=14))):
            streak = update_user_streak(self.user, datetime(2026, 1, 2, 0, 30, 0))

        self.assertEqual(streak.get('current_streak'), 2)
        self.assertEqual(streak.get('longest_streak'), 2)

    def test_start_rate_limit_enforced(self):
        original_limit = self.app.config.get('RATE_LIMIT_SESSION_START')
        self.app.config['RATE_LIMIT_SESSION_START'] = '2 per minute'
        remote_addr = f'198.51.100.{int(uuid.uuid4().hex[:2], 16) % 200 + 1}'
        self.user.lives_remaining = 8
        self.user.lives_last_updated_at = datetime.utcnow()
        db.session.commit()

        try:
            for _ in range(2):
                response = self.client.post(
                    '/api/session/start',
                    json={'game_slug': self.free_slug, 'difficulty': 1},
                    headers=self._csrf_headers(),
                    environ_overrides={'REMOTE_ADDR': remote_addr},
                )
                self.assertEqual(response.status_code, 200)

            response = self.client.post(
                '/api/session/start',
                json={'game_slug': self.free_slug, 'difficulty': 1},
                headers=self._csrf_headers(),
                environ_overrides={'REMOTE_ADDR': remote_addr},
            )
            self.assertEqual(response.status_code, 429)
        finally:
            self.app.config['RATE_LIMIT_SESSION_START'] = original_limit

    def test_end_rate_limit_enforced(self):
        original_limit = self.app.config.get('RATE_LIMIT_SESSION_END')
        self.app.config['RATE_LIMIT_SESSION_END'] = '2 per minute'
        remote_addr = f'203.0.113.{int(uuid.uuid4().hex[:2], 16) % 200 + 1}'

        try:
            session_ids = []
            for _ in range(3):
                response = self.client.post(
                    '/api/session/start',
                    json={'game_slug': self.free_slug, 'difficulty': 1},
                    headers=self._csrf_headers(),
                    environ_overrides={'REMOTE_ADDR': f'198.18.0.{int(uuid.uuid4().hex[:2], 16) % 200 + 1}'},
                )
                self.assertEqual(response.status_code, 200)
                session_ids.append((response.get_json() or {}).get('session_id'))

            for session_id in session_ids[:2]:
                response = self.client.post(
                    f'/api/session/{session_id}/end',
                    json=self._valid_end_payload(),
                    headers=self._csrf_headers(),
                    environ_overrides={'REMOTE_ADDR': remote_addr},
                )
                self.assertEqual(response.status_code, 200)

            response = self.client.post(
                f'/api/session/{session_ids[2]}/end',
                json=self._valid_end_payload(),
                headers=self._csrf_headers(),
                environ_overrides={'REMOTE_ADDR': remote_addr},
            )
            self.assertEqual(response.status_code, 429)
        finally:
            self.app.config['RATE_LIMIT_SESSION_END'] = original_limit

    def test_start_consumes_one_life(self):
        self.user.lives_remaining = 8
        self.user.lives_last_updated_at = datetime.utcnow()
        db.session.commit()

        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json() or {}
        self.assertEqual(payload.get('life_cost'), 1)
        self.assertEqual(payload.get('lives_remaining'), 7)

        refreshed = db.session.get(User, self.user.id)
        self.assertEqual(refreshed.lives_remaining, 7)

    def test_start_from_full_sets_30_minute_refill_clock(self):
        self.user.lives_remaining = 8
        self.user.lives_last_updated_at = datetime.utcnow() - timedelta(hours=6)
        db.session.commit()

        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        payload = response.get_json() or {}
        self.assertEqual(payload.get('lives_remaining'), 7)
        seconds_until_next = int(payload.get('seconds_until_next_life') or 0)
        self.assertGreaterEqual(seconds_until_next, 1790)
        self.assertLessEqual(seconds_until_next, 1800)

    def test_start_rejects_when_no_lives_available(self):
        self.user.lives_remaining = 0
        self.user.lives_last_updated_at = datetime.utcnow()
        db.session.commit()

        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)
        payload = response.get_json() or {}
        self.assertIn('lives', payload.get('error', '').lower())
        self.assertEqual(payload.get('lives_remaining'), 0)

    def test_start_regenerates_life_after_30_minutes(self):
        self.user.lives_remaining = 0
        self.user.lives_last_updated_at = datetime.utcnow() - timedelta(minutes=31)
        db.session.commit()

        response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.free_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json() or {}
        self.assertEqual(payload.get('lives_remaining'), 0)

    def test_problems_page_shows_life_cost_column_for_authenticated_user(self):
        self.user.lives_remaining = 6
        self.user.lives_last_updated_at = datetime.utcnow()
        db.session.commit()

        response = self.client.get('/problems')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('<th>Status</th>', html)
        self.assertIn('<th>Cost</th>', html)
        self.assertIn('lives-row', html)
        self.assertIn('sigma-cost', html)
        self.assertIn('streak-popover', html)
        self.assertIn('streak-week-grid', html)

    def test_start_premium_gating_matches_end_premium_gating(self):
        premium_start = self.client.post(
            '/api/session/start',
            json={'game_slug': self.premium_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
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
            headers=self._csrf_headers(),
        )
        self.assertEqual(premium_end.status_code, 403)

    def test_start_and_end_allow_premium_user_on_premium_game(self):
        self.user.is_premium = True
        db.session.commit()

        start_response = self.client.post(
            '/api/session/start',
            json={'game_slug': self.premium_slug, 'difficulty': 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(start_response.status_code, 200)
        session_id = (start_response.get_json() or {}).get('session_id')
        self.assertIsNotNone(session_id)

        end_response = self.client.post(
            f'/api/session/{session_id}/end',
            json=self._valid_end_payload(),
            headers=self._csrf_headers(),
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
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('accuracy', (response.get_json() or {}).get('error', ''))

    def test_end_rejects_out_of_range_accuracy(self):
        session_id = self._start_free_session()
        payload = self._valid_end_payload()
        payload['accuracy'] = 1.2
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=payload,
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('accuracy', (response.get_json() or {}).get('error', ''))

    def test_end_accepts_null_avg_response_time(self):
        session_id = self._start_free_session()
        payload = self._valid_end_payload()
        payload['avg_response_time_ms'] = None

        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=payload,
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        session_row = db.session.get(GameSession, session_id)
        self.assertIsNone(session_row.avg_response_time_ms)
        self.assertEqual(session_row.score, payload['score'])
        self.assertEqual(session_row.rounds_completed, payload['rounds_completed'])

    def test_end_rewards_one_xp_per_score_point(self):
        self.user.total_xp = 5
        db.session.commit()

        session_id = self._start_free_session()
        payload = self._valid_end_payload()
        payload['score'] = 12
        response = self.client.post(
            f'/api/session/{session_id}/end',
            json=payload,
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json() or {}
        self.assertEqual(body.get('xp_earned'), 12)
        self.assertEqual(body.get('total_xp'), 17)

        refreshed = db.session.get(User, self.user.id)
        self.assertEqual(refreshed.total_xp, 17)


if __name__ == '__main__':
    unittest.main()
