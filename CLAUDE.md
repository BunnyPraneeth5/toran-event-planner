# CLAUDE.md (essentials, read every session)

## Project
Toran. Tagline: "An event planner". Repo: toran-event-planner. PromptWars Challenge 5. GenAI planner for Indian weddings (primary persona), with birthdays and community events via templates.
Core rule: Gemini proposes, engines verify. The LLM never computes money or dates.

## Stack
Python 3.12, FastAPI, Pydantic v2, google-genai (async client). Jinja2 + HTMX + vanilla JS + plain CSS. Stateless server, plan in localStorage. Docker on Render.

## Modules
app/engines (pure, no I/O) | app/ai (Gemini wrapper, prompts, schemas) | app/planner.py (only place ai meets engines) | app/api (thin routers) | app/models | app/data (reference JSON) | app/web (templates, static)

## Data models
Plan (root, schema_version), Event, Function, LineItem, Task, Person, Idea, Change, Option, Op. Vendor is stretch. Money is int rupees, datetimes are IST-aware. See ARCHITECTURE.md.

## Boundaries
- engines never import ai, api or planner
- ai never does math on money or dates; Gemini returns raw values, engines convert
- every Gemini call uses a response schema and Pydantic validation, then engines/sanitize
- every option Gemini proposes is verified by engines before the user sees it
- locked line items never change
- fallback must show a visible banner, never silent

## Rules
- Work TASKS.md in order. Next task is the first unchecked one. Tick it only when its proof test passes.
- Stay in scope of the current task. Don't touch unrelated files.
- No new dependencies without asking.
- No secrets in code. Env only. Keep .env.example updated.
- Validate all input with Pydantic limits.
- Run `ruff check . && mypy app && pytest` before saying done.
- Fake Gemini client only in tests via dependency override.
- No inline scripts, inline styles or hx-on attributes (strict CSP).
- UI copy: no fake metrics, no emoji icons, no em dashes, no filler hero text.
- Docs: no days or dates in plans or schedules.
- Small commits, one feature per commit.
- Only the final submission counts: resubmit only from a tagged commit that is green and checked on the live link.
- Update PROGRESS.md at end of each session.

## Current focus
First unchecked task in TASKS.md.

## Gotchas
(add repeated agent mistakes here)
