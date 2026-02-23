# Dependency Map

This document is a fast navigation and impact map for the Synapy codebase.
Use this first when planning edits.

## 1) Entry Points And Runtime Wiring

Primary app wiring lives in `app.py`.

- App and config bootstrap: `app.py`
- DB + models source of truth: `database.py`
- HTTP route/controller logic: `routes.py`
- HTML/JS client surface: `templates/`
- Schema history: `migrations/versions/`
- Test behavior contracts: `tests/`

Runtime wiring in `app.py`:

- `Flask` app instance
- `SQLAlchemy` (`db`)
- `Flask-Migrate` (`migrate`)
- `Flask-WTF` CSRF (`csrf`)
- `Flask-Limiter` (`limiter`)
- `Flask-Login` (`login_manager`)
- Imports `routes.py` after extension initialization

Dependency direction is intentionally:

- `app.py` -> initializes shared extensions
- `routes.py` -> imports `app` and `limiter` from `app.py`
- `routes.py` -> imports models from `database.py`
- Templates -> call route endpoints and JSON APIs

## 2) Route Groups (routes.py)

### Public And Auth

- `/` -> index
- `/problems` -> list active game types
- `/login` -> form POST auth
- `/register` -> form POST account creation
- `/logout` -> authenticated logout

Dependencies:

- `User` model for login/register
- `GameType` for problems list
- `limiter` on login/register POST

### User Surfaces

- `/dashboard` -> user analytics page
- `/profile/<username>` -> public profile
- `/leaderboard` -> XP ranking

Dependencies:

- `GameSession`, `CognitiveScore`, `User`
- `COGNITIVE_DOMAINS` labels for UI rendering

### Upgrade/Billing

- `/upgrade` -> plan page
- `/upgrade/checkout` (POST) -> start checkout flow
- `/upgrade/success` -> post-checkout confirmation
- `/upgrade/cancel` -> canceled checkout
- `/api/billing/stripe/webhook` (POST) -> Stripe webhook ingest

Dependencies:

- `User.is_premium`
- App config billing keys:
  - `BILLING_PROVIDER`
  - `STRIPE_SECRET_KEY`
  - `STRIPE_PRICE_ID`
  - `STRIPE_WEBHOOK_SECRET`
- `stripe` SDK when provider is `stripe`
- `limiter` on checkout POST

### Game Access And Session APIs

- `/play/<slug>` -> authenticated play
- `/try/<slug>` -> guest/auth trial
- `/coming-soon/<slug>`
- `/api/session/start` (POST)
- `/api/session/<id>/end` (POST)

Dependencies:

- Shared access guard: `user_can_access_game(...)`
- `GameType.access_level` + `User.is_premium`
- Session payload validators:
  - `validate_session_start_payload(...)`
  - `validate_session_end_payload(...)`
- CSRF required on API POSTs (`X-CSRFToken` from client JS)
- Game templates in `templates/games/*.html` supply payload fields

### Cognitive Scoring Pipeline

Core functions:

- `calculate_game_normalization(...)`
- `extract_normalized_signal(...)`
- `recompute_user_cognitive_scores(...)`
- `apply_cognitive_progression_rewards(...)`
- `validate_game_cognitive_weights(...)`

Dependencies:

- `GAME_COGNITIVE_WEIGHTS`
- `GAME_BASELINE_LEVELS`
- `COGNITIVE_WEIGHT_VERSION`
- `TRAIT_RETRY_WINDOW_BELOW_PEAK`
- `GameSession` + `CognitiveScore`

Important invariant: weight config and peak-window logic are protected by tests and validation checks.

### Admin

- `/admin` -> admin panel
- `/admin/users/<id>/premium` (POST) -> entitlement mutation

Dependencies:

- `admin_required` decorator
- `User.is_premium`
- CSRF-protected form POST
- Admin mutation rate limit

## 3) Template/Client Dependency Map

Base layout and nav:

- `templates/base.html`
  - contains nav links and global CSRF meta token:
    - `<meta name="csrf-token" ...>`

Game clients:

- `templates/games/sequence-memory.html`
- `templates/games/box-adding.html`
- `templates/games/color-word.html`
- `templates/games/speed-dart.html`

Each game template:

- starts session -> POST `/api/session/start`
- ends session -> POST `/api/session/<id>/end`
- includes `X-CSRFToken` header from base meta token
- sends normalized payload shape:
  - `score`
  - `accuracy`
  - `rounds_completed`
  - `avg_response_time_ms`

Billing UI:

- `templates/upgrade.html` -> upgrade CTA + provider hints
- `templates/base.html` upgrade button routes to `/upgrade`

## 4) Data Model Dependency Map (database.py)

Core entities:

- `User`
- `GameType`
- `GameSession`
- `CognitiveScore`
- `DailyChallenge`
- `Leaderboard`

Critical relationships:

- `User` 1 -> many `GameSession`
- `User` 1 -> many `CognitiveScore`
- `GameType` 1 -> many `GameSession`
- `DailyChallenge` references `GameType`
- `Leaderboard` references `User`

Premium entitlement field:

- `User.is_premium` controls premium gates in route access checks

## 5) External Dependencies And What They Control

- `Flask`: routing/templates/request lifecycle
- `Flask-Login`: auth/session identity
- `Flask-WTF` CSRF: POST CSRF enforcement
- `Flask-Limiter`: route-level throttling
- `Flask-SQLAlchemy` + `SQLAlchemy`: ORM/persistence
- `Flask-Migrate` + `Alembic`: schema migrations
- `stripe`: checkout and webhook verification (when enabled)

## 6) Environment Variable Dependency Map

Security/runtime:

- `APP_ENV`
- `DEBUG`
- `SECRET_KEY`
- `DATABASE_URL`
- `SESSION_COOKIE_SECURE`
- `REMEMBER_COOKIE_SECURE`
- `SESSION_COOKIE_SAMESITE`
- `WTF_CSRF_SSL_STRICT`
- `WTF_CSRF_TIME_LIMIT_SECONDS`
- `SESSION_LIFETIME_MINUTES`

Rate limits:

- `RATE_LIMIT_ENABLED`
- `RATE_LIMIT_LOGIN`
- `RATE_LIMIT_REGISTER`
- `RATE_LIMIT_ADMIN_MUTATIONS`
- `RATE_LIMIT_UPGRADE_CHECKOUT`
- `RATELIMIT_STORAGE_URI`
- `RATELIMIT_STRATEGY`

Billing:

- `BILLING_PROVIDER` (`dev` or `stripe`)
- `STRIPE_SECRET_KEY`
- `STRIPE_PRICE_ID`
- `STRIPE_WEBHOOK_SECRET`

## 7) Tests As Dependency Contracts

- `tests/test_cognitive_regression.py`
  - cognitive score regressions, peak/peak-1 window behavior
- `tests/test_session_payload_validation.py`
  - API payload trust boundaries, CSRF on session APIs, premium gating parity
- `tests/test_admin_premium_controls.py`
  - admin-only entitlement mutation + CSRF
- `tests/test_upgrade_flow.py`
  - `/upgrade` auth gate + checkout behavior in `dev` provider

## 8) Change Impact Checklist

When editing these areas, check related dependencies:

- If editing premium access logic:
  - update `user_has_premium_access(...)`
  - verify `/play`, `/try`, `/api/session/start`, `/api/session/<id>/end`
  - verify admin entitlement endpoint and upgrade routes

- If editing game payload fields:
  - update server validators
  - update all game templates posting session payloads
  - update session payload tests

- If editing cognitive weights/scoring:
  - preserve weight contract invariants
  - update baseline map/version when needed
  - run cognitive regression tests

- If editing billing provider logic:
  - verify `/upgrade`, checkout, success/cancel, webhook
  - verify fallback `dev` provider behavior
  - verify premium entitlement transitions

## 9) Recommended Navigation Sequence For New Work

1. Read `app.py` for runtime and env behavior.
2. Read relevant route group in `routes.py`.
3. Trace to template in `templates/`.
4. Confirm impacted model fields in `database.py`.
5. Inspect matching tests in `tests/`.
6. Verify migration implications in `migrations/`.
