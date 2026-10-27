# TASKS: Toran

Work top to bottom. One task per session. Tick a task only when its proof test passes and `ruff check . && mypy app && pytest` is green. Record each session in PROGRESS.md.

## Index
- [x] T01 Scaffold
- [x] T02 Config
- [x] T03 Domain models
- [x] T04 Reference data
- [x] T05 Budget engine
- [x] T06 Timeline engine
- [x] T07 Ledger engine
- [x] T08 Parse and sanitize engines
- [x] T09 Adapt engine
- [x] T10 Gemini wrapper
- [x] T11 Intake
- [x] T12 Generate
- [x] T13 Adapt options (AI)
- [x] T14 API routes
- [x] T14a Early Vercel deploy (checkpoint)
- [x] T15 UI base and intake page
- [x] T16 Dashboard page and state contract
- [x] T16a Try a sample event
- [x] T16b People and payers
- [x] T16c Bookings and actual costs
- [x] T16d Navigation, overview and small usability details
- [x] T16e Indian visual theme
- [x] T17 What-if slider
- [x] T18 Something changed UI
- [ ] T18a Video script (checkpoint, owner: you)
- [x] T19 Calendar export
- [x] T20 Security middleware
- [x] T21 CI
- [x] T22 E2E and accessibility tests
- [x] T23 Live evals
- [x] T24 README
- [x] T25 PROBLEM_ALIGNMENT.md
- [x] T26 SECURITY.md
- [ ] T27 Production release on Vercel
- [ ] S01 STRETCH: Replacement vendor discovery (Maps grounding)
- [ ] S02 STRETCH: Day-of run sheet
- [ ] S03 STRETCH: Telugu and Hindi output
- [ ] S04 STRETCH: More ideas per function
- [ ] S05 STRETCH: Read-only share link

---

## T01 Scaffold
**Files:** `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `app/__init__.py`, `app/main.py`, `app/api/health.py`, `tests/conftest.py`, `tests/api/test_health.py`, `.gitignore`, `.gitattributes`, `.dockerignore`, `.env.example`

**Acceptance**
- [x] Git repository initialized; first commit contains only the scaffold
- [x] `create_app()` factory in `app/main.py`; `GET /healthz` returns `{"status": "ok"}`
- [x] Runtime and dev dependencies pinned, limited to those listed in ARCHITECTURE.md
- [x] ruff (including bandit `S` rules) and mypy (strict on `app/`) configured in `pyproject.toml`
- [x] `.gitignore` and `.dockerignore` both exclude `.env`, virtualenvs and caches
- [x] `ruff check . && mypy app && pytest` passes

**Proof:** `pytest tests/api/test_health.py::test_healthz_ok`

## T02 Config
**Files:** `app/config.py`, `app/main.py`, `.env.example`, `tests/unit/test_config.py`, `tests/api/test_health.py`

**Acceptance**
- [x] Settings via pydantic-settings: `GEMINI_API_KEY` (`SecretStr`, optional), model names, AI deadline seconds, rate limits, body size cap, environment (IST is a fixed UTC+05:30 offset in `app/models/common.py`, so no tz database dependency)
- [x] App starts without `GEMINI_API_KEY`; `/healthz` reports `ai_configured: false`
- [x] Key never appears in `repr`, logs or error responses
- [x] Every setting listed in `.env.example` with a safe placeholder

**Proof:** `pytest tests/unit/test_config.py` (`test_defaults`, `test_secret_not_in_repr`) and `tests/api/test_health.py::test_healthz_reports_ai_configured`

## T03 Domain models
**Files:** `app/models/__init__.py`, `app/models/common.py`, `app/models/event.py`, `app/models/plan.py`, `app/models/change.py`, `tests/factories.py`, `tests/unit/test_models.py`

**Acceptance**
- [x] Plan, Event, Function, LineItem, Task, Person, Idea, Change, Option, Op match ARCHITECTURE.md
- [x] Money fields are strict `int` rupees; floats and negatives rejected
- [x] Function uses an IST-aware `start` datetime plus `duration_minutes`
- [x] LineItem payer shares sum to 100 when present; `locked` is true when status is booked or paid
- [x] Task stores no late or at-risk flag
- [x] Plan validator rejects dangling `function_id`, payer `person_id` and `owner_id` references
- [x] Length and count limits on every string and list
- [x] Plan JSON round-trips unchanged

**Proof:** `pytest tests/unit/test_models.py`

## T04 Reference data
**Files:** `app/data/categories.json`, `app/data/lead_times.json`, `app/data/function_templates.json`, `app/data/city_tiers.json`, `app/data/loader.py`, `tests/unit/test_data.py`

**Acceptance**
- [x] Categories with default weights per event type; lead time in days per category
- [x] Templates: Telugu wedding, North Indian wedding, birthday, community event
- [x] Cities mapped to a city type (metro, tier2, tier3); per-plate price ranges for catering and invitations by city type and tier (budget, standard, premium)
- [x] Loader validates each file with Pydantic at startup and keeps it in memory
- [x] Default weights use known categories and sum to 100 per event type; every category has a lead time; every event type has a template
- [x] Each file carries a "rough defaults, not vendor quotes" note

**Proof:** `pytest tests/unit/test_data.py::test_reference_data_consistent`

## T05 Budget engine
**Files:** `app/engines/__init__.py`, `app/engines/budget.py`, `app/models/budget.py`, `tests/unit/test_budget.py`, `tests/unit/test_boundaries.py`

**Acceptance**
- [x] `allocate(total, weights, functions, ...)` produces line items by largest remainder; sum equals total exactly
- [x] Function-scoped lines split by guests (per-plate) and venue tier; what-if guest and tier changes scale those lines
- [x] `realism_warnings` flags per-plate lines below the usual range for the function's tier and the city type, with the typical low and high for its guests
- [x] `what_if(plan, changes)` rebalances only unlocked items; locked items unchanged
- [x] Overrun flagged when locked plus actual exceed total, with the amount over
- [x] Edge cases covered: zero weights, single item, very large budget, all items locked
- [x] Reference data passed in as arguments; no I/O; no imports from ai, api or planner

**Proof:** `pytest tests/unit/test_budget.py` (sum exact, locked unchanged, overrun amount)

## T06 Timeline engine
**Files:** `app/engines/timeline.py`, `app/models/timeline.py`, `tests/unit/test_timeline.py`

**Acceptance**
- [x] `build_tasks(plan, lead_times)` schedules backward from each function date
- [x] No task due after the event date
- [x] Late and at-risk computed with an injected `today` in IST; at-risk tasks get the earliest feasible date
- [x] Event three weeks away: long-lead tasks marked at risk, not given past due dates
- [x] Overnight function (starts 22:00, runs 5 hours) stays within event dates

**Proof:** `pytest tests/unit/test_timeline.py`

## T07 Ledger engine
**Files:** `app/engines/ledger.py`, `app/models/ledger.py`, `tests/unit/test_ledger.py`

**Acceptance**
- [x] Per person: pledged, assigned (payer share of planned), paid (payer share of actual), gap
- [x] Split shares allocate rupees exactly by largest remainder
- [x] Unassigned total reported
- [x] Sum of assigned plus unassigned equals sum of planned

**Proof:** `pytest tests/unit/test_ledger.py`

## T08 Parse and sanitize engines
**Files:** `app/engines/parse.py`, `app/engines/sanitize.py`, `tests/unit/test_parse.py`, `tests/unit/test_sanitize.py`, `tests/fixtures/sanitize_cases.json`

**Acceptance**
- [x] `parse_amount(value, unit)` handles rupees, thousand, lakh, crore (25 lakh is 2,500,000)
- [x] `parse_date(year, month, day, today)` returns a date or a "needs day" marker; past dates flagged
- [x] Sanitize clamps guests to 1 to 5000, sets negative weights to 0, replaces zero-sum weights with defaults, maps unknown categories to "other", drops functions outside event dates with a notice, dedupes function names
- [x] Weight and function cases driven by the fixture file (NaN, infinity and the 12-function cap are inline, since JSON cannot express them compactly)

**Proof:** `pytest tests/unit/test_parse.py tests/unit/test_sanitize.py`

## T09 Adapt engine
**Files:** `app/engines/adapt.py`, `app/engines/budget.py` (`rebalance` flag, `budget_status`), `app/models/change.py` (`Impact`), `tests/unit/test_adapt.py`

**Acceptance**
- [x] `apply_change(plan, change)` for budget_cut, vendor_cancelled, guests_changed, date_moved, function_dropped
- [x] `impact(before, after)` reports amount over budget, newly late or at-risk tasks, affected lines
- [x] vendor_cancelled frees the line item and adds a "book replacement" task checked against lead time
- [x] `apply_ops(plan, ops)` works on a copy and rejects unknown ids and invalid params
- [x] `verify_option` keeps an option only if all invariants hold and the problem is resolved
- [x] `rule_based_options(plan, change)` returns at least one valid option for budget_cut and vendor_cancelled
- [x] Locked items never change

**Proof:** `pytest tests/unit/test_adapt.py`

## T10 Gemini wrapper
**Files:** `app/ai/__init__.py`, `app/ai/client.py`, `requirements.txt`, `tests/fakes.py`, `tests/unit/test_ai_client.py`, `tests/unit/test_boundaries.py`

**Acceptance**
- [x] Async client only; one overall deadline per call from settings
- [x] Retry once only on schema-invalid output and only if time remains; timeouts never retried
- [x] `finish_reason` checked before parsing
- [x] Failures mapped to `AIError`: timeout, rate_limited, unavailable, blocked, truncated, invalid
- [x] System instruction, response schema, safety settings and `max_output_tokens` set on every call
- [x] Logs endpoint, model, latency, token counts and outcome; never user text
- [x] Fake client lives in `tests/fakes.py`, injected by dependency override, never imported by app code

**Proof:** `pytest tests/unit/test_ai_client.py` (one test per `AIError`, retry rule, no user text in captured logs)

## T11 Intake
**Files:** `app/models/intake.py`, `app/ai/schemas.py`, `app/ai/prompts.py`, `app/ai/service.py`, `app/planner.py`, `tests/unit/test_intake.py`, `tests/fixtures/ai/intake_*.json`

**Acceptance**
- [x] Flat BriefDraft schema: raw amount + unit, raw date parts, city, guests, type, `is_event`, `reason`, up to 3 questions
- [x] User text and answers fenced as data in the prompt
- [x] `planner.intake` converts values with `engines.parse`; a missing day becomes a question, not a guess
- [x] Non-event input returns `is_event: false` with a friendly message
- [x] AI failure returns an empty brief form with the fallback banner flag set
- [x] Live check against Gemini: complete brief, Hinglish with a missing day, non-event and an injection attempt all behave as above

**Proof:** `pytest tests/unit/test_intake.py` (fixtures: valid, Hinglish, non-event, injection attempt, timeout)

## T12 Generate
**Files:** `app/models/generate.py`, `app/engines/sanitize.py` (`place_functions`), `app/data/function_templates.json` (neutral default first), `app/ai/schemas.py`, `app/ai/prompts.py`, `app/ai/service.py`, `app/planner.py`, `tests/unit/test_generate.py`, `tests/unit/test_sanitize.py`, `tests/fixtures/ai/generate_*.json`

**Acceptance**
- [x] Gemini returns functions, category weights and ideas only; checklist built from `lead_times.json`
- [x] Output passes sanitize, budget, timeline and ledger; server assigns ids
- [x] Fallback plan from `function_templates.json` passes every engine invariant and is marked in `plan.sources`
- [x] `max_output_tokens` sized for the largest template
- [x] Live check against Gemini: wedding and birthday plans came back with exact budgets, correct dates and fitting ideas; a hung main model and a 429 both handed over to the lite model

**Proof:** `pytest tests/unit/test_generate.py` (valid, truncated, invalid weights, fallback invariants)

## T13 Adapt options (AI)
**Files:** `app/models/adapt.py`, `app/engines/adapt.py` (`complete_option`, stable replacement ids), `app/ai/schemas.py`, `app/ai/prompts.py`, `app/ai/service.py`, `app/planner.py` (`adapt_options`, `apply_option`), `tests/unit/test_adapt_ai.py`, `tests/unit/test_adapt.py`, `tests/fixtures/ai/adapt_*.json`

**Acceptance**
- [x] Gemini receives the impact summary and the fenced plan, returns 2 to 3 options using only the Op vocabulary
- [x] Each option verified by `engines.adapt`; failing options dropped
- [x] If none survive or the call fails, rule-based options are returned with the fallback flag
- [x] A rationale containing digits is replaced by template text
- [x] Every figure on an option comes from the engine
- [x] A short option (right direction, sum too small) is completed by the engine with an even trim, then verified
- [x] Fewer than three AI options are topped up with rule-based ones
- [x] `apply_option` re-verifies from scratch and refuses a tampered or stale option
- [x] Live check: a cut from 25 to 20 lakh produced three distinct Gemini options, each completed and verified below the new total

**Proof:** `pytest tests/unit/test_adapt_ai.py` (valid options, one invalid op dropped, all invalid falls back, digits in rationale)

## T14 API routes
**Files:** `app/api/plan.py`, `app/api/budget.py`, `app/api/adapt.py`, `app/api/deps.py`, `app/api/render.py`, `app/models/view.py`, `app/planner.py` (`recompute`, `run_what_if`), `app/web/formatting.py`, `app/web/templates/partials/*.html` (minimal, fleshed out in T15 and T16), `app/main.py`, `requirements.txt` (jinja2), `tests/api/test_routes.py`, `tests/unit/test_formatting.py`, `tests/factories.py`

**Acceptance**
- [x] Routes from ARCHITECTURE.md wired (calendar and stretch routes excluded), each a thin call into `planner`
- [x] JSON by default; HTML partial when the `HX-Request` header is present
- [x] Intake route passes `GEMINI_LITE_MODEL`; generate and adapt routes pass `GEMINI_MODEL`
- [x] 422 on invalid plan, dangling references and oversized lists
- [x] `/api/adapt/apply` re-applies ops server-side and never accepts a client-computed plan
- [x] LLM routes tested with the fake client via dependency override

**Proof:** `pytest tests/api/test_routes.py`

## T14a Early Vercel deploy (checkpoint)
Done right after T14, so hosting, env var and cold start problems show up early, not on the last day. Render was dropped: every existing service on that account was suspended for billing, and its free plan sleeps for about a minute.

**Files:** `pyproject.toml` (runtime dependencies), `app/config.py` (`VERCEL_ENV`), `tests/unit/test_dependencies.py`, `tests/unit/test_config.py`, `tests/api/test_health.py`

**Acceptance**
- [x] Vercel project imported from GitHub: FastAPI preset, root `./`, Hobby plan, Mumbai region (`bom1`), deploys on every push to `main`
- [x] `GEMINI_API_KEY` and `ENVIRONMENT` set in the Vercel dashboard, never in the repo
- [x] Runtime dependencies declared in `pyproject.toml` (Vercel installs from it); a test keeps them identical to `requirements.txt`
- [x] Live `/healthz` returns `{"status": "ok", "ai_configured": true}`; recompute and the HTMX partial work live; responses in about 0.4 seconds
- [x] `/docs` hidden on the live site: the app also treats Vercel's own `VERCEL_ENV=production` as production, so it no longer depends on the dashboard variable's scope

**Proof:** `GET https://toran-event-planner.vercel.app/healthz` returns ok; `GET /docs` returns 404

## T15 UI base and intake page
**Files:** `app/api/pages.py`, `app/web/templates/base.html`, `app/web/templates/intake.html`, `app/web/templates/partials/brief.html`, `app/web/templates/partials/banner.html`, `app/web/static/css/app.css`, `app/web/static/js/app.js`, `app/web/static/vendor/htmx.min.js` (2.0.11, with licence), `app/web/templates/partials/plan_state.html`, `app/main.py` (static mount), `tests/api/test_pages.py`, `tests/api/test_routes.py`

**Acceptance**
- [x] Base layout: landmarks, skip link, `lang` attribute, `htmx-config` meta (`includeIndicatorStyles: false`, `allowEval: false`, `allowScriptTags: false`), one aria-live region
- [x] No inline scripts, no inline `style` attributes, no `hx-on`, no CDN scripts
- [x] Intake: one text field, then the brief as a form with questions as fields and missing fields highlighted
- [x] Fallback banner partial shown whenever `sources` marks fallback
- [x] `htmx:responseError` writes the message into the live region
- [x] Layout works at 390px

**Proof:** `pytest tests/api/test_pages.py` (pages render; every `<script>` has a local `src`; no `style=` attributes; banner present on fallback)

## T16 Dashboard page and state contract
**Files:** `app/web/templates/dashboard.html`, `app/web/templates/partials/functions.html`, `app/web/templates/partials/budget.html`, `app/web/templates/partials/timeline.html`, `app/web/templates/partials/ledger.html`, `app/web/templates/partials/plan_state.html`, `app/web/templates/partials/plan.html`, `app/web/templates/partials/plan_tools.html`, `app/web/static/js/state.js`, `app/web/static/js/app.js`, `app/api/pages.py` (`/plan`), `app/web/formatting.py` (date filters), `app/web/static/css/app.css`, `tests/api/test_pages.py`

**Acceptance**
- [x] Dashboard shows functions, budget table, timeline with late and at-risk text labels, ledger
- [x] Every plan-changing partial embeds `<div id="plan-state" hidden data-plan="...">` (htmx strips script tags from swaps)
- [x] `state.js` adds the plan to requests, saves on `htmx:afterSwap`, checks `schema_version`, warns on changes from another tab, calls `navigator.storage.persist()`
- [x] Export and import JSON; imports validated server-side through `/api/plan/recompute`
- [x] Budget bars via `<meter>` or SVG; every chart also a table; rupees in lakh/crore

**Proof:** `pytest tests/api/test_pages.py::test_dashboard_partials_embed_plan_state` (browser round-trip covered in T22)

## T16a Try a sample event
A one-click demo so judges see the whole flow in seconds, even if Gemini is slow or rate limited.

**Files:** `app/data/sample_plan.json`, `app/data/loader.py` (`SampleFile`), `app/planner.py` (`sample_plan`), `app/api/plan.py` (`/api/plan/sample`), `app/api/pages.py`, `app/models/common.py` (source `sample`), `app/web/templates/intake.html`, `app/web/templates/partials/plan.html`, `app/web/static/js/sample.js`, `tests/api/test_sample.py`

**Acceptance**
- [x] "Try a sample wedding" loads a prebuilt plan instantly, with no AI call
- [x] The user picks the city from a list (default: a neutral metro); the sample plan is rebuilt by the engines for that city
- [x] Optional "Use my location": the browser picks the nearest supported city from built-in coordinates; the location never leaves the browser
- [x] Sample data names no real people and no Andhra Pradesh cities
- [x] Sample plan passes every engine invariant and is clearly labelled as a sample

**Proof:** `pytest tests/api/test_sample.py` (loads without an AI client, invariants hold, city change reprices catering ranges)

## T16b People and payers
The ledger can show who pays, but nobody can enter their own people or assign payers yet. This adds that, engine only.

**Files:** `app/engines/ledger.py`, `app/models/people.py`, `app/planner.py`, `app/api/people.py`, `app/main.py`, `app/web/templates/partials/ledger.html`, `app/web/static/js/app.js`, `app/web/static/css/app.css`, `tests/unit/test_ledger.py`, `tests/api/test_people.py`

**Acceptance**
- [x] In "Who pays", the user can add a person or side (name, role, pledge in rupees), change a pledge, and remove a person
- [x] Removing a person also removes them from every line they pay for and every task they own; the affected lines become unassigned, and a notice says how many
- [x] Each budget line can be given one payer, or split between people by percent, with a "Split equally" choice; shares must add up to 100
- [x] Pure engine functions in `engines/ledger.py` (add person, update pledge, remove person, assign payers) return a new plan; ids are assigned by the server; no LLM call
- [x] Unknown ids, shares that do not add up to 100, a duplicate person in one split, or more than 50 people return 422 with a clear message, shown in the live region
- [x] After every change the ledger (pledged, assigned, paid, balance, unassigned) updates, the response embeds the plan state, and the plan is saved in the browser
- [x] Labelled inputs, keyboard only flow, works at 390px, no inline scripts or styles

**Proof:** `pytest tests/unit/test_ledger.py tests/api/test_people.py` (add, change pledge, remove with payer and owner clean-up, single and split payers, split equally gives exact rupees, shares not adding to 100 return 422, zero AI calls, partial embeds plan state)

## T16c Bookings and actual costs
Only the sample shows booked lines today. Users need to mark their own bookings, because booked or paid lines are what stay fixed in what-if and fill the ledger's Paid column.

**Files:** `app/engines/budget.py` (or a small `engines/lines.py`), `app/models/lines.py`, `app/planner.py`, `app/api/lines.py`, `app/main.py`, `app/web/templates/partials/budget.html`, `app/web/static/js/app.js`, `tests/unit/test_lines.py`, `tests/api/test_lines_api.py`

**Acceptance**
- [x] Each budget line can be marked planned, booked or paid, and given an actual cost in rupees
- [x] Booked or paid lines lock automatically (existing model rule); marking a line back to planned unlocks it
- [x] The line's task is marked done when it is booked or paid, and back to to-do when unbooked
- [x] An actual cost above the planned amount shows the difference as text ("₹20,000 over the plan for this line") and counts towards the overrun
- [x] Engine only, no LLM call; unknown ids or negative amounts return 422 with a clear message in the live region
- [x] Labelled inputs, keyboard only flow, works at 390px, no inline scripts or styles

**Proof:** `pytest tests/unit/test_lines.py tests/api/test_lines_api.py` (book, pay with actual, unbook, task status follows, over-plan text, locked line unchanged by a later what-if, zero AI calls)

## T16d Navigation, overview and small usability details
The dashboard holds a lot. This makes it easy to scan on a phone and a laptop, with what needs action first.

**Files:** `app/web/templates/dashboard.html`, `app/web/templates/partials/plan.html`, `app/web/templates/partials/overview.html`, `app/web/templates/partials/nav.html`, `app/web/templates/partials/timeline.html`, `app/web/templates/partials/functions.html`, `app/web/templates/intake.html`, `app/web/static/js/nav.js`, `app/web/static/js/state.js`, `app/web/static/js/app.js`, `app/web/static/css/app.css`, `tests/api/test_dashboard_nav.py`

**Acceptance**
- [x] Creating a plan (generate, sample or import) opens the dashboard on `/plan`; the home page stays short (describe, check, or try the sample)
- [x] Step marker on the home page: Describe, Check, Plan, with the current step announced
- [x] Sticky contents panel on wide screens (left rail): Overview, Something changed, Budget, What if, Timeline, Functions, Who pays, Keep your plan, each with a live status next to it (for example "Over by ₹40,000", "3 late", "₹2 lakh unassigned"); the section in view is highlighted as you scroll
- [x] On phones the panel becomes a sticky one-line status bar at the top ("₹25 lakh, over ₹40k, 3 late"); tapping it opens the full list
- [x] Overview section first: countdown ("97 days to go"), a budget bar (planned, booked or paid, and any overrun, drawn with SVG or `<meter>` and always repeated as text), and an "Action needed" list (late tasks, at-risk tasks, over-budget lines, unassigned money) with links to the right section
- [x] "Something changed?" is one click away from anywhere (in the panel and the overview)
- [x] Long lists collapse by default using `<details>`: the timeline shows late, at-risk and the next five tasks, the rest folded; done tasks and ideas folded
- [x] Function times shown as ranges with weekday ("Sat 8 Mar, 19:00 to 23:00")
- [x] Undo: the last plan change (what-if, applied option, import, new plan) can be undone once; starting a new plan or the sample no longer silently overwrites the saved plan without an undo
- [x] "Saved in this browser" status in the panel after each change
- [x] Budget fields in the brief form show the amount in lakh or crore as you type
- [x] Panel is a `<nav aria-label>` with ordinary links; works by keyboard; respects reduced motion; no inline scripts or styles; no horizontal scroll at 390px

**Proof:** `pytest tests/api/test_dashboard_nav.py` (panel links match section ids, statuses match engine figures, overview action list, collapsed timeline, undo kept in state.js, generate and sample responses send the browser to /plan) and a browser check at 390px and desktop

## T16e Indian visual theme
Make Toran look like an Indian celebration planner without hurting speed, contrast or the strict CSP.

**Files:** `app/web/static/css/app.css`, `app/web/static/img/` (hand-made SVGs), `app/web/templates/base.html`, `app/web/templates/partials/*.html`, `tests/unit/test_theme.py`

**Acceptance**
- [x] Palette from the occasion (marigold, turmeric, sindoor red, mehendi green, peacock blue) as CSS tokens, in light and dark mode
- [x] Every text and background token pair meets WCAG AA contrast (4.5:1 for body text, 3:1 for large text and focus outlines)
- [x] A toran (marigold and mango-leaf garland) SVG across the header; a matching favicon
- [x] Light motifs: rangoli or mandala corner on cards, a paisley divider between sections, and one small SVG icon per budget category (no emoji)
- [x] One display font for headings from Google Fonts with a Devanagari-capable family, `display=swap`; body text stays Noto Sans
- [x] All SVGs drawn for this project (no third-party art), decorative ones `aria-hidden`, total added weight under 30 KB
- [x] No inline `style` attributes, no animation when reduced motion is requested; still no horizontal scroll at 390px

**Proof:** `pytest tests/unit/test_theme.py` (contrast ratio of every token pair from app.css, SVG files exist and are under the size budget, no `style=` in SVGs or templates) and screenshots at 390px and desktop in light and dark mode

## T17 What-if slider
**Files:** `app/web/templates/partials/whatif.html`, `app/web/templates/partials/plan.html`, `app/web/static/js/whatif.js`, `app/web/static/js/app.js` (single-control requests), `app/web/static/css/app.css`, `tests/api/test_whatif.py`

Venue tier is a select per function rather than a slider: three values read better as a list.

**Acceptance**
- [x] Sliders for guests, venue tier and category amounts; `hx-trigger="input changed delay:250ms"`, `hx-sync="this:replace"`
- [x] `aria-valuetext` in Indian format; one live announcement per settled change
- [x] Locked items shown as locked and never move
- [x] Overrun shown as text ("Over by ₹40,000"), not color alone
- [x] No LLM call

**Proof:** `pytest tests/api/test_whatif.py` (locked unchanged, overrun text present, fake client records zero calls)

## T18 Something changed UI
**Files:** `app/web/templates/partials/change_form.html`, `app/web/templates/partials/options.html`, `app/web/static/js/app.js`, `app/api/adapt.py`, `app/web/templates/partials/plan.html`, `app/web/static/css/app.css`, `tests/api/test_adapt_ui.py`

**Acceptance**
- [x] Form for each change kind
- [x] Impact shown first, then 2 to 3 options side by side with engine figures and rationale
- [x] Choosing an option posts to `/api/adapt/apply`; plan updates and is saved
- [x] Fallback options carry the banner
- [x] Whole flow works by keyboard alone

**Proof:** `pytest tests/api/test_adapt_ui.py` (budget cut renders options; apply returns a plan that passes all invariants)

## T18a Video script (checkpoint, owner: you)
Once T18 works, write the 2 to 3 minute video script against the flow in PRD.md, and plan to record it on the deployed link, not localhost.

## T19 Calendar export
**Files:** `app/engines/calendar.py`, `app/web/links.py` (Google Calendar link, kept out of engines), `app/api/calendar.py`, `app/clock.py` (`now_utc`), `app/web/static/js/calendar.js`, `app/web/templates/partials/timeline.html`, `tests/unit/test_calendar.py`, `tests/api/test_calendar_api.py`

**Acceptance**
- [x] .ics with one all-day event per task and one timed event per function (UTC, converted from IST), stable UIDs
- [x] User text escaped per RFC 5545
- [x] "Add to Google Calendar" link per task
- [x] Download via fetch + blob, filename `toran-plan.ics`
- [x] No LLM call

**Proof:** `pytest tests/unit/test_calendar.py tests/api/test_calendar_api.py` (escaping, stable UIDs, `text/calendar` attachment)

## T20 Security middleware
**Files:** `app/security.py`, `app/main.py`, `app/api/plan.py` and `app/api/adapt.py` (rate limits), `requirements.txt` and `pyproject.toml` (slowapi 0.1.10), `tests/conftest.py` (limiter reset), `tests/api/test_security.py`

**Acceptance**
- [x] CSP (as in ARCHITECTURE.md), HSTS, nosniff, Referrer-Policy, Permissions-Policy on every response
- [x] Body size cap returns 413
- [x] slowapi limit on LLM routes returns 429, keyed on the real client IP (first entry of Vercel's `x-forwarded-for`)
- [x] Gzip enabled; static assets sent with cache headers
- [x] Global exception handler returns a generic message with a request id, no stack trace
- [x] Every rendered page still works under the CSP

**Proof:** `pytest tests/api/test_security.py`

## T21 CI
**Files:** `.github/workflows/ci.yml`

No Docker image is needed on Vercel, so the Docker build step was dropped.

**Acceptance**
- [x] CI on push and pull request: ruff, mypy, pytest with 80% coverage floor, pip-audit (added early, before T11)
- [x] CI fails if `pyproject.toml` and `requirements.txt` list different runtime dependencies
- [x] Pipeline green on main

**Proof:** green CI run on main

## T22 E2E and accessibility tests
**Files:** `e2e/conftest.py`, `e2e/test_smoke.py`, `e2e/axe.min.js`, `.github/workflows/ci.yml`

**Acceptance**
- [x] App served in-process with the fake client via dependency override
- [x] One flow at 390px and desktop: intake, questions, plan, what-if, budget cut, pick option, export
- [x] Plan survives a page reload
- [x] axe scan on intake, dashboard and adapt views: no serious or critical violations
- [x] Keyboard-only path through intake and adapt
- [x] e2e job added to CI

**Proof:** `pytest e2e` green locally and in CI

## T23 Live evals
**Files:** `tests/evals/briefs.json`, `tests/evals/run_evals.py`

**Acceptance**
- [x] Six briefs: Telugu wedding, North Indian wedding, Hinglish input, 5th birthday, society Ganesh event, wedding three weeks away
- [x] Against live Gemini: schema valid, engine invariants hold, latency per call recorded
- [x] Separate command, excluded from CI and from `pytest` default collection
- [x] Useful outputs saved as fixtures for unit tests

**Proof:** `python -m tests.evals.run_evals` reports every brief passing

## T24 README
**Files:** `README.md`

**Acceptance**
- [x] Problem, persona and what Toran does
- [x] Architecture diagram (Mermaid) and the core rule
- [x] Where Gemini is used, with file links
- [x] How to run locally, run tests, run evals; env vars
- [x] Security and accessibility summaries linking to docs

**Proof (manual):** fresh clone, follow the README, app runs and tests pass

## T25 PROBLEM_ALIGNMENT.md
**Files:** `docs/PROBLEM_ALIGNMENT.md`

**Acceptance**
- [x] Each problem statement point mapped to a feature, a file and a test: budget, guest and timeline constraints; adapting to budget cuts and vendor cancellations; asking questions; tradeoffs
- [x] Explains "Gemini proposes, engines verify" with one worked example

**Proof (manual):** every linked file and test exists

## T26 SECURITY.md
**Files:** `docs/SECURITY.md`

**Acceptance**
- [x] Threat model, input limits, prompt injection handling, CSP, rate limiting, secrets handling
- [x] No PII at rest; AI Studio data handling
- [x] Why CSRF and CORS do not apply
- [x] Dependency scanning

**Proof (manual):** every control listed points to a test in `tests/api/test_security.py` or a named file

## T27 Production release on Vercel
**Files:** `README.md`

**Acceptance**
- [x] Production deployment on Vercel matches the commit being submitted; env vars set in the Vercel dashboard, not in the repo
- [ ] Submission is a tagged commit whose production deployment is green and checked live
- [x] Live link added to README
- [ ] Release checklist below completed

**Proof:** e2e smoke run with `BASE_URL` set to the live URL passes

---

## S01 STRETCH: Replacement vendor discovery (Maps grounding)
**Files:** `app/ai/service.py`, `app/ai/schemas.py`, `app/api/ai.py`, `app/web/templates/partials/vendors.html`, `tests/unit/test_vendors.py`

**Acceptance**
- [ ] Pricing, free quota and schema compatibility confirmed before building; hard daily cap in code
- [ ] Vendor name and `maps_uri` taken only from grounding metadata
- [ ] Labelled "discovered, not endorsed"; Google Maps attribution shown
- [ ] Only place URIs cached, short TTL
- [ ] Offered from the vendor_cancelled flow

**Proof:** `pytest tests/unit/test_vendors.py` (recorded grounding response, daily cap enforced)

## S02 STRETCH: Day-of run sheet
**Files:** `app/engines/runsheet.py`, `app/web/templates/partials/runsheet.html`, `app/web/static/css/print.css`, `tests/unit/test_runsheet.py`

**Acceptance**
- [ ] Now / Next per function with owner names
- [ ] Owner clash warnings when one person owns overlapping tasks
- [ ] Print stylesheet

**Proof:** `pytest tests/unit/test_runsheet.py`

## S03 STRETCH: Telugu and Hindi output
**Files:** `app/ai/service.py`, `app/ai/prompts.py`, `app/api/ai.py`, `app/web/templates/base.html`, `tests/unit/test_translate.py`

**Acceptance**
- [ ] Lite model translates checklist and run sheet text only
- [ ] Figures inserted by the engine after translation, never translated by Gemini
- [ ] Noto Sans Telugu and Devanagari load only when chosen; `lang` attribute set
- [ ] Failure keeps English with a banner

**Proof:** `pytest tests/unit/test_translate.py` (placeholders preserved, fallback banner)

## S04 STRETCH: More ideas per function
**Files:** `app/ai/service.py`, `app/api/ai.py`, `app/web/templates/partials/ideas.html`, `tests/api/test_ideas.py`

**Acceptance**
- [ ] Lite model returns ideas with cost band for one function
- [ ] Ideas carry no prices
- [ ] Rate limited like other LLM routes

**Proof:** `pytest tests/api/test_ideas.py`

## S05 STRETCH: Read-only share link
**Files:** `app/web/static/js/share.js`, `app/web/templates/shared.html`, `e2e/test_share.py`

**Acceptance**
- [ ] Plan compressed with `CompressionStream` into the URL fragment; never sent to the server
- [ ] Read-only view, validated through `/api/plan/recompute`
- [ ] Warning when the link is too long to share

**Proof:** `pytest e2e/test_share.py` (round-trip opens the same plan)

---

## Release checklist (every submission)
- [ ] `ruff check . && mypy app && pytest` green; CI green
- [ ] Live evals pass
- [ ] e2e smoke passes against the live URL (`BASE_URL=<live link> pytest e2e`)
- [ ] `/healthz` on the live link reports the commit being tagged
- [ ] Commit tagged; Vercel's production deployment is that commit
- [ ] Live link checked on a phone
- [ ] Only submit if better than the last submission
