import unittest
import uuid

from app import app
from database import db, User, GameType, GameSession, CognitiveScore
from routes import recompute_user_cognitive_scores


class CognitiveScoringRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app
        cls._created_game_ids = []
        with cls.app.app_context():
            cls.sequence_game = cls._ensure_game(
                slug='sequence-memory',
                name='Sequence Memory',
                cognitive_domain='working_memory',
            )
            cls.box_game = cls._ensure_game(
                slug='box-adding',
                name='Box Adding',
                cognitive_domain='attention',
            )

    @classmethod
    def _ensure_game(cls, slug, name, cognitive_domain):
        game = GameType.query.filter_by(slug=slug).first()
        if game:
            return game

        game = GameType(
            slug=slug,
            name=name,
            description='Regression test game type',
            cognitive_domain=cognitive_domain,
            icon='test',
            color='#000000',
            industry='General',
            access_level='free',
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
            username=f'reg_{suffix}',
            email=f'reg_{suffix}@example.com',
            is_admin=False,
        )
        self.user.set_password('password')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        CognitiveScore.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        GameSession.query.filter_by(user_id=self.user.id).delete(synchronize_session=False)
        User.query.filter_by(id=self.user.id).delete(synchronize_session=False)
        db.session.commit()
        self.ctx.pop()

    def _add_session(self, game_type_id, completed_level, normalized_signal):
        session = GameSession(
            user_id=self.user.id,
            game_type_id=game_type_id,
            rounds_completed=completed_level,
            raw_data={
                'normalization': {
                    'normalized_signal': float(normalized_signal),
                }
            },
        )
        db.session.add(session)
        db.session.commit()
        return session

    def _get_trait_score(self, domain):
        row = CognitiveScore.query.filter_by(user_id=self.user.id, domain=domain).first()
        return round(float(row.score), 2) if row else 0.0

    def test_peak_minus_two_retry_does_not_improve_trait_score(self):
        # Peak run.
        self._add_session(self.sequence_game.id, completed_level=10, normalized_signal=50)
        # High-signal retry far below peak should be ignored for trait recompute.
        self._add_session(self.sequence_game.id, completed_level=8, normalized_signal=100)

        state = recompute_user_cognitive_scores(self.user.id)
        db.session.commit()

        self.assertAlmostEqual(state['domain_scores']['working_memory'], 30.0, places=2)
        self.assertAlmostEqual(self._get_trait_score('working_memory'), 30.0, places=2)

    def test_peak_minus_one_retry_can_improve_trait_score(self):
        # Peak run.
        self._add_session(self.sequence_game.id, completed_level=10, normalized_signal=50)
        # Near-peak retry is allowed and can improve score via better normalized signal.
        self._add_session(self.sequence_game.id, completed_level=9, normalized_signal=100)

        state = recompute_user_cognitive_scores(self.user.id)
        db.session.commit()

        # 9 * 3.0 * 1.5 = 40.5
        self.assertAlmostEqual(state['domain_scores']['working_memory'], 40.5, places=2)
        self.assertAlmostEqual(self._get_trait_score('working_memory'), 40.5, places=2)

    def test_peak_minus_one_window_applies_per_game(self):
        # sequence-memory contributes working_memory and pattern/attention.
        self._add_session(self.sequence_game.id, completed_level=6, normalized_signal=50)
        self._add_session(self.sequence_game.id, completed_level=5, normalized_signal=100)
        self._add_session(self.sequence_game.id, completed_level=4, normalized_signal=100)  # should be ignored

        # box-adding contributes working_memory and attention with its own independent peak window.
        self._add_session(self.box_game.id, completed_level=4, normalized_signal=50)
        self._add_session(self.box_game.id, completed_level=3, normalized_signal=100)

        state = recompute_user_cognitive_scores(self.user.id)
        db.session.commit()

        # Per-domain score is max across games, not sum.
        # sequence-memory best WM: max(6*3*1.0, 5*3*1.5) = 22.5
        # box-adding best WM: max(4*2.5*1.0, 3*2.5*1.5) = 11.25
        # final WM should be 22.5
        self.assertAlmostEqual(state['domain_scores']['working_memory'], 22.5, places=2)
        self.assertAlmostEqual(self._get_trait_score('working_memory'), 22.5, places=2)


if __name__ == '__main__':
    unittest.main()
