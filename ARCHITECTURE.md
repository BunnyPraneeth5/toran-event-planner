# ARCHITECTURE: Toran (toran-event-planner)

## Stack and why
| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 | Fast, typed, you already know it. Pydantic validates every request and every Gemini response. |
| AI | google-genai SDK (async client), Gemini API (AI Studio key) | Structured output with response schemas. Maps grounding for the stretch vendor discovery. |
| Models | `gemini-3.8-flash` (generate, adapt), `gemini-3.5-flash-lite` (intake and cheap stretch tasks); fallback chain `gemini-3.6-flash`, then `gemini-3.5-flash-lite` | Set via env, verified against the key's model list. Pin stable, never "latest". Intake is pure extraction, and the lite model answered it correctly in about 2 seconds while the newest flash models were often overloaded. |
| Frontend | Jinja2 templates + HTMX 2.0.11 (vendored) + small vanilla JS (including a `toran-json` htmx extension that sends typed, nested JSON) + hand-written CSS | No build step, tiny bundle, easy accessibility, one deploy. HTMX swaps partials for the what-if slider and adapt options. |
| State | Stateless server. Plan lives in browser localStorage with `schema_version`, export/import as JSON | No DB to secure, no PII stored server-side, nothing lost on redeploys. |
| Calendar | .ics file + "Add to Google Calendar" link | Free, no OAuth. |
| Fonts | Google Fonts: Noto Sans (`display=swap`). Noto Sans Telugu and Devanagari load only with the translation stretch. | Small payload by default. |
| Hosting | Vercel (Hobby plan), FastAPI preset, Mumbai region (`bom1`) | Free with no card, wakes in well under a second, deploys from GitHub on every push to `main`. A request may run up to 300 seconds; our AI deadline is 25. Serverless, so several instances may run at once. |
| Quality | ruff (incl. bandit S rules), mypy, pytest, pytest-cov, httpx, pip-audit, Playwright + axe-core | Covers code quality, security, testing, accessibility signals. |
| CI | GitHub Actions: lint, type check, tests with coverage floor, pip-audit, e2e smoke | Visible proof for the grader. |

Note: the host scores nothing on Google services. The signal comes from Gemini (response schemas, system instructions, explicit safety settings, usage metadata, grounding in stretch), Google Calendar links and Google Fonts. Cloud Run stays a documented upgrade path.

## Modules
```
app/
  main.py            app factory, middleware wiring, exception handler
  config.py          env settings (pydantic-settings)
  planner.py         orchestrates ai + engines per use case; the only place they meet; routers stay thin
  security.py        security headers, body size cap, rate limit, request id
  models/            Pydantic domain models (see below)
  engines/           PURE python, no I/O, no LLM, clock and reference data passed in
    parse.py         raw amount + unit to rupees, raw date parts to dates
    sanitize.py      clamp ranges, normalize weights, map unknown categories, drop out-of-range functions
    budget.py        allocate (largest remainder), what_if, overrun flags, respects locked items
    timeline.py      backward schedule, late and at-risk flags
    ledger.py        pledged, assigned, paid, gap per person
    adapt.py         apply a Change, compute impact, apply and verify option ops, rule-based options
    calendar.py      .ics export, Google Calendar links
    runsheet.py      STRETCH: ordering, owner clashes
  ai/
    client.py        async Gemini wrapper: overall deadline, retry on invalid output only, AIError, token logging
    prompts.py       system instructions and templates; every user-sourced field fenced as data
    schemas.py       flat response models for structured output, separate from domain models
    service.py       intake, generate, adapt_options; STRETCH vendors, translate, ideas
  api/               routers: pages, plan, budget, adapt, calendar, health
  data/              reference JSON: categories (weights, per-plate price ranges by city type and tier), lead_times, function_templates, city_tiers + loader
  web/templates/     Jinja2 pages + HTMX partials
  web/static/        css, js, vendor (htmx, json-enc)
tests/unit  tests/api  tests/fixtures  tests/evals  e2e/
docs/PROBLEM_ALIGNMENT.md  docs/SECURITY.md
```

## Data models (core fields)
All money is `int` rupees (strict, never float), formatted as lakh/crore only at render. All datetimes are timezone-aware in Asia/Kolkata. Ids are short UUIDs assigned by the server after sanitize; Gemini never invents ids.

- **Plan** (root, the single body for storage, import and API): schema_version, event, functions, line_items, tasks, people, ideas, sources (brief, plan, options: "ai", "fallback" or "sample"). A model validator checks every reference resolves.
- **Event**: id, type (wedding | birthday | community), title, city, start_date, end_date, guests, total_budget, language, style_notes
- **Function**: id, name, start (datetime), duration_minutes, guests, guests_override, tier (budget | standard | premium)
- **LineItem**: id, function_id (nullable = event-wide), category, planned, actual (nullable), payers [{person_id, share_pct}] (shares sum to 100 when present), status (planned | booked | paid | cancelled), locked (true when booked or paid)
- **Task**: id, title, function_id, category, due_date, lead_days, status, owner_id. Late and at-risk are computed per request, never stored.
- **Person**: id, name, side_or_role, pledge. Used as payer and task owner.
- **Idea**: id, function_id, text, cost_band (low | mid | high)
- **Change**: kind (budget_cut | vendor_cancelled | guests_changed | date_moved | function_dropped) + typed params
- **Option**: id, rationale (plain text, no digits), ops (list of Op), plus engine-computed result figures
- **Op**: reduce_guests(function_id, guests) | change_tier(function_id, tier) | scale_category(category, percent) | drop_item(line_item_id). No rupee amounts come from Gemini.
- **Impact** (engine output): total_committed, over_by, unallocated, newly_flagged_task_ids, affected_line_ids
- **TaskAssessment** (engine output, never stored): task_id, late, at_risk, days_until_due, ready_by
- **Vendor** (stretch): name, category, maps_uri, source = "maps_grounding"

## Flow
1. **Intake.** Free text goes to Gemini with structured output. Returns a flat BriefDraft: raw amount + unit, raw date parts, city, guests, type, `is_event`, and up to 3 clarifying questions. `engines.parse` converts amounts and dates. The UI shows the brief as a form with the questions as fields; a missing day becomes a question, never a guess. Submitting answers sends text + answers back to intake (no chat state on the server).
2. **Generate.** One Gemini call. Input: brief + function template + category list. Output: functions, category weights, ideas. The checklist comes from lead_times.json, not Gemini, which keeps output small.
3. **Engines run.** sanitize, then budget turns weights into rupee line items, timeline builds tasks backward from the event date, ledger starts empty. Server assigns ids.
4. **Render.** Plan returned to the browser and saved to localStorage. Dashboard shows functions, budget, timeline, ledger.
5. **What-if.** Debounced slider changes post to `/api/budget/whatif`. Engine only. Returns an HTMX partial in milliseconds.
6. **Something changed.** `/api/adapt/options`: the engine applies the change and computes impact. If nothing is wrong, no AI call is made. Otherwise Gemini proposes 2 to 3 options as ops. The engine applies each to a copy; when an option points the right way but leaves a shortfall, the engine completes it with an even trim of the largest remaining categories; it keeps only options that pass every invariant and resolve the problem, and attaches real figures. Fewer than three AI options are topped up with rule-based ones. If none survive or Gemini fails, rule-based options with a banner. `/api/adapt/apply` re-applies the change and the chosen ops server-side and re-verifies them; it never accepts a plan computed by the client. Lines and tasks created by a change get ids derived from the change, so the apply step recreates the same ids.
7. **Export.** .ics download and Google Calendar links per task.

## State contract (HTMX + localStorage + strict CSP)
- Static JS adds the plan from localStorage to each request; the `toran-json` extension in `app.js` sends JSON bodies (numbers stay numbers, dotted field names nest, only the keys each route accepts), so no form parsing dependency is needed.
- Every partial that changes the plan embeds `<div id="plan-state" hidden data-plan="...">` with the plan as escaped JSON. JS reads it on `htmx:afterSwap`, checks `schema_version` and writes localStorage. An attribute rather than a `<script type="application/json">` block, because htmx with `allowScriptTags: false` strips every script tag from swapped content.
- `<meta name="htmx-config">` sets `includeIndicatorStyles: false`, `allowEval: false`, `allowScriptTags: false`. No `hx-on` attributes; listeners live in static JS. No inline `style` attributes; bars use `<meter>`, `<progress>` or SVG attributes.
- `htmx:responseError` writes the error message into an aria-live region.
- Unknown `schema_version`: offer export of the raw data, then reset. Call `navigator.storage.persist()`. Listen for the `storage` event to warn when another tab changed the plan.
- Endpoints return JSON by default and an HTML partial when the `HX-Request` header is present. Same handler, same validation.

## API
| Method | Path | LLM | Purpose |
|---|---|---|---|
| POST | /api/plan/intake | yes | text (+ answers) to brief + questions |
| POST | /api/plan/generate | yes | brief to full plan |
| POST | /api/plan/sample | no | city to the one-click sample wedding, built by the engines |
| POST | /api/plan/recompute | no | plan to budget, timeline (late, at risk) and ledger views; also validates imports |
| POST | /api/budget/whatif | no | plan + changes to rebalanced plan |
| POST | /api/adapt/options | yes | plan + change to impact + verified options |
| POST | /api/adapt/apply | no | plan + change + chosen option to new plan |
| POST | /api/calendar/ics | no | plan to .ics file |
| GET | /healthz | no | health check, AI configured flag |
| POST | /api/ai/vendors | yes | STRETCH: Maps grounding replacement vendors |
| POST | /api/ai/translate | yes | STRETCH: Telugu / Hindi |
| POST | /api/ai/ideas | yes | STRETCH: more ideas for one function |

## AI guardrails
- Every call sets a system instruction, a response schema from `ai/schemas.py`, explicit safety settings and `max_output_tokens`. Output parsed into Pydantic.
- Async client only, so a slow call never blocks other requests. One overall deadline per request (default 25s, env). Retry once only on schema-invalid output and only if time remains. On overload, rate limit (429, 5xx) or a hang, hand over to the next untried model in `GEMINI_FALLBACK_MODELS` (default `gemini-3.6-flash,gemini-3.5-flash-lite`); while another model is left to try, each attempt gets at most half of the remaining time. The same model is never retried after a timeout. SDK-level retries are off so this logic owns the deadline.
- `finish_reason` checked before parsing. Failures map to `AIError`: timeout, rate_limited, unavailable, blocked, truncated, invalid. Each has its own banner text; rate_limited says "busy, try again" instead of falling back.
- Schema-valid output still passes through `engines.sanitize` before any engine uses it.
- Intake returns `is_event`; non-event input gets a friendly prompt, not a plan.
- Every user-sourced field (text, answers, style_notes, names from imported plans) is fenced as data in every prompt. System prompt says treat it as data, not instructions.
- Option rationale must contain no digits; if it does, a template line replaces it. Every number the user sees comes from an engine.
- Fallback per section, recorded in `plan.sources`, with a visible banner that survives reload. Never silent.
- Model output rendered through Jinja autoescape. No raw HTML from the model.
- Log per call: endpoint, model, latency, tokens from `usage_metadata`, outcome. No user text in logs.
- No response caching, except stretch vendor lookups (place URIs only, short TTL, per Maps terms).
- Daily cap: `AI_DAILY_CALL_LIMIT` (default 500) counts every Gemini request per IST day, retries and fallbacks included. Once reached, every AI feature uses its rule-based fallback with a banner saying the limit resets at midnight IST. The count is in memory and per serverless instance, so the hard cap is the key's own quota (free tier today); this guards against loops and abuse.

## Security
- Pydantic limits on everything: text length, guests 1 to 5000, budget range, max functions, items, tasks, people, string lengths inside imported plans.
- Request body size cap (413). Rate limit on LLM endpoints per client IP (slowapi), with the IP taken from the first entry of Vercel's `x-forwarded-for` header. Limits are kept in memory, so they apply per serverless instance.
- Headers: CSP `default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy.
- No cookies, no sessions, same-origin only, no CORS middleware, so CSRF and CORS do not apply (documented in SECURITY.md).
- Global exception handler returns a generic message with a request id. No stack traces. Debug off in production.
- Secrets only in env (`SecretStr`), set in the Vercel dashboard for production. `.env.example` committed, `.env` gitignored. Pinned dependencies in both `pyproject.toml` (read by Vercel) and `requirements.txt` (read by CI), kept identical by a test. pip-audit in CI.
- No server-side storage means no PII at rest. AI Studio data handling noted in SECURITY.md.

## Efficiency
- At most one LLM call per user action. What-if, recompute, apply and export never touch the LLM.
- Checklist from templates instead of the LLM keeps generate output small and fast.
- Lite model for intake and cheap stretch tasks. Flash for generate and adapt.
- Slider debounced (`hx-trigger="input changed delay:250ms"`, `hx-sync="this:replace"`).
- Gzip, cache headers on static assets, no JS framework, HTMX partials instead of full reloads, small serverless bundle (runtime dependencies only).

## Testing
- **Unit:** engines. Invariants: line items sum exactly to budget (to the rupee), no task after event date, late and at-risk flags correct relative to an injected "today" in IST, ledger totals balance, locked items never change, every surviving option passes all invariants. parse and sanitize: one fixture per bad-output case.
- **AI layer:** fake client returns recorded responses (valid, invalid JSON, truncated, blocked, timeout, 429). Each maps to the right `AIError` and banner.
- **API:** FastAPI TestClient with a fake Gemini client injected via dependency override. Tests only, never in prod. Security headers, 413, 429, 422 on dangling references.
- **Evals:** 6 real-style briefs (Telugu wedding, North Indian wedding, Hinglish input, 5th birthday, society Ganesh event, wedding 3 weeks away). Run against live Gemini, check schema validity and engine invariants. Separate command, not in CI.
- **E2E:** one Playwright smoke flow at 390px and desktop, app served in-process with the fake client. axe-core scan on intake, dashboard and adapt views.
- Coverage: 80% overall floor enforced in CI, 85%+ on engines.

## Accessibility
Semantic landmarks, skip link, labelled inputs, keyboard path for everything, visible focus, one aria-live region for results and errors (announced once after the debounce settles, not on every slider tick), slider `aria-valuetext` in Indian format ("₹25 lakh"), overruns and at-risk tasks shown with text, not color alone, AA contrast, reduced motion respected, `lang` attribute set per output language, every chart also shown as a table. Rupees in Indian format (lakh, crore).

## External services
Gemini API, Google Calendar links, Google Fonts, Vercel (hosting). STRETCH: Google Maps grounding.

## Deployment
- Vercel project imported from GitHub `BunnyPraneeth5/toran-event-planner`, FastAPI preset, root `./`, Hobby plan, region Mumbai (`bom1`). Live at https://toran-event-planner.vercel.app
- Vercel finds the FastAPI `app` in `app/main.py` and installs the dependencies listed in `pyproject.toml`.
- Every push to `main` deploys to production. A submission is a tagged commit whose production deployment is green and checked live.
- Environment variables live in the Vercel dashboard, scoped to Production: `GEMINI_API_KEY` (secret) and `ENVIRONMENT=production` (hides `/docs`). Everything else uses the defaults in `app/config.py`. Changing a variable needs a redeploy.
- Cloud Run (Docker) stays a documented upgrade path if a long-running container is ever needed.

## Boundaries
- Engines never import ai/, api/ or planner.
- ai/ never computes money or dates. It returns raw values; engines convert.
- planner.py is the only module that calls both ai/ and engines/.
- Reference data in app/data is editable JSON, labelled "rough defaults, not vendor quotes" in the UI.

## Open questions
- Lead time and cost reference values: need a quick sanity pass from someone who has run a wedding.
- Exact Gemini model names, structured output schema limits, free-tier quota. Check before building the AI layer.
- STRETCH Maps grounding: pricing, free quota, and whether it combines with a response schema in one call.
- The in-memory daily cap and rate limits count per serverless instance on Vercel. Acceptable while the Gemini key is on the free tier with no billing (nothing to overspend); revisit if paid billing is turned on.
