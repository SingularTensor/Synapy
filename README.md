# Synapy

Synapy is a mobile-first cognitive training web application built with Flask. Players complete short browser games, receive performance feedback, and can track their progress over time.

## Features
- **Playable game templates today:** `sequence-memory`, `speed-dart`, `box-adding`, `color-word`. Additional game slugs can appear as **Coming Soon** until templates are implemented.
- **Performance metrics pipeline:** Authenticated sessions track `score`, `accuracy`, `rounds_completed`, and `avg_response_time_ms`, then feed XP and cognitive trait recomputation.
- **Server-side access gating:** Premium access is enforced on `/try/<slug>`, `/play/<slug>`, `/api/session/start`, and `/api/session/<id>/end`.
- **Access tiers:**
  - *Unregistered Free:* Browse the catalog and play currently available free games in guest mode (no persisted session history or XP).
  - *Registered Free:* Access currently available free games with persisted sessions, XP progression, lives/streak systems, and `/dashboard`.
  - *Paid Premium:* Registered-free capabilities plus premium-gated game access and premium entitlements as premium templates/analytics roll out.
- **Dashboard:** The trait chart uses live `cognitive_scores`; several top KPI/history cards are currently placeholder/demo values.

## Project Documentation

For implementation details, see:

- `docs/PUZZLE_DESIGN.md` for game mechanics and tracked metrics.
- `docs/DEPENDENCY_MAP.md` for the application structure.
- `docs/BILLING_RUNBOOK.md` for Stripe webhook and reconciliation operations.

## Tech Stack
- **Backend:** Flask (Python)
- **Database:** SQLite & SQLAlchemy
- **Frontend structure:** HTML/Vanilla JS/CSS logic within Jinja templates

## Quickstart

```bash
# 1. Activate virtual environment (Windows)
.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Apply database migrations
flask --app app db upgrade

# 4. Seed the database with initial game types (local reset workflow)
python seed.py

# 5. Run the Flask development server
python app.py
```

Then visit `http://127.0.0.1:5000` in your browser.

## Environment Hardening

Security settings are environment-driven, so dev stays easy while production can be strict.

```bash
# environment mode
APP_ENV=production

# required in production
SECRET_KEY=replace-with-long-random-secret
DATABASE_URL=sqlite:///synapy.db

# runtime toggles
DEBUG=false
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=Lax
WTF_CSRF_SSL_STRICT=true
SESSION_LIFETIME_MINUTES=10080

# rate limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_LOGIN="20 per minute"
RATE_LIMIT_REGISTER="10 per minute"
RATE_LIMIT_ADMIN_MUTATIONS="30 per minute"
RATE_LIMIT_UPGRADE_CHECKOUT="10 per minute"
RATELIMIT_STORAGE_URI=memory://

# billing provider
BILLING_PROVIDER=dev
# set BILLING_PROVIDER=stripe in production and configure:
STRIPE_SECRET_KEY=
STRIPE_PRICE_ID=
STRIPE_WEBHOOK_SECRET=
# optional billing alert webhook (Slack/ops relay, etc.)
BILLING_ALERTS_ENABLED=true
BILLING_ALERT_WEBHOOK_URL=
BILLING_ALERT_TIMEOUT_SECONDS=3
```

In development, defaults are intentionally looser and do not require `SECRET_KEY`.

## Database Migrations

```bash
# create a new migration after model changes
flask --app app db migrate -m "describe change"

# apply pending migrations
flask --app app db upgrade
```

If you already have an existing local database created before migrations were introduced and
its schema already matches the models, stamp it once:

```bash
flask --app app db stamp head
```

## Credits

| Name | Role |
|------|------|
| Chris | Technical Product Lead / Chief Agent Officer |
| Claude Opus 4.6 | Software Architect / Full-Stack Engineer |
| GPT CODEX 5.3 | Game Systems Engineer |
| Gemini 3.1 Pro w/ Antigravity | UI / Frontend Engineer |
