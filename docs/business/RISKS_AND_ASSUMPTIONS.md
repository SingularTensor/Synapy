# RISKS_AND_ASSUMPTIONS

## Purpose
Track top business risks and assumptions with explicit mitigation plans.

## Current Decision
`Adopt this file as the canonical technical+product risk backlog for v1 launch readiness.`

## Open Questions
- Do we gate premium access with a paid-user flag before opening external traffic?
- What level of server-side score validation is required before leaderboards are considered trusted?
- Do we require CSRF protection before public beta, or before first paid tier launch?

## Owner
`Product + Engineering`

## Last Updated
`2026-02-22`

## Next Review
`2026-03-01`

## Critical Assumptions
- A1: Server-side route checks will enforce access tiers even if clients are modified.
- A2: Session payload metrics sent by the browser are sufficiently trustworthy for XP and trait scoring.
- A3: Users will trust dashboards even when some KPI cards are still placeholder/demo values.

## Risk Register
| ID | Risk | Likelihood | Impact | Early Signal | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|---|
| R-TECH-001 | Premium access bypass risk: `/play/<slug>` does not currently enforce premium entitlement checks. | `High` | `High` | Non-paying users show game sessions for premium slugs. | Add backend entitlement guard for `/play`, `/api/session/start`, and `/api/session/<id>/end`; add access-control tests. | `Backend` | `Open (P0)` |
| R-TECH-002 | Score integrity risk: session API trusts client-submitted `score`, `accuracy`, `rounds_completed`, and `difficulty`. | `High` | `High` | Abnormal score/XP outliers and unrealistic difficulty values in sessions. | Enforce server-side bounds and anti-tamper checks; reject invalid payloads; add anomaly monitoring. | `Backend + Data` | `Open (P0)` |
| R-TECH-003 | CSRF risk on form/API POST routes (auth/session endpoints currently lack explicit CSRF protection). | `Medium` | `High` | Unexpected account actions or unexplained session spam. | Implement CSRF protection (token-based), enforce SameSite cookies, and add route-level tests. | `Backend + Security` | `Open (P1)` |
| R-TECH-004 | Production safety risk: app can run with `debug=True` and non-persistent random `SECRET_KEY` fallback. | `Medium` | `High` | Session invalidation after restart; accidental debug exposure in deploy environment. | Require env-provided persistent `SECRET_KEY`; block debug in non-dev; add startup config checks. | `Platform` | `Open (P1)` |
| R-PROD-001 | Product trust risk: dashboard combines real trait data with hardcoded demo KPI values. | `Medium` | `Medium` | User-reported mismatch between gameplay history and top-card metrics. | Replace hardcoded KPI cards with computed values or explicitly mark as demo until live. | `Product + Frontend` | `Open (P2)` |

## Validation Plan
- Test 1: `R-TECH-001 -> direct-route entitlement tests for premium slugs -> 2026-02-24`
- Test 2: `R-TECH-002 -> payload tampering tests (score/difficulty extremes) -> 2026-02-24`
- Test 3: `R-TECH-003 -> CSRF attack simulation on auth/session POST endpoints -> 2026-02-28`
- Test 4: `R-PROD-001 -> dashboard consistency check against real session aggregates -> 2026-03-01`

## Decision Log
- `2026-02-22`: Added initial major-risk backlog from code quality and risk review.
- `2026-02-22`: Prioritized P0: premium access control and score integrity ahead of feature expansion.
