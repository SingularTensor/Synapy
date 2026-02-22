# AGENT_PLAYBOOK

## Purpose
Operational guide for AI agents working in this repository. Use this with `AGENTS.md`.


## Fast Start

1. Read:
   - `AGENTS.md`
   - `CLAUDE.md`
   - `docs/business/RISKS_AND_ASSUMPTIONS.md`
2. Identify task type:
   - game mechanic change,
   - scoring change,
   - auth/access change,
   - UI/dashboard change.
3. Apply relevant checklist below before edits and before final response.


## Checklists By Task Type

### A) Game Mechanic Or New Game

1. Ensure slug exists in seed/migration and appears in `/problems`.
2. Ensure template exists at `templates/games/<slug>.html`.
3. Ensure session payload sends:
   - `score`,
   - `accuracy`,
   - `rounds_completed`,
   - `avg_response_time_ms`.
4. If cognitive domains are affected, update:
   - `GAME_COGNITIVE_WEIGHTS`,
   - `GAME_BASELINE_LEVELS`,
   - `COGNITIVE_WEIGHT_VERSION`.
5. Run `python -m py_compile routes.py` when possible.


### B) Cognitive Scoring Logic

1. Preserve contract:
   - per-game weights sum to `5.0`,
   - at least one `0.0` trait per game,
   - no trait above `3.0`.
2. Keep `validate_game_cognitive_weights(...)` active.
3. Keep intent: progression deltas and peak/peak-1 retry window.
4. Update regression tests when scoring behavior changes.
5. Flag if rebaseline/backfill of historical `cognitive_scores` is needed.


### C) Auth, Access, Or Session APIs

1. Keep access parity across:
   - `/play/<slug>`,
   - `/try/<slug>`,
   - `/api/session/start`,
   - `/api/session/<id>/end`.
2. Do not trust browser payloads.
3. Validate ranges/types on server before persistence.
4. Verify changes for both authenticated and unauthenticated users.


### D) Dashboard Or Analytics UI

1. Mark whether each displayed metric is:
   - live computed data, or
   - placeholder/demo.
2. Avoid implying precision for placeholder metrics.
3. Keep domain label mapping consistent with internal alias keys.


## Known Alias Map (Do Not Rename Casually)

- Internal: `verbal_fluency` -> Label: `Verbal Comprehension`
- Internal: `pattern_recognition` -> Label: `Spatial Reasoning`


## Known Hotspots

1. `routes.py` session endpoints: easy to introduce client-trust bugs.
2. `routes.py` play/try routes: easy to create premium gating drift.
3. `templates/dashboard.html`: easy to mix demo and live metrics without clear labeling.
4. `seed.py`: destructive reset behavior by design.


## Final Response Requirements For Agents

1. State what changed.
2. State what was verified.
3. State what could not be verified and why.
4. Mention risk tradeoffs when relevant.
