from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect, text

db = SQLAlchemy()


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    is_admin = db.Column(db.Boolean, default=False)
    is_recruiter = db.Column(db.Boolean, default=False)
    is_premium = db.Column(db.Boolean, default=False, nullable=False, server_default=text('0'))
    profile_public = db.Column(db.Boolean, default=False)

    total_xp = db.Column(db.Integer, default=0)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_played = db.Column(db.DateTime)

    sessions = db.relationship('GameSession', backref='user', lazy=True)
    cognitive_scores = db.relationship('CognitiveScore', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class GameType(db.Model):
    __tablename__ = 'game_types'
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    cognitive_domain = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(50))
    color = db.Column(db.String(20))
    industry = db.Column(db.String(50), default='General')
    access_level = db.Column(db.String(20), default='free') # 'free' or 'premium'
    is_active = db.Column(db.Boolean, default=True)

    sessions = db.relationship('GameSession', backref='game_type', lazy=True)


COGNITIVE_DOMAINS = {
    'working_memory': {
        'name': 'Working Memory',
        'description': 'Hold and manipulate information in mind'
    },
    'processing_speed': {
        'name': 'Processing Speed',
        'description': 'Speed of cognitive operations'
    },
    'attention': {
        'name': 'Attention',
        'description': 'Focus and sustained concentration'
    },
    'pattern_recognition': {
        'name': 'Spatial Reasoning',
        'description': 'Interpret visual patterns and spatial relationships'
    },
    'mental_math': {
        'name': 'Mental Math',
        'description': 'Numerical calculation speed and accuracy'
    },
    'verbal_fluency': {
        'name': 'Verbal Comprehension',
        'description': 'Understand and interpret language in context'
    }
}


class GameSession(db.Model):
    __tablename__ = 'game_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    game_type_id = db.Column(db.Integer, db.ForeignKey('game_types.id'), nullable=False)

    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)
    duration_seconds = db.Column(db.Integer)

    score = db.Column(db.Integer, default=0)
    accuracy = db.Column(db.Float)
    avg_response_time_ms = db.Column(db.Integer)

    difficulty_level = db.Column(db.Integer, default=1)
    rounds_completed = db.Column(db.Integer, default=0)

    xp_earned = db.Column(db.Integer, default=0)
    raw_data = db.Column(db.JSON)


class CognitiveScore(db.Model):
    __tablename__ = 'cognitive_scores'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    domain = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Float, nullable=False)
    percentile = db.Column(db.Float)
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)
    session_count = db.Column(db.Integer, default=1)


class DailyChallenge(db.Model):
    __tablename__ = 'daily_challenges'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    game_type_id = db.Column(db.Integer, db.ForeignKey('game_types.id'), nullable=False)
    config = db.Column(db.JSON)

    game_type = db.relationship('GameType')


class Leaderboard(db.Model):
    __tablename__ = 'leaderboard'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    period = db.Column(db.String(20), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    total_xp = db.Column(db.Integer, default=0)
    rank = db.Column(db.Integer)

    user = db.relationship('User')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'period', 'period_start', name='_user_period_uc'),
    )


def ensure_runtime_schema_compatibility():
    """
    Apply minimal additive schema patches for local/dev environments that
    may run without a migration system.
    """
    engine = db.engine
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if 'users' not in table_names:
        return

    user_columns = {column['name'] for column in inspector.get_columns('users')}
    statements = []
    if 'is_premium' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN is_premium BOOLEAN NOT NULL DEFAULT 0')

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
