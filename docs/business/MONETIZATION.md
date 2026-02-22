# MONETIZATION

## Purpose
Define pricing, packaging, and entitlement rules tied to measurable user outcomes.

## Current Decision
`Adopted on 2026-02-21`

## Open Questions
- What price point maximizes retained paid users at day 30?
- Which premium reports create highest conversion from active free users?

## Owner
`Chris`

## Last Updated
`2026-02-21`

## Next Review
`2026-02-28`

## Plan Structure
- Free (Unregistered): `Limited rotating g-factor games`, `session outcome only`, `no long-term personalized analytics history`.
- Free (Registered): `Full g-factor game catalog`, `general cognitive dashboard and trends`, `1 industry preview challenge/week`.
- Premium: `Full industry-specific games`, `full role-specific analytics and benchmarks`, `priority access to new industry tracks`.

## Pricing
- Billing cadence: `Monthly + Annual`
- Price points: `TBD during pricing tests`
- Trial policy: `Optional 7-day premium trial for registered users`
- Refund policy: `TBD (define before public paid launch)`

## Entitlement Matrix
| Capability | Unregistered Free | Registered Free | Premium |
|---|---|---|---|
| Play g-factor games | Limited rotating set | Full | Full |
| View g-factor data | Session-only | Full general dashboard | Full general dashboard |
| Play industry games | No | Preview: 1 challenge/week | Full |
| View industry-specific data | No | Locked (teaser only) | Full |
| Long-term history/export | No | General history only | General + industry history/export |

## Upgrade Triggers
- Trigger event 1: `User completes >= 3 g-factor sessions in 7 days and hits locked industry challenge/report.`
- Trigger event 2: `User finishes weekly industry preview and requests role-specific feedback.`
- Trigger event 3: `User attempts to access industry benchmark comparison or full role track.`

## Entitlement Rules
- Gate by game access: `Industry-specific games are premium-only except weekly free preview.`
- Gate by analytics depth: `General cognitive analytics are free for registered users; role-specific analytics are premium-only.`
- Gate by history/export: `Industry history and export features are premium-only.`

## Monetization Metrics
- Visit to paid conversion: `Track weekly; initial benchmark to be set after baseline period`
- Registered to paid conversion: `Track weekly; target set after first pricing test cycle`
- Retained paid D30: `Primary monetization quality metric`
- ARPU: `Track monthly`
- Churn: `Track monthly with focus on first 30-day churn`

## Decision Log
- `2026-02-21`: `Set consumer monetization: free g-factor gameplay/data, premium industry-specific gameplay/data, with weekly free industry preview as upgrade bridge.`
