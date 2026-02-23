# BILLING_RUNBOOK

## Purpose
Operational guide for Stripe billing in Synapy.


## Scope
Use this for:
1. Webhook setup and validation.
2. Billing incident triage.
3. Manual state reconciliation (`flask billing reconcile`).


## Required Environment
Set these in the running environment:
1. `BILLING_PROVIDER=stripe`
2. `STRIPE_SECRET_KEY=<sk_...>`
3. `STRIPE_PRICE_ID=<price_...>`
4. `STRIPE_WEBHOOK_SECRET=<whsec_...>`
5. `APP_ENV=production` in production
6. `SECRET_KEY=<strong-random-value>`


## Stripe Webhook Events
Enable these destination events:
1. `checkout.session.completed`
2. `customer.subscription.updated`
3. `customer.subscription.deleted`
4. `invoice.payment_failed`


## Endpoint URL
Use:
1. `https://<your-host>/api/billing/stripe/webhook`

Local-only testing (no domain yet):
1. `stripe listen --forward-to localhost:5000/api/billing/stripe/webhook`
2. Copy the CLI-provided `whsec_...` into `STRIPE_WEBHOOK_SECRET`.


## Quick Validation
1. Start app.
2. Start forwarding (local) or configure Stripe Dashboard endpoint (staging/prod).
3. Trigger events from Stripe CLI:

```powershell
stripe trigger checkout.session.completed
stripe trigger customer.subscription.updated
stripe trigger customer.subscription.deleted
stripe trigger invoice.payment_failed
```

4. Confirm HTTP `200` on webhook deliveries.
5. Confirm app-side state changes in admin billing diagnostics (`/admin`).


## Reconcile Command
Manual reconciliation command:

```powershell
.\.venv\Scripts\flask.exe --app app billing reconcile --dry-run
.\.venv\Scripts\flask.exe --app app billing reconcile
.\.venv\Scripts\flask.exe --app app billing reconcile --user-id 123
.\.venv\Scripts\flask.exe --app app billing reconcile --limit 500
```

Behavior:
1. Skips when `BILLING_PROVIDER` is not `stripe`.
2. Uses Stripe API as source of truth for premium state.
3. `--dry-run` prints planned changes without database writes.


## Suggested Ops Cadence
1. Run `--dry-run` during incident triage first.
2. Run real reconcile when drift is confirmed.
3. Schedule periodic reconcile (daily or every few hours) once deployed.


## Triage Checklist
1. Confirm webhook endpoint URL is correct and reachable.
2. Confirm `STRIPE_WEBHOOK_SECRET` matches current destination.
3. Confirm required event types are enabled in Stripe.
4. Check app logs for webhook signature or processing errors.
5. Check `/admin` billing diagnostics for recent webhook event IDs and types.
6. Run reconcile (`--dry-run`, then real).


## Common Failure Modes
1. `400 Invalid signature`
Cause: wrong `STRIPE_WEBHOOK_SECRET`.
Fix: copy current endpoint signing secret and restart app.

2. `503 Stripe webhook is not configured`
Cause: missing `STRIPE_SECRET_KEY` or `STRIPE_WEBHOOK_SECRET`.
Fix: set env vars and restart app.

3. Event delivery succeeds but user state is wrong
Cause: mapping mismatch or missed events.
Fix: run `billing reconcile` and inspect `billing_status`, `stripe_customer_id`, `stripe_subscription_id`.

4. `flask` command not found on Windows
Cause: shell not using venv executable path.
Fix: use `.\.venv\Scripts\flask.exe --app app ...`


## Notes
1. Dev mode can use `BILLING_PROVIDER=dev` to bypass real Stripe charge flow.
2. Production should always use `BILLING_PROVIDER=stripe`.
