# Security

Toran is a stateless web app. The server keeps no database and no sessions, and sets no
cookies; each user's plan lives in their own browser. The server's job is to validate
input, call Gemini safely, run the engines and return the result. This document lists what
it protects, the controls in place, and the test or file behind each one.

## Threat model

| Asset | Threat | Main controls |
|---|---|---|
| Gemini API key | Leaked from the repo, logs or responses | Environment only, `SecretStr`, never logged or rendered |
| Gemini quota | Abuse or a runaway loop draining it | Per-IP rate limit, daily call cap, one AI call per user action at most |
| The app's integrity | Injected scripts (XSS), prompt injection steering the AI, tampered requests | Strict CSP, autoescaping, fenced prompts, schema-validated AI output, server-side recompute |
| Availability | Huge bodies, slow AI, crashes leaking internals | Body cap, overall AI deadline with model fallback, generic errors |
| Users' plans | Exposure on the server | Nothing stored server-side; plans stay in the browser |

Out of scope: accounts, payments and multi-user editing do not exist in Toran, so there is
no authentication, authorisation or payment surface to defend.

## Controls

### Input limits

Every request body is a Pydantic model with `extra="forbid"`: unknown fields are rejected,
strings have maximum lengths, money is a strict non-negative integer with an upper bound,
guests are 1 to 5000, and lists (functions, line items, tasks, people, ideas, what-if
changes, payer shares) have maximum sizes. Imported plans go through the same model, which
also checks that every reference (function, payer, task owner) resolves. Ids are always
assigned by the server; a request cannot choose one.

- [app/models/](../app/models/) (limits in [common.py](../app/models/common.py) and
  [plan.py](../app/models/plan.py))
- Tests: [tests/api/test_routes.py](../tests/api/test_routes.py)
  `test_intake_rejects_oversized_text`, `test_invalid_plans_rejected_with_422`,
  `test_whatif_limits_number_of_changes`;
  [tests/unit/test_models.py](../tests/unit/test_models.py)
  `test_money_must_be_non_negative_int`;
  [tests/api/test_people.py](../tests/api/test_people.py)
  `test_add_person_refuses_an_id_from_the_client`

Request bodies larger than `MAX_BODY_BYTES` (256 KB) are refused with 413 before any route
runs, including streamed bodies with no length header.

- [app/security.py](../app/security.py) `BodySizeLimitMiddleware`
- Tests: [tests/api/test_security.py](../tests/api/test_security.py)
  `test_large_body_rejected_with_413`, `test_large_streamed_body_without_length_rejected`

### Prompt injection

- Everything the user typed (the description, answers, style notes, and plan data sent for
  Something changed) is wrapped in tags such as `<user_input>` and `<plan>`, after
  stripping anything that could open or close a tag. The system instruction says fenced
  content is data, not instructions. [app/ai/prompts.py](../app/ai/prompts.py) `fence`
- Gemini can only answer in a fixed response schema; the answer is validated by Pydantic,
  then cleaned by [app/engines/sanitize.py](../app/engines/sanitize.py). It cannot invent
  ids, set amounts or add fields.
- Fixes are named operations, applied and verified by the engines. A fix that does not
  pass every invariant is dropped. Option text may not contain digits, so every figure the
  user sees comes from the engines.
- Model output is never rendered as HTML: Jinja autoescaping is on everywhere.
- Tests: [tests/unit/test_intake.py](../tests/unit/test_intake.py)
  `test_injection_text_is_fenced_and_cannot_close_the_fence`;
  [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py)
  `test_prompt_fences_the_plan_and_gives_engine_figures`,
  `test_rationale_with_digits_is_replaced_by_template`;
  [tests/api/test_routes.py](../tests/api/test_routes.py)
  `test_htmx_partials_escape_user_text`;
  [tests/unit/test_calendar.py](../tests/unit/test_calendar.py) `test_user_text_is_escaped`

### Tampered requests

The browser holds the plan, so the server never trusts a result it computed. Applying a fix
sends the original plan, the change and the chosen option; the server re-applies and
re-verifies all of it and refuses anything that no longer fixes the problem.

- [app/planner.py](../app/planner.py) `apply_option`
- Tests: [tests/api/test_routes.py](../tests/api/test_routes.py)
  `test_apply_never_accepts_a_client_computed_plan`,
  `test_apply_refuses_an_option_that_does_not_fix_the_problem`;
  [tests/unit/test_adapt_ai.py](../tests/unit/test_adapt_ai.py)
  `test_apply_option_refuses_a_tampered_option`

### Content Security Policy and headers

Every response, including 413, 429 and 500, carries:

- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'
  https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:;
  connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self';
  frame-ancestors 'none'`
- `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`, `Cross-Origin-Opener-Policy`,
  `Permissions-Policy` (geolocation for this site only, used by the sample's "Use my
  location", which compares coordinates in the browser and never sends them; camera,
  microphone, payment and usb off), and an `X-Request-ID`.

There are no inline scripts, inline styles or `hx-on` attributes anywhere, and htmx runs
with `allowEval: false`, `allowScriptTags: false` and `selfRequestsOnly: true`. The plan
travels in a `data-` attribute, not a script block. The CSP is relaxed only on `/docs`
outside production; in production `/docs` and `/openapi.json` are switched off.

- [app/security.py](../app/security.py) `CSP`, `SECURITY_HEADERS`,
  `SecurityHeadersMiddleware`; [app/web/templates/base.html](../app/web/templates/base.html)
- Tests: [tests/api/test_security.py](../tests/api/test_security.py)
  `test_every_response_carries_security_headers`, `test_csp_is_strict`,
  `test_pages_only_load_what_the_csp_allows`, `test_geolocation_allowed_only_for_this_site`;
  [tests/api/test_pages.py](../tests/api/test_pages.py)
  `test_htmx_config_turns_off_eval_and_inline_styles`;
  [tests/unit/test_theme.py](../tests/unit/test_theme.py)
  `test_templates_have_no_inline_styles`, `test_svgs_are_plain_drawings`;
  [tests/api/test_health.py](../tests/api/test_health.py)
  `test_docs_hidden_on_vercel_production`;
  [e2e/test_smoke.py](../e2e/test_smoke.py) fails on any browser console error, which
  includes CSP violations

### Rate limiting and quota

- The three routes that call Gemini (intake, generate, Something changed options) are
  limited per client IP (`RATE_LIMIT_LLM`, default 10 a minute). The IP is the first entry
  of Vercel's `x-forwarded-for`. Engine-only routes are not limited: they are cheap.
- `AI_DAILY_CALL_LIMIT` (default 500) counts every Gemini request per IST day, retries and
  fallbacks included. When it is reached, AI steps use their rule-based fallback with a
  banner.
- Each AI-backed request has one overall deadline (25 seconds) and the SDK's own retries
  are off, so a slow model cannot hold a worker or multiply calls.
- Both counters live in memory, so on Vercel they apply per serverless instance. The hard
  ceiling is the key's own quota: the key is on the free tier with no billing, so there is
  nothing to overspend.
- [app/security.py](../app/security.py) `limiter`, `llm_limit`;
  [app/ai/limits.py](../app/ai/limits.py); [app/ai/client.py](../app/ai/client.py)
- Tests: [tests/api/test_security.py](../tests/api/test_security.py)
  `test_llm_routes_rate_limited_per_client_ip`, `test_engine_only_routes_are_not_rate_limited`;
  [tests/unit/test_ai_limits.py](../tests/unit/test_ai_limits.py)
  `test_client_stops_calling_gemini_at_the_limit`,
  `test_retries_and_fallbacks_count_against_the_limit`;
  [tests/unit/test_ai_client.py](../tests/unit/test_ai_client.py)
  `test_timeout_is_never_retried`

### Errors

Unexpected errors return a generic message and the request id; the stack trace and
exception text go only to the server log, with the same id. Validation errors return 422
with field names, never internal details.

- [app/security.py](../app/security.py) `_unexpected`
- Tests: [tests/api/test_security.py](../tests/api/test_security.py)
  `test_unexpected_errors_are_generic_with_request_id`

### Secrets

- The Gemini key is read from the environment into a `SecretStr`, so it never appears in a
  repr, a log line or an error. Locally it lives in `.env`, which is git-ignored; in
  production it is set in the Vercel dashboard. [.env.example](../.env.example) documents
  every variable with no values.
- AI logs record endpoint, model, latency, token counts and outcome, never user text.
- [app/config.py](../app/config.py); [.gitignore](../.gitignore)
- Tests: [tests/unit/test_config.py](../tests/unit/test_config.py)
  `test_secret_not_in_repr`, `test_blank_key_is_not_configured`;
  [tests/unit/test_ai_client.py](../tests/unit/test_ai_client.py)
  `test_logs_carry_metrics_but_never_user_text`, `test_no_client_without_key`

## Personal data

- **No PII at rest.** The server stores nothing: no database, no files, no sessions. Plans,
  including any names and pledges in Who pays, live in the user's browser (localStorage)
  and in files the user chooses to download.
- **What reaches Gemini.** Intake sends the user's description and answers. Generate sends
  the brief (event type, title, city, date, guests, budget, style notes). Something changed
  sends the change, functions, categories and amounts; it does not send people's names or
  pledges.
- **AI Studio data handling.** Toran uses a Gemini API key from Google AI Studio on the
  free tier. Under Google's terms for unpaid Gemini API use, prompts and responses may be
  used to improve Google's products and may be reviewed by people. That is why nothing
  beyond the event details is sent, and why the app never asks for phone numbers,
  addresses or payment details. Moving the key to a paid project changes this handling.
- Logs hold no user text.

## Why CSRF and CORS do not apply

- **CSRF** relies on the browser attaching credentials (cookies or HTTP auth) to a request
  forged by another site. Toran sets no cookies and has no login or session, so a forged
  request carries nothing the attacker does not already have. Every write operation is
  pure: it takes a plan in the body and returns a result; nothing is changed on the server.
- **CORS**: there is no CORS middleware, so browsers block other origins from reading
  Toran's responses. The front end only talks to its own origin (`connect-src 'self'`,
  htmx `selfRequestsOnly`).
- Framing is blocked (`frame-ancestors 'none'`, `X-Frame-Options: DENY`), so clickjacking
  does not apply either.

## Dependencies

- Runtime dependencies are pinned to exact versions in both [pyproject.toml](../pyproject.toml)
  (read by Vercel) and [requirements.txt](../requirements.txt) (read by CI); a test keeps
  them identical. Dev tools are pinned in [requirements-dev.txt](../requirements-dev.txt).
- htmx is vendored at a pinned version with its licence; axe-core (tests only) likewise.
- CI runs `pip-audit` against the runtime requirements on every push, and ruff with the
  bandit (`S`) security rules on all Python.
- Tests: [tests/unit/test_dependencies.py](../tests/unit/test_dependencies.py)
  `test_runtime_dependencies_match_requirements_txt`, `test_runtime_dependencies_are_pinned`;
  [tests/api/test_pages.py](../tests/api/test_pages.py)
  `test_vendored_htmx_is_the_pinned_version`; [.github/workflows/ci.yml](../.github/workflows/ci.yml)

## Reporting a problem

Please open an issue on the GitHub repository without including exploit details, and a
private channel will be arranged.
