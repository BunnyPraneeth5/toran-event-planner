# PROGRESS: Toran

## Status
- Current task: review of T24 to T27, then push, check the deployed commit, tag the release; T18a video script is yours
- Last green commit: T20 Security middleware
- Last submission tag:
- Repo: https://github.com/BunnyPraneeth5/toran-event-planner (public, CI on every push)
- Live link: https://toran-event-planner.vercel.app (Vercel Hobby, Mumbai region)

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

### Session 11
- Task(s): T14a leftover, T16, T16a, T17, T18, T19, T20
- Done:
  - T14a: the app treats Vercel's own VERCEL_ENV=production as production, so `/docs` and `/openapi.json` are 404 on the live site without depending on the dashboard variable.
  - T16: dashboard (budget table with meters and share, functions with ideas, timeline with Late, At risk and Done labels, ledger with balances, keep your plan section) on the home page and a new `/plan` page; state.js saves the plan from every response, sends it with requests, sets aside plans from another schema version, warns on changes from another tab, asks for persistent storage, exports and imports (imports validated by the server).
  - T16a: one-click sample wedding built by the engines (no AI), 24 cities with prices per city type, optional in-browser nearest city, honest "sample" banner via a new `sample` source value.
  - T17: what-if sliders (total, guests, each category) and a tier select per function; one control per request; readouts and aria-valuetext update while dragging; focus kept and one announcement per settled change; booked categories shown as fixed.
  - T18: Something changed form for all five kinds, impact first, up to three verified options side by side, apply re-checked by the server.
  - T19: .ics export (all-day tasks, timed functions in UTC, stable UIDs, RFC 5545 escaping and folding) and a Google Calendar link per task.
  - T20: security headers and request ids on every response, 413 body cap (also for streamed bodies), slowapi limits on the three Gemini routes keyed on the first x-forwarded-for entry, gzip, static cache headers, generic 500s.
- Checks: ruff clean, mypy strict clean, 460 tests passing, 97.5% coverage, pip-audit clean, CI green. Browser checks at 390px for every task, including the full keyboard-only Something changed flow; no CSP violations with the strict policy on. Live on Vercel without AI calls: /docs 404, headers present, sample, dashboard, what-if, calendar file and 413 all work.
- Problems and gotchas:
  - A field inside a disabled fieldset still reports `field.disabled === false`; use `field.matches(":disabled")`. Found in the browser, not by server tests.
  - Test files in different folders must have different names (no package `__init__` files): `test_calendar_api.py`.
  - The local dev server can get stuck mid-reload after a burst of edits; restart it before trusting a browser check.
  - Exception handlers for 429 run inside the middleware stack (headers added there); only 500s run outside it.
- Decisions:
  - Google Calendar links live in `app/web/links.py`, not in engines (engines stay free of urllib).
  - Venue tier in what-if is a select, not a slider.
  - The sample's people are "Bride's family" and "Groom's family"; no real names, no Andhra Pradesh cities.
- Gaps to schedule: no UI yet to add people or assign payers (the ledger can only show them); no favicon (browsers log a 404).
- Next: T22 E2E and accessibility tests; T18a video script (yours).

### Session 10
- Task(s): CLAUDE.md hosting line, T15 UI base and intake page
- Done: base layout (landmarks, skip link, lang, one aria-live region, htmx config with eval and inline scripts off), hand-written CSS (mobile first, light and dark, visible focus, reduced motion), vendored htmx 2.0.11, app.js with the toran-json extension, error messages in the live region and focus moved to new headings, intake page, brief form with Needed fields and follow-up questions, fallback banners.
- Checks: ruff clean, mypy strict clean, 366 tests passing. Browser at 390px with the live key: intake filled Wedding, Pune, 300 guests and 20 lakh and asked only for the day; generate produced an AI plan of exactly 20 lakh with 4 functions and 22 tasks; no horizontal scroll; focus landed on each new heading.
- Problems and gotchas:
  - htmx with allowScriptTags false strips every script tag from swapped HTML, including JSON data blocks. The plan now travels in a hidden div's data-plan attribute; tests and docs updated.
  - A `.wrap` class rule overrode `main`'s padding (class beats element); fixed with `main.wrap`.
  - Shell heredocs keep mangling backslashes in Python and regex strings; use the editor for those edits.
- Decisions:
  - Our own toran-json htmx extension instead of json-enc: json-enc sends every value as a string (strict integers reject "400") and cannot nest `brief.*` fields.
  - Static paths are root-relative (`/static/...`), never url_for, so they stay correct behind Vercel's proxy.
- Next: T16 Dashboard page and state contract.

### Session 9
- Task(s): T14a early deploy (moved from Render to Vercel)
- Done: checked Render read-only and found every existing service on the account suspended for billing, so a new free service would likely be blocked too; compared hosts and chose Vercel (free, no card, fast wake-up, 300 second request limit, Mumbai region); you imported the repo with the FastAPI preset and set GEMINI_API_KEY and ENVIRONMENT in the dashboard; fixed the first live failure; updated ARCHITECTURE.md (hosting, deployment section, security notes) and TASKS.md (T14a rewritten for Vercel, T21 done without Docker, T27 now a Vercel release).
- Checks: ruff clean, mypy strict clean, 352 tests passing, CI green. Live: `/healthz` 200 with ai_configured true; recompute 200; HTMX partial renders with plan-state and Indian rupee formatting; about 0.4 seconds per request.
- Problems and gotchas:
  - First deploy failed on every route with FUNCTION_INVOCATION_FAILED: pyproject.toml had a [project] table with no dependencies, so Vercel installed nothing. Runtime dependencies are now listed there too, and a test keeps pyproject.toml and requirements.txt identical. Vercel redeployed in about 20 seconds after the push.
  - A wrong ENVIRONMENT value (for example "Production") crashes the app at startup, because the setting only accepts lowercase values.
- Open for you: `/docs` still loads on the live site, so the running app does not see ENVIRONMENT=production. Make sure the variable is scoped to Production, then redeploy.
- Decisions:
  - No Docker image; Cloud Run stays the documented upgrade path.
  - Daily AI cap and rate limits are in memory per serverless instance; acceptable while the key is on the free tier.
  - Every push to main deploys to production; submissions are tagged commits checked live.
- Next: T15 UI base and intake page.

### Session 8
- Task(s): T14 API routes
- Done: intake, generate, recompute, what-if, adapt options and adapt apply routes, each a thin call into the planner; one respond() helper returns JSON, or an HTML partial when HX-Request is set; minimal partials (brief, plan, options, banner, plan_state) with the plan-state JSON block; Indian rupee formatting filters.
- Checks: ruff clean, mypy strict clean, 350 tests passing, 97.2% coverage. Real-server check with the live key: all 7 routes served, generate returned an AI plan, the HTMX partial carried plan-state.
- Decisions:
  - Every plan-changing route returns PlanResponse (the plan plus budget, timeline and ledger views), so the UI never needs a second request.
  - Intake passes GEMINI_LITE_MODEL; generate and adapt pass GEMINI_MODEL (main model with the fallback chain).
  - Engine ValueErrors (unknown ids, a stale option) become 422 with the engine's message; Pydantic handles malformed, dangling and oversized plans.
  - Apply takes the original plan, the change and the option, and rejects any extra field, so a client-computed plan cannot be submitted.
  - Plan state goes into the page through Jinja's tojson, which escapes anything that could close the script tag.
  - Runtime dependency added: jinja2 3.1.6 (already listed in ARCHITECTURE.md).
- Next: T14a early Render deploy.

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

## Session 12
- T16b done: add people, change pledges, remove people (payers and task owners cleared, notice with count), one payer, equal split or percent split per line. Engine only, POST /api/people.
- T16c done: mark lines planned, booked or paid with actual cost; locks and task status follow; over-plan text counts towards the overrun. POST /api/lines.
- T16d done: contents panel (left rail on desktop, status bar on phones) with live statuses, overview with countdown, budget bar and action list, timeline and ideas folded, function time ranges, one-level undo, saved status, home hands new plans to /plan, live lakh display.
- T16e done: occasion palette (sindoor, marigold, turmeric, mehendi, peacock) in light and dark with every text pair at WCAG AA, toran garland header, marigold favicon, rangoli card corners, paisley dividers, one icon per budget category, Rozha One headings. Hand-made SVGs total about 6.5 KB.
- Checks: ruff, mypy and 596 tests green; browser checked at 375px and desktop in light and dark. Committed locally, not pushed.
- Every task from T01 to T21 is done except T18a (video script, yours). Waiting for review before pushing; then T22.
- T22 done: `pytest e2e` runs the real app in-process with a schema-routed fake Gemini. One flow at 390px and desktop (intake, questions, plan on /plan, what-if, budget cut, pick option, export, reload), a keyboard-only path through intake and adapt, axe scans on intake, brief, dashboard and adapt views, and a console-error check. New e2e CI job installs Playwright's Chromium; locally E2E_BROWSER_CHANNEL=chrome uses the installed browser.
- axe found a real issue: the scrollable tables could not be reached by keyboard on phones. They are now focusable, labelled regions.
- Committed locally, not pushed. Waiting for review.
- Pushed T22; CI green on both jobs (checks and e2e). Live site on the new deploy.
- T23 done: `python -m tests.evals.run_evals` runs six briefs (Telugu wedding, North Indian wedding, Hinglish, 5th birthday, society Ganesh, wedding three weeks away) through intake, generate and adapt on live Gemini. Checks schema, engine invariants and that every option re-applies within the cut budget; records model, latency and error per call. Not collected by pytest, not in CI. Result: 6 of 6 passed, twice.
- `--save` stored the live responses in tests/fixtures/ai/evals; tests/unit/test_eval_fixtures.py replays them offline (19 tests).
- Finding: on the free tier the Flash models (gemini-3.8-flash, gemini-3.6-flash) mostly returned 503 (overloaded) or 429 (quota); the fallback chain served almost every generate and adapt call from gemini-3.5-flash-lite.
- Committed locally, not pushed. Waiting for review.
- Pushed T23; CI green on both jobs.
- T24 to T26 done in one commit (as agreed): README (problem, persona, features, Mermaid diagram, where Gemini is used with file links, run, test, evals, env vars, security and accessibility summaries), docs/PROBLEM_ALIGNMENT.md (each challenge point mapped to a feature, file and test, plus a worked budget-cut example with real engine figures), docs/SECURITY.md (threat model and every control with its test). tests/unit/test_docs.py keeps every linked file, named test and named function real. ARCHITECTURE.md brought up to date (people and lines routes, fonts, img folder).
- README proof: a fresh clone in a short path, following the README with no key, installs, passes lint, types and all tests, and serves the home page and the sample. A very long clone path on Windows fails in pip (Playwright's nested files hit the 260-character limit); the README now says so.
- T27 prepared: `/healthz` reports the deployed commit (from Vercel's VERCEL_GIT_COMMIT_SHA, ignored if malformed), e2e live mode (BASE_URL skips the fake-Gemini flows), a new engine-only sample flow at phone and desktop, live link and release steps in the README. `BASE_URL=<live link> pytest e2e` passed against production (2 passed, 4 skipped by design).
- Left for after review: push, confirm /healthz shows the pushed commit, rerun the live e2e, tag v1.0.0 and push the tag, check on a real phone.
