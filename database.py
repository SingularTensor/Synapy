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
    stripe_customer_id = db.Column(db.String(255), unique=True, index=True)
    stripe_subscription_id = db.Column(db.String(255), unique=True, index=True)
    billing_status = db.Column(db.String(32), default='inactive', nullable=False, server_default=text("'inactive'"))
    lives_remaining = db.Column(db.Integer, default=8, nullable=False, server_default=text('8'))
    lives_last_updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    profile_public = db.Column(db.Boolean, default=False)

    total_xp = db.Column(db.Integer, default=0)
    current_streak = db.Column(db.Integer, default=0)
    longest_streak = db.Column(db.Integer, default=0)
    last_played = db.Column(db.DateTime)
    timezone = db.Column(db.String(64))

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


class StripeWebhookEvent(db.Model):
    __tablename__ = 'stripe_webhook_events'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    event_type = db.Column(db.String(120), nullable=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


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
    if 'stripe_customer_id' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(255)')
    if 'stripe_subscription_id' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(255)')
    if 'billing_status' not in user_columns:
        statements.append("ALTER TABLE users ADD COLUMN billing_status VARCHAR(32) NOT NULL DEFAULT 'inactive'")
    if 'lives_remaining' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN lives_remaining INTEGER NOT NULL DEFAULT 8')
    if 'lives_last_updated_at' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN lives_last_updated_at DATETIME')
        statements.append("UPDATE users SET lives_last_updated_at = CURRENT_TIMESTAMP WHERE lives_last_updated_at IS NULL")
    if 'timezone' not in user_columns:
        statements.append('ALTER TABLE users ADD COLUMN timezone VARCHAR(64)')

    if 'stripe_webhook_events' not in table_names:
        statements.append(
            '''
            CREATE TABLE stripe_webhook_events (
                id INTEGER PRIMARY KEY,
                event_id VARCHAR(255) NOT NULL UNIQUE,
                event_type VARCHAR(120) NOT NULL,
                processed_at DATETIME NOT NULL
            )
            '''
        )

    statements.append(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id '
        'ON users (stripe_customer_id)'
    )
    statements.append(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_subscription_id '
        'ON users (stripe_subscription_id)'
    )
    statements.append(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_stripe_webhook_events_event_id '
        'ON stripe_webhook_events (event_id)'
    )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
