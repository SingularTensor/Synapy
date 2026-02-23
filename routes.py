import math
import os
import json
from datetime import datetime, timedelta, timezone
from functools import wraps
import click
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib import request as urllib_request
from flask import render_template, request, jsonify, redirect, url_for, flash, abort, current_app
from flask.cli import AppGroup
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app import app, limiter, csrf
from database import (
    db,
    User,
    GameType,
    GameSession,
    CognitiveScore,
    COGNITIVE_DOMAINS,
    StripeWebhookEvent,
)

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
TIMEZONE_NAME_MAX_LENGTH = 64
MAX_LIVES = 8
LIFE_REGEN_INTERVAL_SECONDS = 1800
DEFAULT_GAME_LIFE_COST = 1
MAX_GAME_LIFE_COST = 3
GAME_LIFE_COSTS = {}

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


def resolve_timezone_name(timezone_name):
    normalized = (timezone_name or '').strip()
    if not normalized:
        return None

    if normalized.upper() in {'UTC', 'Z'}:
        return timezone.utc

    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError:
        return None


def get_streak_timezone(user=None):
    user_timezone_name = (getattr(user, 'timezone', '') or '').strip()
    if user_timezone_name:
        user_timezone = resolve_timezone_name(user_timezone_name)
        if user_timezone is not None:
            return user_timezone
        current_app.logger.warning(
            'Invalid user timezone=%s for user_id=%s. Falling back to app timezone.',
            user_timezone_name,
            getattr(user, 'id', None),
        )

    configured_tz = (app.config.get('STREAK_TIMEZONE') or '').strip()
    if configured_tz:
        configured_timezone = resolve_timezone_name(configured_tz)
        if configured_timezone is not None:
            return configured_timezone
        current_app.logger.warning(
            'Invalid STREAK_TIMEZONE=%s. Falling back to server local timezone.',
            configured_tz,
        )

    local_tz = datetime.now().astimezone().tzinfo
    return local_tz or timezone.utc


def to_streak_local_date(dt_value, tzinfo):
    if dt_value is None:
        return None

    if dt_value.tzinfo is None:
        dt_utc = dt_value.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_value.astimezone(timezone.utc)

    return dt_utc.astimezone(tzinfo).date()


def update_user_streak(user, played_at_utc):
    streak_tz = get_streak_timezone(user=user)
    played_date = to_streak_local_date(played_at_utc, streak_tz)
    previous_date = to_streak_local_date(user.last_played, streak_tz)

    current_streak = max(0, int(user.current_streak or 0))
    longest_streak = max(0, int(user.longest_streak or 0))

    if previous_date is None:
        current_streak = 1
    elif played_date <= previous_date:
        # Same-day or out-of-order completion should not inflate streak count.
        current_streak = max(1, current_streak)
    elif played_date == (previous_date + timedelta(days=1)):
        # Local-midnight rollover: consecutive day extends streak.
        current_streak = max(1, current_streak) + 1
    else:
        # Missed at least one local day; streak restarts.
        current_streak = 1

    user.current_streak = current_streak
    user.longest_streak = max(longest_streak, current_streak)

    if user.last_played is None or played_at_utc >= user.last_played:
        user.last_played = played_at_utc

    return {
        'current_streak': int(user.current_streak),
        'longest_streak': int(user.longest_streak),
    }


def get_game_life_cost(game_slug):
    configured = GAME_LIFE_COSTS.get(game_slug, DEFAULT_GAME_LIFE_COST)
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        parsed = DEFAULT_GAME_LIFE_COST
    return clamp(parsed, 1, MAX_GAME_LIFE_COST)


def _normalize_user_life_state(user, now=None):
    now = now or datetime.utcnow()
    changed = False

    if user.lives_remaining is None:
        user.lives_remaining = MAX_LIVES
        changed = True
    else:
        normalized = clamp(int(user.lives_remaining), 0, MAX_LIVES)
        if normalized != user.lives_remaining:
            user.lives_remaining = normalized
            changed = True

    if user.lives_last_updated_at is None:
        user.lives_last_updated_at = now
        changed = True

    return changed


def refresh_user_lives(user, now=None):
    now = now or datetime.utcnow()
    changed = _normalize_user_life_state(user, now=now)

    if user.lives_remaining >= MAX_LIVES:
        return changed

    elapsed_seconds = int((now - user.lives_last_updated_at).total_seconds())
    if elapsed_seconds < LIFE_REGEN_INTERVAL_SECONDS:
        return changed

    gained_lives = elapsed_seconds // LIFE_REGEN_INTERVAL_SECONDS
    if gained_lives <= 0:
        return changed

    user.lives_remaining = min(MAX_LIVES, int(user.lives_remaining) + int(gained_lives))
    changed = True

    if user.lives_remaining >= MAX_LIVES:
        user.lives_last_updated_at = now
    else:
        user.lives_last_updated_at = user.lives_last_updated_at + timedelta(
            seconds=int(gained_lives) * LIFE_REGEN_INTERVAL_SECONDS
        )
    return changed


def get_seconds_until_next_life(user, now=None):
    now = now or datetime.utcnow()
    _normalize_user_life_state(user, now=now)
    if user.lives_remaining >= MAX_LIVES:
        return 0

    elapsed_seconds = max(0, int((now - user.lives_last_updated_at).total_seconds()))
    progress = elapsed_seconds % LIFE_REGEN_INTERVAL_SECONDS
    if progress == 0:
        return LIFE_REGEN_INTERVAL_SECONDS
    return LIFE_REGEN_INTERVAL_SECONDS - progress


def format_seconds_short(total_seconds):
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f'{hours}h {minutes}m'
    return f'{minutes}m {seconds:02d}s'


def build_user_lives_view(user, now=None):
    now = now or datetime.utcnow()
    changed = refresh_user_lives(user, now=now)
    seconds_until_next = get_seconds_until_next_life(user, now=now)
    return {
        'lives_remaining': int(user.lives_remaining),
        'lives_max': MAX_LIVES,
        'seconds_until_next_life': int(seconds_until_next),
        'next_life_eta': format_seconds_short(seconds_until_next) if seconds_until_next else 'Ready',
        'changed': changed,
    }


def consume_user_lives(user, life_cost, now=None):
    now = now or datetime.utcnow()
    changed = refresh_user_lives(user, now=now)
    available = int(user.lives_remaining or 0)
    was_full = available >= MAX_LIVES
    if available < int(life_cost):
        return {
            'ok': False,
            'changed': changed,
            'lives_remaining': available,
            'lives_required': int(life_cost),
            'seconds_until_next_life': get_seconds_until_next_life(user, now=now),
        }

    user.lives_remaining = max(0, available - int(life_cost))
    if was_full:
        # When spending from full, start the refill timer from this spend event.
        user.lives_last_updated_at = now
    elif user.lives_last_updated_at is None:
        user.lives_last_updated_at = now

    return {
        'ok': True,
        'changed': True,
        'lives_remaining': int(user.lives_remaining),
        'lives_required': int(life_cost),
        'seconds_until_next_life': get_seconds_until_next_life(user, now=now),
    }


def _billing_log_context(**context):
    parts = []
    for key in sorted(context.keys()):
        value = context[key]
        if value is None:
            continue
        text = str(value).replace('\n', ' ').strip()
        if not text:
            continue
        parts.append(f'{key}={text}')
    return ' '.join(parts)


def _billing_log(level, message, **context):
    logger_fn = getattr(current_app.logger, level, current_app.logger.info)
    context_text = _billing_log_context(**context)
    if context_text:
        logger_fn('[billing] %s %s', message, context_text)
        return
    logger_fn('[billing] %s', message)


def _send_billing_alert(event_name, severity='error', **context):
    level = 'warning' if severity == 'warning' else 'error'
    _billing_log(level, f'alert:{event_name}', **context)

    if not app.config.get('BILLING_ALERTS_ENABLED', False):
        return

    webhook_url = (app.config.get('BILLING_ALERT_WEBHOOK_URL') or '').strip()
    if not webhook_url:
        return

    payload = {
        'service': 'synapy',
        'scope': 'billing',
        'event': event_name,
        'severity': severity,
        'context': context,
    }
    data = json.dumps(payload, separators=(',', ':'), default=str).encode('utf-8')
    req = urllib_request.Request(
        webhook_url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    timeout = max(1, int(app.config.get('BILLING_ALERT_TIMEOUT_SECONDS', 3)))
    try:
        with urllib_request.urlopen(req, timeout=timeout):
            return
    except Exception:
        current_app.logger.exception(
            'Failed to deliver billing alert event=%s webhook_url=%s',
            event_name,
            webhook_url,
        )


def _stripe_get(payload_obj, key, default=None):
    if payload_obj is None:
        return default
    if isinstance(payload_obj, dict):
        return payload_obj.get(key, default)
    getter = getattr(payload_obj, 'get', None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            value = getter(key)
            return default if value is None else value
    return getattr(payload_obj, key, default)


def _extract_stripe_id(raw_value):
    if isinstance(raw_value, dict):
        raw_value = raw_value.get('id')
    elif hasattr(raw_value, 'id'):
        raw_value = getattr(raw_value, 'id')
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def _extract_stripe_customer_id(payload_obj):
    return _extract_stripe_id(_stripe_get(payload_obj, 'customer'))


def _extract_stripe_subscription_id(payload_obj, *, allow_object_id=False):
    subscription_id = _extract_stripe_id(_stripe_get(payload_obj, 'subscription'))
    if subscription_id:
        return subscription_id
    if allow_object_id:
        return _extract_stripe_id(_stripe_get(payload_obj, 'id'))
    return None


def _is_stripe_subscription_active(status):
    return status in {'active', 'trialing'}


def _find_user_for_billing_sync(*, user_id=None, stripe_customer_id=None, stripe_subscription_id=None):
    if user_id is not None:
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            user = None
        if user is not None:
            return user

    if stripe_subscription_id:
        user = User.query.filter_by(stripe_subscription_id=stripe_subscription_id).first()
        if user is not None:
            return user

    if stripe_customer_id:
        user = User.query.filter_by(stripe_customer_id=stripe_customer_id).first()
        if user is not None:
            return user

    return None


def _apply_user_billing_state(
    user,
    *,
    is_premium=None,
    billing_status=None,
    stripe_customer_id=None,
    stripe_subscription_id=None,
):
    if stripe_customer_id:
        user.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        user.stripe_subscription_id = stripe_subscription_id
    if is_premium is not None:
        user.is_premium = bool(is_premium)
    if billing_status:
        user.billing_status = billing_status


def set_user_premium_state(
    user_id,
    is_premium,
    *,
    billing_status=None,
    stripe_customer_id=None,
    stripe_subscription_id=None,
    commit=True,
):
    user = db.session.get(User, int(user_id))
    if user is None:
        return None
    _apply_user_billing_state(
        user,
        is_premium=is_premium,
        billing_status=billing_status,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )
    if commit:
        db.session.commit()
    return user


def _claim_stripe_event(event_id, event_type):
    event_row = StripeWebhookEvent(event_id=event_id, event_type=event_type)
    db.session.add(event_row)
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False
    return True


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

    set_user_premium_state(
        expected_user_id,
        True,
        billing_status='active',
        stripe_customer_id=_extract_stripe_customer_id(session_obj),
        stripe_subscription_id=_extract_stripe_subscription_id(session_obj),
    )
    return True


def _handle_stripe_checkout_completed(session_obj):
    user_id = _extract_stripe_user_id(session_obj)
    if user_id is None:
        return

    payment_status = (session_obj.get('payment_status') or '').lower()
    status = (session_obj.get('status') or '').lower()
    if payment_status not in {'paid', 'no_payment_required'} and status != 'complete':
        return

    set_user_premium_state(
        user_id,
        True,
        billing_status='active',
        stripe_customer_id=_extract_stripe_customer_id(session_obj),
        stripe_subscription_id=_extract_stripe_subscription_id(session_obj),
        commit=False,
    )


def _handle_stripe_subscription_event(subscription_obj):
    subscription_status = (subscription_obj.get('status') or '').strip().lower()
    stripe_customer_id = _extract_stripe_customer_id(subscription_obj)
    stripe_subscription_id = _extract_stripe_subscription_id(
        subscription_obj, allow_object_id=True
    )
    user_id = _extract_stripe_user_id(subscription_obj)

    user = _find_user_for_billing_sync(
        user_id=user_id,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )
    if user is None:
        return

    _apply_user_billing_state(
        user,
        is_premium=_is_stripe_subscription_active(subscription_status),
        billing_status=subscription_status or 'inactive',
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )


def _handle_stripe_invoice_payment_failed(invoice_obj):
    stripe_customer_id = _extract_stripe_customer_id(invoice_obj)
    stripe_subscription_id = _extract_stripe_subscription_id(invoice_obj)
    user = _find_user_for_billing_sync(
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )
    if user is None:
        return

    _apply_user_billing_state(
        user,
        is_premium=False,
        billing_status='payment_failed',
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )


def _process_stripe_event(event):
    event_type = (event.get('type') or '').strip()
    event_object = event.get('data', {}).get('object', {})
    if not isinstance(event_object, dict):
        event_object = {}

    if event_type == 'checkout.session.completed':
        _handle_stripe_checkout_completed(event_object)
        return

    if event_type in {'customer.subscription.updated', 'customer.subscription.deleted'}:
        _handle_stripe_subscription_event(event_object)
        return

    if event_type == 'invoice.payment_failed':
        _handle_stripe_invoice_payment_failed(event_object)


def _normalize_stripe_subscription_status(status):
    return (str(status or '').strip().lower() or 'inactive')


def _subscription_created_ts(subscription_obj):
    created = _stripe_get(subscription_obj, 'created', 0)
    try:
        return int(created)
    except (TypeError, ValueError):
        return 0


def _pick_reconcile_subscription(subscription_rows):
    if not subscription_rows:
        return None
    active_rows = [
        row
        for row in subscription_rows
        if _is_stripe_subscription_active(
            _normalize_stripe_subscription_status(_stripe_get(row, 'status'))
        )
    ]
    candidates = active_rows or subscription_rows
    return max(candidates, key=_subscription_created_ts)


def _get_stripe_invalid_request_error(stripe_module):
    return getattr(getattr(stripe_module, 'error', None), 'InvalidRequestError', Exception)


def _fetch_reconcile_subscription_for_user(stripe_module, user):
    invalid_request_error = _get_stripe_invalid_request_error(stripe_module)
    subscription_obj = None

    if user.stripe_subscription_id:
        try:
            subscription_obj = stripe_module.Subscription.retrieve(user.stripe_subscription_id)
        except invalid_request_error as exc:
            if 'No such subscription' not in str(exc):
                raise

    if subscription_obj is not None:
        return subscription_obj

    if not user.stripe_customer_id:
        return None

    subscription_list = stripe_module.Subscription.list(
        customer=user.stripe_customer_id,
        status='all',
        limit=20,
    )
    subscription_rows = _stripe_get(subscription_list, 'data', []) or []
    if not isinstance(subscription_rows, list):
        try:
            subscription_rows = list(subscription_rows)
        except TypeError:
            subscription_rows = []

    return _pick_reconcile_subscription(subscription_rows)


def _build_reconciled_user_state(stripe_module, user):
    subscription_obj = _fetch_reconcile_subscription_for_user(stripe_module, user)
    if subscription_obj is None:
        return {
            'is_premium': False,
            'billing_status': 'inactive',
            'stripe_customer_id': user.stripe_customer_id,
            'stripe_subscription_id': None,
        }

    subscription_status = _normalize_stripe_subscription_status(
        _stripe_get(subscription_obj, 'status')
    )
    return {
        'is_premium': _is_stripe_subscription_active(subscription_status),
        'billing_status': subscription_status,
        'stripe_customer_id': _extract_stripe_customer_id(subscription_obj) or user.stripe_customer_id,
        'stripe_subscription_id': (
            _extract_stripe_subscription_id(subscription_obj, allow_object_id=True)
            or user.stripe_subscription_id
        ),
    }


def _diff_user_billing_state(user, target_state):
    fields = (
        'is_premium',
        'billing_status',
        'stripe_customer_id',
        'stripe_subscription_id',
    )
    changes = {}
    for field_name in fields:
        old_value = getattr(user, field_name)
        new_value = target_state[field_name]
        if old_value != new_value:
            changes[field_name] = {'old': old_value, 'new': new_value}
    return changes


def _apply_reconciled_user_state(user, target_state):
    user.is_premium = bool(target_state['is_premium'])
    user.billing_status = target_state['billing_status']
    user.stripe_customer_id = target_state['stripe_customer_id']
    user.stripe_subscription_id = target_state['stripe_subscription_id']


billing_cli = AppGroup('billing')


@billing_cli.command('reconcile')
@click.option(
    '--user-id',
    'user_ids',
    type=int,
    multiple=True,
    help='Reconcile only the specified user ID(s).',
)
@click.option(
    '--limit',
    type=click.IntRange(min=1, max=5000),
    default=200,
    show_default=True,
    help='Maximum users to scan when no --user-id values are provided.',
)
@click.option('--dry-run', is_flag=True, help='Show planned changes without writing to the database.')
def billing_reconcile_command(user_ids, limit, dry_run):
    provider = get_billing_provider()
    if provider != 'stripe':
        _billing_log('info', 'reconcile_skipped_non_stripe_provider', provider=provider)
        click.echo(f'Skipping reconcile: BILLING_PROVIDER={provider} (expected stripe).')
        return

    stripe_secret_key = app.config.get('STRIPE_SECRET_KEY', '').strip()
    if not stripe_secret_key:
        raise click.ClickException('STRIPE_SECRET_KEY is required for billing reconciliation.')

    try:
        import stripe  # type: ignore
    except ImportError as exc:
        raise click.ClickException('Stripe SDK is not installed.') from exc

    stripe.api_key = stripe_secret_key

    if user_ids:
        users = User.query.filter(User.id.in_(set(user_ids))).order_by(User.id.asc()).all()
    else:
        users = User.query.filter(
            or_(
                User.is_premium.is_(True),
                User.billing_status != 'inactive',
                User.stripe_customer_id.isnot(None),
                User.stripe_subscription_id.isnot(None),
            )
        ).order_by(User.id.asc()).limit(limit).all()

    if not users:
        click.echo('No users matched billing reconciliation criteria.')
        return

    updated = 0
    unchanged = 0
    errors = 0
    for user in users:
        try:
            target_state = _build_reconciled_user_state(stripe, user)
            changes = _diff_user_billing_state(user, target_state)
            if not changes:
                unchanged += 1
                continue

            updated += 1
            changed_fields = ', '.join(sorted(changes.keys()))
            click.echo(f'user_id={user.id} reconcile {changed_fields}')
            if not dry_run:
                _apply_reconciled_user_state(user, target_state)
        except Exception as exc:
            errors += 1
            current_app.logger.exception('Billing reconcile failed for user_id=%s', user.id)
            _billing_log('error', 'reconcile_user_failed', user_id=user.id, error=exc)
            click.echo(f'user_id={user.id} reconcile_error={exc}')

    if not dry_run:
        db.session.commit()

    summary = (
        f'reconcile_complete scanned={len(users)} '
        f'updated={updated} unchanged={unchanged} '
        f'errors={errors} dry_run={str(dry_run).lower()}'
    )
    click.echo(summary)
    _billing_log(
        'info',
        'reconcile_complete',
        scanned=len(users),
        updated=updated,
        unchanged=unchanged,
        errors=errors,
        dry_run=str(dry_run).lower(),
    )
    if errors > 0:
        _send_billing_alert(
            'reconcile_completed_with_errors',
            severity='warning',
            scanned=len(users),
            updated=updated,
            unchanged=unchanged,
            errors=errors,
            dry_run=str(dry_run).lower(),
        )


app.cli.add_command(billing_cli)


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


def validate_timezone_sync_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object')

    timezone_name = payload.get('timezone')
    if not isinstance(timezone_name, str):
        raise ValueError('timezone must be a string')

    normalized_timezone_name = timezone_name.strip()
    if not normalized_timezone_name:
        raise ValueError('timezone must be a non-empty string')
    if len(normalized_timezone_name) > TIMEZONE_NAME_MAX_LENGTH:
        raise ValueError(f'timezone must be <= {TIMEZONE_NAME_MAX_LENGTH} characters')

    if resolve_timezone_name(normalized_timezone_name) is None:
        raise ValueError('timezone must be a valid IANA timezone name')

    if normalized_timezone_name.upper() in {'UTC', 'Z'}:
        return 'UTC'
    return normalized_timezone_name


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
    game_types = GameType.query.filter_by(is_active=True).all()
    for game in game_types:
        game.is_coming_soon = not game_template_exists(game.slug)
        game.life_cost = get_game_life_cost(game.slug)

    lives_view = {
        'lives_remaining': MAX_LIVES,
        'lives_max': MAX_LIVES,
        'seconds_until_next_life': 0,
        'next_life_eta': 'Ready',
        'changed': False,
    }
    if current_user.is_authenticated:
        lives_view = build_user_lives_view(current_user)
        if lives_view['changed']:
            db.session.commit()

    return render_template(
        'problems.html',
        games=game_types,
        lives_remaining=lives_view['lives_remaining'],
        lives_max=lives_view['lives_max'],
        seconds_until_next_life=lives_view['seconds_until_next_life'],
        next_life_eta=lives_view['next_life_eta'],
    )


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
        _send_billing_alert('webhook_stripe_sdk_missing', severity='error')
        return jsonify({'error': 'Stripe SDK is not installed'}), 503

    stripe_secret_key = app.config.get('STRIPE_SECRET_KEY')
    stripe_webhook_secret = app.config.get('STRIPE_WEBHOOK_SECRET')
    if not stripe_secret_key or not stripe_webhook_secret:
        _send_billing_alert(
            'webhook_misconfigured',
            severity='error',
            has_secret_key=bool(stripe_secret_key),
            has_webhook_secret=bool(stripe_webhook_secret),
        )
        return jsonify({'error': 'Stripe webhook is not configured'}), 503

    stripe.api_key = stripe_secret_key
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=stripe_webhook_secret)
    except ValueError:
        _billing_log('warning', 'webhook_invalid_payload', remote_addr=request.remote_addr)
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        _billing_log('warning', 'webhook_invalid_signature', remote_addr=request.remote_addr)
        return jsonify({'error': 'Invalid signature'}), 400

    event_id = (event.get('id') or '').strip()
    event_type = (event.get('type') or '').strip()
    if not event_id:
        _billing_log('warning', 'webhook_missing_event_id')
        return jsonify({'error': 'Stripe event id is required'}), 400
    if not event_type:
        _billing_log('warning', 'webhook_missing_event_type', event_id=event_id)
        return jsonify({'error': 'Stripe event type is required'}), 400

    if not _claim_stripe_event(event_id, event_type):
        _billing_log('info', 'webhook_duplicate_event', event_id=event_id, event_type=event_type)
        return jsonify({'received': True, 'duplicate': True})

    try:
        _process_stripe_event(event)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to process Stripe webhook event %s.', event_id)
        _send_billing_alert(
            'webhook_processing_failed',
            severity='error',
            event_id=event_id,
            event_type=event_type,
        )
        return jsonify({'error': 'Stripe webhook processing failed'}), 500

    _billing_log('info', 'webhook_processed', event_id=event_id, event_type=event_type)
    return jsonify({'received': True})


@app.route('/play/<game_slug>')
@login_required
def play_game(game_slug):
    game_type = GameType.query.filter_by(slug=game_slug, is_active=True).first_or_404()
    if not user_can_access_game(current_user, game_type):
        flash('This is an Elite metric assessment. Please upgrade to Premium to play.', 'warning')
        return redirect(url_for('problems'))
    if not current_user.is_admin:
        life_cost = get_game_life_cost(game_slug)
        lives_view = build_user_lives_view(current_user)
        if lives_view['changed']:
            db.session.commit()
        if lives_view['lives_remaining'] < life_cost:
            flash(
                f'You need {life_cost} life to start this game. '
                f'Next life in {lives_view["next_life_eta"]}.',
                'warning',
            )
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


@app.route('/api/user/timezone', methods=['POST'])
@login_required
@limiter.limit(lambda: app.config['RATE_LIMIT_TIMEZONE_SYNC'], methods=['POST'])
def sync_user_timezone():
    payload = request.get_json(silent=True)
    try:
        timezone_name = validate_timezone_sync_payload(payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    previous_timezone = (current_user.timezone or '').strip()
    if previous_timezone != timezone_name:
        current_user.timezone = timezone_name
        db.session.commit()

    return jsonify({'timezone': current_user.timezone or timezone_name})


@app.route('/api/session/start', methods=['POST'])
@login_required
@limiter.limit(lambda: app.config['RATE_LIMIT_SESSION_START'], methods=['POST'])
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

    life_cost = get_game_life_cost(game_slug)
    life_use = {
        'ok': True,
        'changed': False,
        'lives_remaining': int(getattr(current_user, 'lives_remaining', MAX_LIVES) or MAX_LIVES),
        'seconds_until_next_life': 0,
    }
    if not current_user.is_admin:
        life_use = consume_user_lives(current_user, life_cost)
        if not life_use['ok']:
            if life_use['changed']:
                db.session.commit()
            return jsonify({
                'error': 'Not enough lives',
                'lives_remaining': life_use['lives_remaining'],
                'lives_required': life_use['lives_required'],
                'seconds_until_next_life': life_use['seconds_until_next_life'],
                'next_life_eta': format_seconds_short(life_use['seconds_until_next_life']),
            }), 403

    session = GameSession(
        user_id=current_user.id,
        game_type_id=game_type.id,
        difficulty_level=validated['difficulty_level']
    )
    db.session.add(session)
    db.session.commit()

    return jsonify({
        'session_id': session.id,
        'life_cost': life_cost,
        'lives_remaining': life_use['lives_remaining'],
        'seconds_until_next_life': life_use['seconds_until_next_life'],
        'next_life_eta': format_seconds_short(life_use['seconds_until_next_life']),
    })


@app.route('/api/session/<int:session_id>/end', methods=['POST'])
@login_required
@limiter.limit(lambda: app.config['RATE_LIMIT_SESSION_END'], methods=['POST'])
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
    streak_update = update_user_streak(current_user, session.ended_at)
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
        'current_streak': streak_update['current_streak'],
        'longest_streak': streak_update['longest_streak'],
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
    recent_webhook_events = StripeWebhookEvent.query.order_by(
        StripeWebhookEvent.processed_at.desc()
    ).limit(20).all()
    return render_template(
        'admin.html',
        users=users,
        game_types=game_types,
        recent_webhook_events=recent_webhook_events,
        billing_provider=get_billing_provider(),
    )


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
