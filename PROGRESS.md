# PROGRESS: Toran

## Status
- Current task: T14
- Last green commit: T13 Adapt options
- Last submission tag:
- Repo: https://github.com/BunnyPraneeth5/toran-event-planner (public, CI on every push)
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

### Session 7
- Task(s): free-tier key check, T12 live check, T13 Adapt options
- Done: key works again on the free tier (billing removed from the project); T12 live check passed; built adapt_options and apply_option with verified, engine-completed Gemini options and rule-based fallback.
- Checks: ruff clean, mypy strict clean, 307 tests passing.
- Live findings:
  - gemini-3.8-flash is still overloaded (503, 429, or a hang); the lite fallback answered every time.
  - The lite model chooses sensible fixes but under-sizes them (for example a 45 percent catering trim for a 5 lakh gap). The engine now completes such options instead of rejecting them. After that change, a cut from 25 to 20 lakh got three distinct Gemini options, all verified.
- Decisions:
  - complete_option: Gemini picks the direction, the engine appends an even trim (within five ops) to close the gap, then verifies.
  - Replacement line and task ids for a cancelled vendor are derived from the cancelled line ("<id>-r", "<id>-t") so apply recreates them.
  - No AI call when a change causes no overrun and no newly late tasks.
- Suggestion for the user: set GEMINI_MODEL=gemini-3.6-flash in .env while 3.8-flash stays overloaded (it answered generate in about 10 seconds with richer ideas).
- Follow-up: the single fallback became an ordered chain, GEMINI_FALLBACK_MODELS (default gemini-3.6-flash, then gemini-3.5-flash-lite), with gemini-3.8-flash kept as the main model. Live: 429 then 503 then lite answered in 3.9s; 429 then 3.6-flash answered in 7.6s.
- Next: T14 API routes, then T14a early Render deploy.

### Session 6
- Task(s): daily AI cap, T12 Generate
- Done: AI_DAILY_CALL_LIMIT (default 500) counts every Gemini request per IST day and falls back with a "resets at midnight IST" banner; generate turns Gemini's proposal (functions with day offsets and guest shares, category weights, ideas) into a full plan through place_functions, sanitize_weights, allocate and build_tasks; template plan as fallback.
- Checks: ruff clean, mypy strict clean, 290 tests passing, CI green.
- Decisions:
  - Generate gets a CompleteBrief (every required field non-optional), so validation, not asserts, guarantees completeness.
  - Gemini proposes day offsets and guest percentages; the engine computes dates and guest counts.
  - Ideas that mention prices are dropped with a notice; ideas for an unknown function become event-wide.
  - Template choice: the event type's template whose first label word appears in the title or notes, else the first one. The North Indian wedding template is now first as the neutral default.
  - GENERATE_MAX_TOKENS is 8192 because thinking tokens count against it.
- Blocked: live generate check. Every model returns HTTP 402 "prepayment credits are depleted" for the key's AI Studio project. The fallback plan works and was checked live (sums exact, dates right, 23 tasks).
- Next: T13 Adapt options (AI).

### Session 5
- Task(s): verify Gemini access, T11 Intake
- Done: confirmed the key can use gemini-3.8-flash and gemini-3.5-flash-lite (both stable); built intake (flat BriefDraft schema, fenced prompt, planner.intake with engine conversion, questions for missing fields, fallback form); live-checked four messages against Gemini.
- Checks: ruff clean, mypy strict clean, 259 tests passing, 97.5% coverage, CI green.
- Live findings:
  - gemini-3.8-flash, 3.7-flash and flash-latest often returned 503 (high demand) or a 504 after about 24 seconds; gemini-3.5-flash-lite answered every time in 1.3 to 2.3 seconds.
  - Real outputs: "25 lakh" came back as 25 + "lakh" and the engine made 2,500,000; a missing day became "Which day in March 2027?"; a poem request was rejected politely; an injection with a fake closing tag was ignored.
- Decisions:
  - Intake runs on the lite model; generate and adapt stay on the main model.
  - GEMINI_FALLBACK_MODEL (default gemini-3.5-flash-lite) is tried once on 429, 5xx or a hang; the main model gets at most half the deadline while a fallback exists. SDK retries are off.
  - Gemini never asks about type, city, date, guests or budget; the planner asks those itself, in a fixed order, then adds Gemini's own questions up to three.
- Problems and gotchas:
  - T10 bug found live: the SDK client was garbage collected and closed its HTTP connection. Now cached so it stays alive.
  - The fence regex first swallowed text after an unclosed lookalike tag; it now strips only the tag token.
  - Writing regex strings through a shell heredoc into Python corrupted `` into a backspace. Edit regex code with the editor, not heredocs.
- Next: T12 Generate.

### Session 4
- Task(s): publish repo, early CI, privacy scrub, checkpoint tasks
- Done: removed Andhra Pradesh and nearby Telangana town names from every commit before publishing (tier-3 test city is now Jodhpur); created the public GitHub repo and pushed main; CI runs ruff, mypy, pytest with coverage floor and pip-audit on every push; added T14a (early Render deploy), T16a (try a sample event, user picks the city or the browser finds the nearest one) and T18a (video script, owner: you).
- Checks: CI green on GitHub; 226 tests passing locally.
- Decisions: the pre-scrub history is kept only in a local branch `backup/pre-scrub`, never pushed; delete it once you are happy.
- Next: T11 Intake, after the Gemini key is in .env.

### Session 3
- Task(s): T06 to T10
- Done: timeline engine (backward schedule, late and at-risk), ledger engine (exact payer splits), parse and sanitize engines (fixture driven), adapt engine (apply change, impact, apply ops, verify option, rule-based options), Gemini wrapper with fakes.
- Checks: ruff clean, mypy strict clean, 226 tests passing, 97.3% coverage, pip-audit clean on runtime deps.
- Decisions:
  - Late means the due date has passed; at risk means the work can no longer be ready before its function. When the ideal due date is already past, the task is due today and shows as at risk.
  - Ledger gap is assigned minus pledged (positive means assigned more than pledged).
  - Sanitize renames a reused function name on another day or time ("Puja 2") and drops exact repeats.
  - A change is measured without rebalancing (`what_if(..., rebalance=False)`), so the problem is visible before any fix. Options are verified: ops apply, locked lines untouched, nothing over budget, no new late or at-risk tasks.
  - A cancelled vendor gets a replacement line at the same planned amount plus a "Find a replacement" task. No rush surcharge is modelled.
  - Dropping a function frees its open lines; booked or paid lines stay as event-wide costs.
  - Rule-based options trim the largest open categories (at most five, at most 90 percent), protect catering, or move the costliest function down a tier.
  - Gemini wrapper: async SDK, one overall deadline, one retry only on invalid output with at least 3 seconds left, unexpected finish reasons count as invalid.
  - Runtime deps added: google-genai 2.33.0 and httpx 0.28.1 (httpx was already a transitive dependency, now pinned because app code catches its errors).
- Problems and gotchas:
  - Fixed a T05 gap found while testing T09: event-wide per-plate lines (invitations and return gifts) now scale with the event guest count.
  - Writing files from Python on Windows adds CRLF; .gitattributes normalizes on commit, but never stage a raw blob with `git hash-object` without `--path`.
- Open items for later tasks:
  - ARCHITECTURE says model names are checked at startup. Not built yet; fits T14 (health) or T20.
- Next: T11 Intake.

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
