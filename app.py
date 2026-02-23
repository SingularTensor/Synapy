from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from database import db, User
from datetime import timedelta
import os

load_dotenv()


def env_bool(var_name, default=False):
    value = os.environ.get(var_name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_int(var_name, default):
    value = os.environ.get(var_name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


app = Flask(__name__)
app_env = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'development')).strip().lower()
is_production = app_env in {'production', 'prod'}

app.config['APP_ENV'] = app_env
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///synapy.db')
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    if is_production:
        raise RuntimeError('SECRET_KEY must be set when APP_ENV=production')
    secret_key = os.urandom(24)
app.config['SECRET_KEY'] = secret_key

app.config['DEBUG'] = env_bool('DEBUG', default=not is_production)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = env_bool('SESSION_COOKIE_SECURE', default=is_production)
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = env_bool('REMEMBER_COOKIE_SECURE', default=is_production)
app.config['PREFERRED_URL_SCHEME'] = os.environ.get(
    'PREFERRED_URL_SCHEME',
    'https' if is_production else 'http',
)
app.config['WTF_CSRF_SSL_STRICT'] = env_bool('WTF_CSRF_SSL_STRICT', default=is_production)
app.config['WTF_CSRF_TIME_LIMIT'] = env_int('WTF_CSRF_TIME_LIMIT_SECONDS', 3600)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(
    minutes=env_int('SESSION_LIFETIME_MINUTES', 10080)
)

app.config['RATE_LIMIT_ENABLED'] = env_bool('RATE_LIMIT_ENABLED', default=True)
app.config['RATE_LIMIT_LOGIN'] = os.environ.get(
    'RATE_LIMIT_LOGIN',
    '20 per minute' if is_production else '200 per minute',
)
app.config['RATE_LIMIT_REGISTER'] = os.environ.get(
    'RATE_LIMIT_REGISTER',
    '10 per minute' if is_production else '100 per minute',
)
app.config['RATE_LIMIT_ADMIN_MUTATIONS'] = os.environ.get(
    'RATE_LIMIT_ADMIN_MUTATIONS',
    '30 per minute' if is_production else '300 per minute',
)
app.config['RATE_LIMIT_UPGRADE_CHECKOUT'] = os.environ.get(
    'RATE_LIMIT_UPGRADE_CHECKOUT',
    '10 per minute' if is_production else '100 per minute',
)
app.config['BILLING_PROVIDER'] = os.environ.get('BILLING_PROVIDER', 'dev').strip().lower()
app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY', '')
app.config['STRIPE_PRICE_ID'] = os.environ.get('STRIPE_PRICE_ID', '')
app.config['STRIPE_WEBHOOK_SECRET'] = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

db.init_app(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    enabled=app.config['RATE_LIMIT_ENABLED'],
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
    strategy=os.environ.get('RATELIMIT_STRATEGY', 'fixed-window'),
    headers_enabled=True,
)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

from routes import *

if __name__ == '__main__':
    app.run(
        debug=app.config['DEBUG'],
        host=os.environ.get('HOST', '0.0.0.0'),
        port=env_int('PORT', 5000),
    )
