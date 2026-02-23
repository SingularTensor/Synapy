import math
import os
from functools import wraps
from flask import render_template, request, jsonify, redirect, url_for, flash, abort, current_app
from flask_login import login_user, logout_user, login_required, current_user

from app import app, limiter, csrf
from database import db, User, GameType, GameSession, CognitiveScore, COGNITIVE_DOMAINS

COGNITIVE_WEIGHT_VERSION = '2026-02-22-v4'
COGNITIVE_WEIGHT_TOTAL = 5.0
COGNITIVE_WEIGHT_MAX_PER_TRAIT = 3.0
NORMALIZATION_LEVEL_STEP = 10.0
MIN_POPULATION_SAMPLE_FOR_FULL_WEIGHT = 25
TRAIT_RETRY_WINDOW_BELOW_PEAK = 1
SESSION_DIFFICULTY_MIN = 1
SESSION_DIFFICULTY_MAX = 10
SESSION_SCORE_MAX = 1000000
SESSION_ROUNDS_COMPLETED_MAX = 1000000
SESSION_AVG_RESPONSE_TIME_MS_MAX = 600000

GAME_COGNITIVE_WEIGHTS = {
    # Total per-game budget: 5.0
    'sequence-memory': {
        'processing_speed': 0.0,
        'working_memory': 3.0,
        # Existing domain key used as spatial-reasoning proxy.
        'pattern_recognition': 1.0,
        'attention': 1.0,
        'verbal_fluency': 0.0,
    },
    # Total per-game budget: 5.0
    'box-adding': {
        'processing_speed': 0.0,
        'working_memory': 2.5,
        'pattern_recognition': 0.0,
        'attention': 2.5,
        'verbal_fluency': 0.0,
    },
    # Total per-game budget: 5.0
    'speed-dart': {
        'processing_speed': 2.5,
        'working_memory': 0.5,
        'pattern_recognition': 1.0,
        'attention': 1.0,
        'verbal_fluency': 0.0,
    },
    # Total per-game budget: 5.0
    'color-word': {
        'processing_speed': 1.6,
        'working_memory': 0.3,
        'pattern_recognition': 0.0,
        'attention': 2.1,
        'verbal_fluency': 1.0,
    },
}

GAME_BASELINE_LEVELS = {
    'sequence-memory': 4.0,
    'speed-dart': 5.0,
    'box-adding': 3.0,
    'color-word': 12.0,
}

MANAGED_COGNITIVE_DOMAINS = sorted({
    domain
    for per_game in GAME_COGNITIVE_WEIGHTS.values()
    for domain in per_game.keys()
})

def validate_game_cognitive_weights(weight_map):
    for game_slug, domain_weights in weight_map.items():
        if not domain_weights:
            raise ValueError(f'Game {game_slug} has no cognitive weights configured')

        unknown_domains = [domain for domain in domain_weights if domain not in COGNITIVE_DOMAINS]
        if unknown_domains:
            raise ValueError(f'Game {game_slug} has unknown domains: {unknown_domains}')

        values = [float(value) for value in domain_weights.values()]
        if any(value < 0 for value in values):
            raise ValueError(f'Game {game_slug} has negative trait weights')

        total = sum(values)
        if not math.isclose(total, COGNITIVE_WEIGHT_TOTAL, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(
                f'Game {game_slug} weights must sum to {COGNITIVE_WEIGHT_TOTAL}, got {total}'
            )

        if not any(math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-9) for value in values):
            raise ValueError(f'Game {game_slug} must include at least one zero-weight trait')

        if max(values) > COGNITIVE_WEIGHT_MAX_PER_TRAIT:
            raise ValueError(
                f'Game {game_slug} has a trait above max {COGNITIVE_WEIGHT_MAX_PER_TRAIT}'
            )

        baseline_level = GAME_BASELINE_LEVELS.get(game_slug)
        if baseline_level is None:
            raise ValueError(f'Game {game_slug} is missing a baseline level calibration')
        if float(baseline_level) < 0:
            raise ValueError(f'Game {game_slug} has invalid baseline level {baseline_level}')


validate_game_cognitive_weights(GAME_COGNITIVE_WEIGHTS)


def game_template_exists(game_slug):
    template_path = os.path.join(app.root_path, 'templates', 'games', f'{game_slug}.html')
    return os.path.exists(template_path)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def recruiter_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_recruiter:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


def user_has_premium_access(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_admin', False):
        return True
    # Premium flag is not yet migrated into the User model; default deny.
    return bool(getattr(user, 'is_premium', False))


def user_can_access_game(user, game_type):
    if not game_type:
        return False
    if game_type.access_level != 'premium':
        return True
    return user_has_premium_access(user)


def get_billing_provider():
    provider = (app.config.get('BILLING_PROVIDER') or 'dev').strip().lower()
    if provider in {'dev', 'stripe'}:
        return provider
    return 'dev'


def set_user_premium_state(user_id, is_premium):
    user = db.session.get(User, int(user_id))
    if user is None:
        return None
    user.is_premium = bool(is_premium)
    db.session.commit()
    return user


def _create_stripe_checkout_session(user):
    try:
        import stripe  # type: ignore
    except ImportError as exc:  # pragma: no cover - guarded by runtime config
        raise RuntimeError('Stripe SDK is not installed. Add `stripe` to requirements.') from exc

    stripe_secret_key = app.config.get('STRIPE_SECRET_KEY')
    stripe_price_id = app.config.get('STRIPE_PRICE_ID')
    if not stripe_secret_key or not stripe_price_id:
        raise RuntimeError('Stripe is not configured. Set STRIPE_SECRET_KEY and STRIPE_PRICE_ID.')

    stripe.api_key = stripe_secret_key
    success_url = url_for('upgrade_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}'
    cancel_url = url_for('upgrade_cancel', _external=True)

    return stripe.checkout.Session.create(
        mode='subscription',
        line_items=[{'price': stripe_price_id, 'quantity': 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=str(user.id),
        customer_email=user.email,
        metadata={'user_id': str(user.id)},
    )


def _extract_stripe_user_id(session_obj):
    metadata = session_obj.get('metadata') or {}
    user_id_raw = metadata.get('user_id') or session_obj.get('client_reference_id')
    try:
        return int(user_id_raw)
    except (TypeError, ValueError):
        return None


def _sync_stripe_checkout_session_for_current_user(session_id, expected_user_id):
    try:
        import stripe  # type: ignore
    except ImportError as exc:  # pragma: no cover - guarded by runtime config
        raise RuntimeError('Stripe SDK is not installed. Add `stripe` to requirements.') from exc

    stripe_secret_key = app.config.get('STRIPE_SECRET_KEY')
    if not stripe_secret_key:
        raise RuntimeError('Stripe is not configured. Set STRIPE_SECRET_KEY.')

    stripe.api_key = stripe_secret_key
    session_obj = stripe.checkout.Session.retrieve(session_id)

    session_user_id = _extract_stripe_user_id(session_obj)
    if session_user_id != int(expected_user_id):
        return False

    payment_status = (session_obj.get('payment_status') or '').lower()
    status = (session_obj.get('status') or '').lower()
    if payment_status not in {'paid', 'no_payment_required'} and status != 'complete':
        return False

    set_user_premium_state(expected_user_id, True)
    return True


def parse_int_payload_field(
    payload,
    field_name,
    *,
    required=True,
    default=None,
    min_value=None,
    max_value=None,
    allow_none=False,
):
    has_field = field_name in payload
    if not has_field:
        if required:
            raise ValueError(f'{field_name} is required')
        return default

    value = payload.get(field_name)
    if value is None:
        if allow_none:
            return None
        if required:
            raise ValueError(f'{field_name} cannot be null')
        return default

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field_name} must be an integer')
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f'{field_name} must be an integer')

    parsed_value = int(value)
    if min_value is not None and parsed_value < min_value:
        raise ValueError(f'{field_name} must be >= {min_value}')
    if max_value is not None and parsed_value > max_value:
        raise ValueError(f'{field_name} must be <= {max_value}')
    return parsed_value


def parse_float_payload_field(
    payload,
    field_name,
    *,
    required=True,
    default=None,
    min_value=None,
    max_value=None,
    allow_none=False,
):
    has_field = field_name in payload
    if not has_field:
        if required:
            raise ValueError(f'{field_name} is required')
        return default

    value = payload.get(field_name)
    if value is None:
        if allow_none:
            return None
        if required:
            raise ValueError(f'{field_name} cannot be null')
        return default

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{field_name} must be a number')

    parsed_value = float(value)
    if not math.isfinite(parsed_value):
        raise ValueError(f'{field_name} must be finite')
    if min_value is not None and parsed_value < min_value:
        raise ValueError(f'{field_name} must be >= {min_value}')
    if max_value is not None and parsed_value > max_value:
        raise ValueError(f'{field_name} must be <= {max_value}')
    return parsed_value


def validate_session_start_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object')

    game_slug = payload.get('game_slug')
    if not isinstance(game_slug, str) or not game_slug.strip():
        raise ValueError('game_slug must be a non-empty string')

    difficulty_level = parse_int_payload_field(
        payload,
        'difficulty',
        required=False,
        default=SESSION_DIFFICULTY_MIN,
        min_value=SESSION_DIFFICULTY_MIN,
        max_value=SESSION_DIFFICULTY_MAX,
    )

    return {
        'game_slug': game_slug.strip(),
        'difficulty_level': difficulty_level,
    }


def validate_session_end_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object')

    score = parse_int_payload_field(
        payload,
        'score',
        required=True,
        min_value=0,
        max_value=SESSION_SCORE_MAX,
    )
    accuracy = parse_float_payload_field(
        payload,
        'accuracy',
        required=True,
        min_value=0.0,
        max_value=1.0,
    )
    rounds_completed = parse_int_payload_field(
        payload,
        'rounds_completed',
        required=True,
        min_value=0,
        max_value=SESSION_ROUNDS_COMPLETED_MAX,
    )
    avg_response_time_ms = parse_int_payload_field(
        payload,
        'avg_response_time_ms',
        required=True,
        min_value=0,
        max_value=SESSION_AVG_RESPONSE_TIME_MS_MAX,
        allow_none=True,
    )

    incoming_raw_data = payload.get('raw_data')
    if incoming_raw_data is None:
        raw_data = {}
    elif isinstance(incoming_raw_data, dict):
        raw_data = dict(incoming_raw_data)
    else:
        raise ValueError('raw_data must be a JSON object when provided')

    return {
        'score': score,
        'accuracy': accuracy,
        'rounds_completed': rounds_completed,
        'avg_response_time_ms': avg_response_time_ms,
        'raw_data': raw_data,
    }


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/problems')
def problems():
    # Fetch all active games to display on the problems list
    game_types = GameType.query.filter_by(is_active=True).all()
    for game in game_types:
        game.is_coming_soon = not game_template_exists(game.slug)
    return render_template('problems.html', games=game_types)


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit(lambda: app.config['RATE_LIMIT_LOGIN'], methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('problems'))

    if request.method == 'POST':
        login_input = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=login_input).first()
        if not user:
            user = User.query.filter_by(email=login_input).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('problems'))

        flash('Invalid username/email or password')

    return render_template('login.html', mode='Login')


@app.route('/register', methods=['GET', 'POST'])
@limiter.limit(lambda: app.config['RATE_LIMIT_REGISTER'], methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('problems'))

    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Username already taken')
            return render_template('login.html', mode='Register')

        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return render_template('login.html', mode='Register')

        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for('problems'))

    return render_template('login.html', mode='Register')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    game_types = GameType.query.filter_by(is_active=True).all()
    recent_sessions = GameSession.query.filter_by(user_id=current_user.id)\
        .order_by(GameSession.started_at.desc()).limit(5).all()
    cognitive_scores = {s.domain: s for s in current_user.cognitive_scores}

    return render_template('dashboard.html',
                         game_types=game_types,
                         recent_sessions=recent_sessions,
                         cognitive_scores=cognitive_scores,
                         domains=COGNITIVE_DOMAINS)


@app.route('/upgrade')
@login_required
def upgrade():
    return render_template(
        'upgrade.html',
        is_premium=user_has_premium_access(current_user),
        billing_provider=get_billing_provider(),
    )


@app.route('/upgrade/checkout', methods=['POST'])
@login_required
@limiter.limit(lambda: app.config['RATE_LIMIT_UPGRADE_CHECKOUT'], methods=['POST'])
def start_upgrade_checkout():
    if user_has_premium_access(current_user):
        flash('Your account already has Premium access.')
        return redirect(url_for('upgrade'))

    provider = get_billing_provider()
    if provider == 'dev':
        set_user_premium_state(current_user.id, True)
        flash('Premium access enabled (development billing provider).')
        return redirect(url_for('dashboard'))

    if provider == 'stripe':
        try:
            checkout_session = _create_stripe_checkout_session(current_user)
        except Exception:
            current_app.logger.exception('Failed to create Stripe checkout session.')
            flash('Unable to start Stripe checkout right now. Please try again.')
            return redirect(url_for('upgrade'))
        return redirect(checkout_session.url, code=303)

    flash('Unsupported billing provider configuration.')
    return redirect(url_for('upgrade'))


@app.route('/upgrade/success')
@login_required
def upgrade_success():
    if user_has_premium_access(current_user):
        flash('Premium access confirmed.')
        return redirect(url_for('dashboard'))

    provider = get_billing_provider()
    if provider == 'dev':
        set_user_premium_state(current_user.id, True)
        flash('Premium access enabled.')
        return redirect(url_for('dashboard'))

    if provider == 'stripe':
        session_id = (request.args.get('session_id') or '').strip()
        if not session_id:
            flash('Missing Stripe session confirmation. Contact support if you were charged.')
            return redirect(url_for('upgrade'))

        try:
            upgraded = _sync_stripe_checkout_session_for_current_user(session_id, current_user.id)
        except Exception:
            current_app.logger.exception('Stripe checkout confirmation failed.')
            flash('Could not verify payment yet. Please refresh in a moment.')
            return redirect(url_for('upgrade'))

        if upgraded:
            flash('Premium access activated.')
            return redirect(url_for('dashboard'))

        flash('Payment is still processing. Please check back shortly.')
        return redirect(url_for('upgrade'))

    flash('Unsupported billing provider configuration.')
    return redirect(url_for('upgrade'))


@app.route('/upgrade/cancel')
@login_required
def upgrade_cancel():
    flash('Checkout canceled. Your account remains on the free tier.')
    return redirect(url_for('upgrade'))


@app.route('/api/billing/stripe/webhook', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    if get_billing_provider() != 'stripe':
        abort(404)

    try:
        import stripe  # type: ignore
    except ImportError:
        return jsonify({'error': 'Stripe SDK is not installed'}), 503

    stripe_secret_key = app.config.get('STRIPE_SECRET_KEY')
    stripe_webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET')
    if not stripe_secret_key or not stripe_webhook_secret:
        return jsonify({'error': 'Stripe webhook is not configured'}), 503

    stripe.api_key = stripe_secret_key
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=stripe_webhook_secret)
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    if event.get('type') == 'checkout.session.completed':
        session_obj = event.get('data', {}).get('object', {})
        user_id = _extract_stripe_user_id(session_obj)
        if user_id is not None:
            set_user_premium_state(user_id, True)

    return jsonify({'received': True})


@app.route('/play/<game_slug>')
@login_required
def play_game(game_slug):
    game_type = GameType.query.filter_by(slug=game_slug, is_active=True).first_or_404()
    if not user_can_access_game(current_user, game_type):
        flash('This is an Elite metric assessment. Please upgrade to Premium to play.', 'warning')
        return redirect(url_for('problems'))
    if not game_template_exists(game_slug):
        return redirect(url_for('coming_soon', game_slug=game_slug))
    return render_template(f'games/{game_slug}.html', game_type=game_type)


@app.route('/try/<game_slug>')
def try_game(game_slug):
    game_type = GameType.query.filter_by(slug=game_slug, is_active=True).first_or_404()
    
    if not user_can_access_game(current_user, game_type):
        flash('This is an Elite metric assessment. Please upgrade to Premium to play.', 'warning')
        return redirect(url_for('problems'))

    if not game_template_exists(game_slug):
        return redirect(url_for('coming_soon', game_slug=game_slug))

    return render_template(f'games/{game_slug}.html', game_type=game_type)


@app.route('/coming-soon/<game_slug>')
def coming_soon(game_slug):
    game_type = GameType.query.filter_by(slug=game_slug, is_active=True).first_or_404()
    return render_template('coming_soon.html', game_type=game_type)


@app.route('/api/session/start', methods=['POST'])
@login_required
def start_session():
    payload = request.get_json(silent=True)
    try:
        validated = validate_session_start_payload(payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    game_slug = validated['game_slug']

    game_type = GameType.query.filter_by(slug=game_slug, is_active=True).first()
    if not game_type:
        return jsonify({'error': 'Invalid game'}), 400
    if not user_can_access_game(current_user, game_type):
        return jsonify({'error': 'Premium access required'}), 403

    session = GameSession(
        user_id=current_user.id,
        game_type_id=game_type.id,
        difficulty_level=validated['difficulty_level']
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({'session_id': session.id})


@app.route('/api/session/<int:session_id>/end', methods=['POST'])
@login_required
def end_session(session_id):
    from datetime import datetime

    session = GameSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)
    if not user_can_access_game(current_user, session.game_type):
        return jsonify({'error': 'Premium access required'}), 403

    payload = request.get_json(silent=True)
    try:
        validated = validate_session_end_payload(payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    session.ended_at = datetime.utcnow()
    session.score = validated['score']
    session.accuracy = validated['accuracy']
    session.avg_response_time_ms = validated['avg_response_time_ms']
    session.rounds_completed = validated['rounds_completed']
    normalization = calculate_game_normalization(session)

    session.raw_data = validated['raw_data']
    session.raw_data['cognitive_weight_version'] = COGNITIVE_WEIGHT_VERSION
    session.raw_data['normalization'] = normalization

    if session.started_at:
        session.duration_seconds = int((session.ended_at - session.started_at).total_seconds())

    xp = calculate_xp(session)
    session.xp_earned = xp
    current_user.total_xp += xp
    cognitive_update = apply_cognitive_progression_rewards(session, normalization)
    trait_state = recompute_user_cognitive_scores(session.user_id)

    db.session.commit()

    return jsonify({
        'xp_earned': xp,
        'total_xp': current_user.total_xp,
        'score': session.score,
        'normalized_signal': normalization['normalized_signal'],
        'cognitive_weight_version': COGNITIVE_WEIGHT_VERSION,
        'cognitive_level_gain': cognitive_update['level_gain'],
        'cognitive_domain_gains': cognitive_update['domain_gains'],
        'cognitive_domain_confidence': trait_state['domain_confidence'],
    })


def calculate_xp(session):
    base_xp = 10
    accuracy_bonus = int((session.accuracy or 0) * 20)
    difficulty_bonus = (session.difficulty_level - 1) * 5
    return base_xp + accuracy_bonus + difficulty_bonus


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def calculate_game_normalization(session):
    current_level = max(0, int(session.rounds_completed or 0))
    game_slug = session.game_type.slug if session.game_type else None
    baseline_level = float(GAME_BASELINE_LEVELS.get(game_slug, 0.0))
    baseline_signal = clamp(
        50.0 + ((current_level - baseline_level) * NORMALIZATION_LEVEL_STEP),
        0.0,
        100.0,
    )

    peer_rows = db.session.query(GameSession.rounds_completed).join(
        User, User.id == GameSession.user_id
    ).filter(
        GameSession.game_type_id == session.game_type_id,
        GameSession.id != session.id,
        GameSession.rounds_completed.isnot(None),
        User.is_admin.is_(False),
    ).all()

    peer_levels = [max(0, int(row[0] or 0)) for row in peer_rows]
    sample_levels = peer_levels + [current_level]
    sample_size = len(sample_levels)

    if sample_size <= 1:
        return {
            'current_level': current_level,
            'sample_size': sample_size,
            'baseline_level': baseline_level,
            'baseline_signal': round(baseline_signal, 2),
            'population_weight': 0.0,
            'percentile': 50.0,
            'z_score': 0.0,
            'normalized_signal': round(baseline_signal, 2),
        }

    mean_level = sum(sample_levels) / sample_size
    variance = sum((value - mean_level) ** 2 for value in sample_levels) / sample_size
    std_dev = math.sqrt(variance)
    z_score = (current_level - mean_level) / std_dev if std_dev > 0 else 0.0

    less_count = sum(1 for value in sample_levels if value < current_level)
    equal_count = sum(1 for value in sample_levels if value == current_level)
    percentile = (100.0 * (less_count + (0.5 * equal_count)) / sample_size)

    z_score_scaled = clamp(50.0 + (15.0 * z_score), 0.0, 100.0)
    population_signal = clamp((0.7 * percentile) + (0.3 * z_score_scaled), 0.0, 100.0)
    population_weight = clamp(
        (sample_size - 1) / float(max(1, MIN_POPULATION_SAMPLE_FOR_FULL_WEIGHT - 1)),
        0.0,
        1.0,
    )
    normalized_signal = (
        (population_weight * population_signal)
        + ((1.0 - population_weight) * baseline_signal)
    )
    normalized_signal = clamp(normalized_signal, 0.0, 100.0)

    return {
        'current_level': current_level,
        'sample_size': sample_size,
        'baseline_level': baseline_level,
        'baseline_signal': round(baseline_signal, 2),
        'population_weight': round(population_weight, 4),
        'percentile': round(percentile, 2),
        'z_score': round(z_score, 4),
        'normalized_signal': round(normalized_signal, 2),
    }


def extract_normalized_signal(session):
    raw_data = session.raw_data if isinstance(session.raw_data, dict) else {}
    normalization = raw_data.get('normalization') if isinstance(raw_data.get('normalization'), dict) else {}
    value = normalization.get('normalized_signal')
    try:
        return float(value)
    except (TypeError, ValueError):
        return 50.0


def recompute_user_cognitive_scores(user_id):
    from datetime import datetime

    user = User.query.get(user_id)
    if not user or user.is_admin:
        return {'domain_scores': {}, 'domain_confidence': {}}

    sessions = db.session.query(GameSession, GameType.slug).join(
        GameType, GameType.id == GameSession.game_type_id
    ).filter(
        GameSession.user_id == user_id,
        GameType.slug.in_(list(GAME_COGNITIVE_WEIGHTS.keys())),
    ).all()

    sessions_by_game = {}
    for session_obj, game_slug in sessions:
        domain_weights = GAME_COGNITIVE_WEIGHTS.get(game_slug)
        if not domain_weights:
            continue

        completed_level = max(0, int(session_obj.rounds_completed or 0))
        if completed_level <= 0:
            continue

        normalized_signal = extract_normalized_signal(session_obj)
        game_bucket = sessions_by_game.setdefault(
            game_slug,
            {
                'domain_weights': domain_weights,
                'peak_level': 0,
                'sessions': [],
            },
        )
        game_bucket['peak_level'] = max(game_bucket['peak_level'], completed_level)
        game_bucket['sessions'].append(
            {
                'completed_level': completed_level,
                'normalized_signal': normalized_signal,
            }
        )

    best_game_domain_scores = {}
    for game_slug, game_bucket in sessions_by_game.items():
        peak_level = int(game_bucket['peak_level'])
        min_eligible_level = max(1, peak_level - TRAIT_RETRY_WINDOW_BELOW_PEAK)
        domain_weights = game_bucket['domain_weights']

        # Prevent low-level farming: only peak and near-peak retries can impact traits.
        for session_data in game_bucket['sessions']:
            completed_level = int(session_data['completed_level'])
            if completed_level < min_eligible_level:
                continue

            normalized_signal = float(session_data['normalized_signal'])
            signal_multiplier = clamp((normalized_signal / 50.0), 0.5, 1.5)

            for domain_key, weight in domain_weights.items():
                if weight <= 0:
                    continue
                value = float(completed_level * weight * signal_multiplier)
                key = (game_slug, domain_key)
                prior_value = best_game_domain_scores.get(key, 0.0)
                if value > prior_value:
                    best_game_domain_scores[key] = value

    domain_scores = {}
    domain_confidence = {}
    for (game_slug, domain_key), value in best_game_domain_scores.items():
        domain_scores[domain_key] = max(domain_scores.get(domain_key, 0.0), value)
        domain_confidence[domain_key] = domain_confidence.get(domain_key, 0) + 1

    existing_rows = {
        row.domain: row
        for row in CognitiveScore.query.filter_by(user_id=user_id).all()
    }

    now = datetime.utcnow()
    for domain_key in MANAGED_COGNITIVE_DOMAINS:
        score_value = round(float(domain_scores.get(domain_key, 0.0)), 2)
        confidence_value = int(domain_confidence.get(domain_key, 0))
        existing_row = existing_rows.get(domain_key)

        if existing_row is None:
            if score_value <= 0 and confidence_value <= 0:
                continue
            existing_row = CognitiveScore(
                user_id=user_id,
                domain=domain_key,
                score=0.0,
                session_count=0,
            )
            db.session.add(existing_row)

        existing_row.score = score_value
        existing_row.session_count = confidence_value
        existing_row.calculated_at = now

    return {
        'domain_scores': {key: round(value, 2) for key, value in domain_scores.items()},
        'domain_confidence': domain_confidence,
    }


def apply_cognitive_progression_rewards(session, normalization=None):
    game_slug = session.game_type.slug if session.game_type else None
    domain_weights = GAME_COGNITIVE_WEIGHTS.get(game_slug)
    if not domain_weights:
        return {'level_gain': 0, 'domain_gains': {}}

    # Admin runs are often test runs and should not alter progression scores.
    if current_user.is_admin:
        return {'level_gain': 0, 'domain_gains': {}}

    completed_level = int(session.rounds_completed or 0)
    if completed_level <= 0:
        return {'level_gain': 0, 'domain_gains': {}}

    previous_peak = db.session.query(db.func.max(GameSession.rounds_completed)).filter(
        GameSession.user_id == session.user_id,
        GameSession.game_type_id == session.game_type_id,
        GameSession.id != session.id,
    ).scalar() or 0

    level_gain = max(0, completed_level - int(previous_peak))
    if level_gain <= 0:
        return {'level_gain': 0, 'domain_gains': {}}

    normalized_signal = float((normalization or {}).get('normalized_signal', 50.0))
    signal_multiplier = clamp((normalized_signal / 50.0), 0.5, 1.5)

    domain_gains = {}
    for domain_key, weight in domain_weights.items():
        gain = float(level_gain * weight * signal_multiplier)
        domain_gains[domain_key] = gain

    return {
        'level_gain': level_gain,
        'domain_gains': domain_gains,
    }



@app.route('/profile/<username>')
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    if not user.profile_public and (not current_user.is_authenticated or current_user.id != user.id):
        abort(404)

    cognitive_scores = {s.domain: s for s in user.cognitive_scores}
    return render_template('public_profile.html',
                         profile_user=user,
                         cognitive_scores=cognitive_scores,
                         domains=COGNITIVE_DOMAINS)


@app.route('/leaderboard')
def leaderboard():
    top_users = User.query.order_by(User.total_xp.desc()).limit(50).all()
    return render_template('leaderboard.html', users=top_users)


@app.route('/admin')
@login_required
@admin_required
def admin_panel():
    users = User.query.order_by(User.created_at.desc()).all()
    game_types = GameType.query.all()
    return render_template('admin.html', users=users, game_types=game_types)


@app.route('/admin/users/<int:user_id>/premium', methods=['POST'])
@login_required
@admin_required
@limiter.limit(lambda: app.config['RATE_LIMIT_ADMIN_MUTATIONS'], methods=['POST'])
def set_user_premium_access(user_id):
    target_user = db.session.get(User, user_id)
    if target_user is None:
        abort(404)

    raw_value = (request.form.get('is_premium') or '').strip().lower()
    if raw_value not in {'true', 'false'}:
        abort(400)

    target_user.is_premium = (raw_value == 'true')
    db.session.commit()

    status_label = 'granted' if target_user.is_premium else 'revoked'
    flash(f'Premium access {status_label} for @{target_user.username}.')
    return redirect(url_for('admin_panel'))
