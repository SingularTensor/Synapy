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
  - `box-adding` baseline level: `3`
  - `color-word` baseline level: `12`
