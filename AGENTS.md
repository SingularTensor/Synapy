# AGENTS.md

## Cognitive Weight Contract (Mandatory)

When editing cognitive trait mappings in `routes.py`:

1. Per-game trait weights must sum to `5.0`.
2. Each game must include at least one trait with weight `0.0`.
3. No trait weight may exceed `3.0`.
4. Bump `COGNITIVE_WEIGHT_VERSION` whenever weights change.

### Canonical Source

- `GAME_COGNITIVE_WEIGHTS` in `routes.py`
- `validate_game_cognitive_weights(...)` in `routes.py`
- `GAME_BASELINE_LEVELS` in `routes.py` for early-stage normalization anchors

### Required Follow-up After Weight Changes

1. Run syntax check:
   - `python -m py_compile routes.py`
2. Rebaseline/backfill existing `cognitive_scores` if historical consistency is required.

### New Game Mode Checklist

1. Add a `GameType.slug` entry (seed or migration) so it appears in `/problems`.
2. Add matching `templates/games/<slug>.html` so `/try/<slug>` and `/play/<slug>` render.
3. Add the slug to `GAME_COGNITIVE_WEIGHTS` and `GAME_BASELINE_LEVELS` in `routes.py`.
4. Ensure client payload includes `score`, `accuracy`, `rounds_completed`, and `avg_response_time_ms`.

### Migration TODO (Later)

- Internal cognitive key renames are deferred:
  - Current internal key: `verbal_fluency`
  - Desired internal key: `verbal_comprehension`
  - Current internal key: `pattern_recognition`
  - Desired internal key: `spatial_reasoning`
- Keep user-facing labels as **Verbal Comprehension** for now.
- When migrating later:
  1. Update code references (`routes.py`, dashboard mapping, and domain constants).
  2. Run one-time data migration for `cognitive_scores.domain` values.
  3. Keep temporary backward-compat aliasing during rollout, then remove.

### Scoring Intent

- Use progression deltas (new personal-best levels), not repeat farming.
- Use game normalization (`percentile` + `z_score` blend) for cross-game comparability.
- Trait recompute only considers sessions at personal peak and `peak-1` per game (`TRAIT_RETRY_WINDOW_BELOW_PEAK`), so deeper under-peak retries cannot lift trait score.
- Breadth across games in the same trait should update confidence/tie-breaker (`session_count`), not inflate trait score by raw summation.
- Current calibration anchors:
  - `sequence-memory` baseline level: `4`
  - `speed-dart` baseline level: `5`
  - `box-adding` baseline level: `3`
  - `color-word` baseline level: `12`


## Agent Safety Rails (Mandatory For All Tasks)

Before finalizing any code change, agents must run this preflight:

1. Access-control parity check:
   - If a game route or API route is touched, verify access rules stay consistent across:
     - `/play/<slug>`
     - `/try/<slug>`
     - `/api/session/start`
     - `/api/session/<id>/end`
2. Client-payload trust check:
   - Treat browser metrics as untrusted input.
   - Validate expected fields and ranges server-side (`score`, `accuracy`, `rounds_completed`, `avg_response_time_ms`, `difficulty`).
3. Cognitive scoring integrity check:
   - Confirm changes do not bypass `validate_game_cognitive_weights(...)`.
   - Confirm `TRAIT_RETRY_WINDOW_BELOW_PEAK` behavior is preserved unless explicitly requested.
4. Live vs demo data check:
   - If editing dashboard or profile views, state whether each metric is computed live or is placeholder/demo.
5. Verification check:
   - Run available syntax/tests.
   - If execution is blocked by environment, explicitly report what could not be run.


## High-Risk Hotspots (Review Before Editing)

1. `routes.py` -> `play_game(...)` and `try_game(...)`
   - Risk: inconsistent premium gating between authenticated and guest flows.
2. `routes.py` -> `start_session(...)` and `end_session(...)`
   - Risk: trusting client-submitted scoring fields without strict server validation.
3. `routes.py` -> cognitive scoring functions
   - Risk: subtle regressions in normalization and peak-window logic.
4. `templates/dashboard.html`
   - Risk: mixing hardcoded/demo KPI cards with live cognitive data can mislead users and agents.
5. `seed.py`
   - Risk: `drop_all()` is destructive and intended only for local reset workflows.


## Naming And Alias Guardrails

- Internal domain key `verbal_fluency` currently maps to user-facing label `Verbal Comprehension`.
- Internal domain key `pattern_recognition` currently maps to user-facing label `Spatial Reasoning`.
- Do not rename internal keys ad hoc.
- Any key rename requires:
  1. coordinated code update,
  2. data migration plan,
  3. temporary backward-compat alias.


## Agent Definition Of Done

A change is not done until all are true:

1. The requested feature/fix is implemented.
2. Relevant risk rails above were checked.
3. Any touched invariants are documented in code or docs.
4. Verification results are reported (or blocked checks are called out explicitly).
