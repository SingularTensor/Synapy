# KPI_SCORECARD

## Purpose
Track the 90-day growth loop around Meaningful Gameplay DAU with hard quality guardrails.

## Current Decision
`Adopted on 2026-02-21`

## Open Questions
- Is instrumentation complete enough to trust DAU and retention daily?
- Which channels add DAU without degrading guardrails?

## Owner
`Chris`

## Last Updated
`2026-02-21`

## Next Review
`2026-02-28`

## KPI Tree
- North Star: `Meaningful Gameplay DAU`
- Acquisition: `new users/day`, `visit to signup`
- Activation: `signup to first session completion`, `time to first completed session`
- Engagement: `% DAU with >= 3 sessions/day`, `sessions per DAU`
- Retention: `D1`, `D7`, `D30`
- Revenue (secondary for this phase): `registered to paid`, `retained paid at day 30`
- Strategic data output: `qualified data pairs/day`

## Metric Definitions
- `meaningful_gameplay_dau`: `Unique users per calendar day with >= 1 completed puzzle session.`
- `new_user`: `First-seen user account or device id in product analytics.`
- `first_session_completion_rate`: `New users who complete first puzzle session / all new users.`
- `engaged_dau_rate`: `DAU with >= 3 completed sessions / Meaningful Gameplay DAU.`
- `retained_user_D7`: `New users active again on day 7 (or in day 7 window).`
- `qualified_data_pairs`: `Daily count of cross-platform relational pairs that pass quality checks.`
- `retained_paid_D30`: `Paid users still active at day 30.`

## Targets
- 30-day targets: `instrumentation coverage >= 95% of core events`, `first_session_completion_rate >= 60%`, `engaged_dau_rate >= 30%`
- 60-day targets: `D7 retention >= 20%`, `sessions per DAU trending up week-over-week`
- 90-day targets: `Meaningful Gameplay DAU materially above baseline while all guardrails are met`, `qualified_data_pairs/day above baseline and stable`

## Data Source Mapping
- Product analytics: `App event stream (session start/end, puzzle completion, repeat sessions)`
- Billing system: `Subscription provider or payment table`
- CRM/marketing: `Campaign tracking source of signup`

## Weekly Review Notes
- Week of `YYYY-MM-DD`: `[Wins, losses, decisions]`

## Decision Log
- `2026-02-21`: `Set scorecard around Meaningful Gameplay DAU and quality guardrails for a 90-day push.`
