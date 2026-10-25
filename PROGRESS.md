# PROGRESS: Toran

## Status
- Current task: T06
- Last green commit: T05 budget engine
- Last submission tag:
- Live link:

## Session log
Copy the template below for each session, newest first.

<!--
### Session N
- Task(s):
- Done:
- Checks: ruff / mypy / pytest:
- Decisions:
- Problems and gotchas (add repeats to CLAUDE.md):
- Next:
-->

### Session 2
- Task(s): per-plate price choices (follow-up to T04 and T05)
- Done: catering and invitations get per-plate ranges by city type and tier; warnings now carry typical low and high; city_tiers.json maps cities to a type only.
- Checks: ruff clean, mypy strict clean, 105 tests passing.
- Decisions: event-wide per-plate lines use the standard tier and event guests.
- Next: T06 Timeline engine.

### Session 1
- Task(s): T01 to T05
- Done: git repo, scaffold and tooling, env settings, domain models, reference data with validated loader, budget engine (allocate, what-if, realism warnings), engine boundary tests.
- Checks: ruff clean, mypy strict clean, 95 tests passing, 96.8% coverage.
- Decisions:
  - Money is integer rupees; every split uses largest remainder so totals are exact.
  - IST is a fixed UTC+05:30 offset, so no tzdata dependency.
  - `LineItem.locked` is forced by status (booked or paid locks, cancelled unlocks) in a before-validator.
  - Function gained a `tier` field so tier changes and change_tier ops have something to act on.
  - Category weights are integer percents; venue tier multipliers live in categories.json.
  - City type and function tier drive `realism_warnings`: per-plate price ranges (budget, standard, premium for metro, tier2, tier3) replaced the single per-guest floor. They warn only; they never change the allocation.
  - Engines import only models and the reference data types; a boundary test enforces no ai, api, planner, config or I/O imports.
  - Runtime deps pinned so far: fastapi, pydantic, pydantic-settings, uvicorn. google-genai, jinja2 and slowapi get added in the tasks that first use them.
- Problems and gotchas:
  - Starlette's TestClient warns that httpx is deprecated in favour of httpx2. Harmless for now; revisit before CI.
  - `model_copy(update=...)` skips validation, so engines must rebuild the Plan (which re-runs its validators) after changes.
- Next: T06 Timeline engine.
