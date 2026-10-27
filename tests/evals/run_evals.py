"""Live evals: six real-style briefs through intake, generate and adapt on real Gemini.

    python -m tests.evals.run_evals            run all briefs and print a report
    python -m tests.evals.run_evals --only hinglish_input
    python -m tests.evals.run_evals --save     also save each live response as a fixture

Needs GEMINI_API_KEY (from .env or the environment). Not part of `pytest` or CI: it calls
the real API, takes about a minute, and uses the free tier's quota. Every raw call's model
and latency is recorded; every plan and option is checked against the engine invariants.
Saved fixtures go to tests/fixtures/ai/evals/ and are replayed by
tests/unit/test_eval_fixtures.py without any network.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from google.genai import types

from app import planner
from app.ai.client import GeminiClient, _sdk_client
from app.api.deps import get_today
from app.config import get_settings
from app.data.loader import ReferenceData, get_reference_data
from app.engines.budget import budget_status
from app.engines.ledger import ledger_summary
from app.engines.timeline import flagged_task_ids
from app.models.adapt import AdaptRequest, ApplyRequest
from app.models.generate import CompleteBrief, GenerateRequest
from app.models.intake import IntakeRequest
from app.models.plan import Plan

HERE = Path(__file__).parent
BRIEFS = HERE / "briefs.json"
FIXTURE_DIR = HERE.parent / "fixtures" / "ai" / "evals"
PAUSE_SECONDS = 4.0
"""Gap between live calls, to stay inside the free tier's per-minute limits."""
BUDGET_CUT = (8, 10)
"""The adapt step cuts the budget to 80 percent of the plan's total."""


@dataclass
class Call:
    step: str
    model: str
    seconds: float
    ok: bool
    text: str | None = None
    error: str = ""


@dataclass
class RecordingModels:
    """Wraps the SDK's `aio.models`: records model, latency and raw text of every call."""

    inner: Any
    step: str = ""
    calls: list[Call] = field(default_factory=list)

    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        started = time.perf_counter()
        try:
            result: types.GenerateContentResponse = await self.inner.generate_content(
                model=model, contents=contents, config=config
            )
        except Exception as exc:
            error = f"{type(exc).__name__} {getattr(exc, 'code', '')}".strip()
            seconds = time.perf_counter() - started
            self.calls.append(Call(self.step, model, seconds, ok=False, error=error))
            raise
        self.calls.append(
            Call(self.step, model, time.perf_counter() - started, ok=True, text=result.text)
        )
        return result


@dataclass
class Outcome:
    brief: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def plan_problems(plan: Plan, *, budget: int, exact: bool) -> list[str]:
    """Engine invariants. `exact`: lines must sum to the budget to the rupee."""
    problems: list[str] = []
    committed, _, _ = budget_status(plan)
    if exact and committed != budget:
        problems.append(f"lines sum to {committed}, budget is {budget}")
    if not exact and committed > budget:
        problems.append(f"lines sum to {committed}, over the budget of {budget}")
    for function in plan.functions:
        if not plan.event.start_date <= function.start.date() <= plan.event.end_date:
            problems.append(f"function {function.name} is outside the event dates")
    if any(t.due_date > plan.event.end_date for t in plan.tasks):
        problems.append("a task is due after the event")
    if Plan.model_validate_json(plan.model_dump_json()) != plan:
        problems.append("the plan does not survive a JSON round trip")
    summary = ledger_summary(plan)
    if summary.total_assigned + summary.unassigned != summary.total_planned:
        problems.append("ledger does not add up")
    return problems


def _complete_brief(
    intake_brief: dict[str, Any], fill: dict[str, Any], today: date
) -> dict[str, Any]:
    brief = {k: v for k, v in intake_brief.items() if v is not None}
    for key, value in fill.items():
        if key == "start_in_days":
            brief.setdefault("start_date", (today + timedelta(days=value)).isoformat())
        else:
            brief.setdefault(key, value)
    return brief


def _save(name: str, payload: dict[str, Any]) -> None:
    """Save one live response; `today` is kept so a replay judges dates the same way."""
    payload = {"today": get_today().isoformat(), **payload}
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _last_text(models: RecordingModels, step: str) -> Any:
    texts = [c.text for c in models.calls if c.step == step and c.ok and c.text]
    return json.loads(texts[-1]) if texts else None


async def run_brief(
    case: dict[str, Any],
    ai: GeminiClient,
    models: RecordingModels,
    ref: ReferenceData,
    today: date,
    *,
    save: bool,
) -> Outcome:
    settings = get_settings()
    outcome = Outcome(case["name"])
    problems = outcome.problems

    # 1. Intake on the lite model
    models.step = "intake"
    intake = await planner.intake(
        IntakeRequest(text=case["text"]), ai, model=settings.gemini_lite_model, today=today
    )
    if intake.source != "ai":
        problems.append(f"intake fell back: {intake.banner}")
        return outcome
    if intake.status == "not_event":
        problems.append("intake said this is not an event")
        return outcome
    read = intake.brief.model_dump(mode="json")
    for key, expected in case["expect"].items():
        if read.get(key) != expected:
            problems.append(f"intake read {key}={read.get(key)!r}, expected {expected!r}")
    outcome.notes.append(f"intake missing={intake.missing} questions={len(intake.questions)}")
    if save:
        response = _last_text(models, "intake")
        _save(f"{case['name']}_intake", {"text": case["text"], "response": response})
    await asyncio.sleep(PAUSE_SECONDS)

    # 2. Generate on the main model
    models.step = "generate"
    brief = CompleteBrief.model_validate(_complete_brief(read, case["fill"], today))
    generated = await planner.generate(
        GenerateRequest(brief=brief), ai, model=settings.gemini_model, ref=ref, today=today
    )
    plan = generated.plan
    if plan.sources.plan != "ai":
        problems.append(f"generate fell back: {generated.banner}")
    problems.extend(plan_problems(plan, budget=brief.total_budget, exact=True))
    flagged = flagged_task_ids(plan, today)
    if case.get("expect_flagged_tasks") and not flagged:
        problems.append("expected late or at-risk tasks for an event this close")
    outcome.notes.append(
        f"plan functions={[f.name for f in plan.functions]} lines={len(plan.line_items)} "
        f"tasks={len(plan.tasks)} flagged={len(flagged)} ideas={len(plan.ideas)}"
    )
    if save:
        _save(
            f"{case['name']}_generate",
            {"brief": brief.model_dump(mode="json"), "response": _last_text(models, "generate")},
        )
    await asyncio.sleep(PAUSE_SECONDS)

    # 3. Adapt: a budget cut, with every option re-applied and re-checked
    models.step = "adapt"
    new_total = max(plan.event.total_budget * BUDGET_CUT[0] // BUDGET_CUT[1], 1_000)
    request = AdaptRequest.model_validate(
        {"plan": plan, "change": {"kind": "budget_cut", "new_total": new_total}}
    )
    adapted = await planner.adapt_options(
        request, ai, model=settings.gemini_model, ref=ref, today=today
    )
    if adapted.source != "ai":
        problems.append(f"adapt fell back: {adapted.banner}")
    if not adapted.options:
        problems.append(f"no options for a budget cut: {adapted.message}")
    for option in adapted.options:
        try:
            fixed = planner.apply_option(
                ApplyRequest(plan=plan, change=request.change, option=option), ref=ref, today=today
            )
        except ValueError as exc:
            problems.append(f"option {option.id} did not re-apply: {exc}")
            continue
        problems.extend(
            f"option {option.id}: {p}" for p in plan_problems(fixed, budget=new_total, exact=False)
        )
    outcome.notes.append(f"adapt options={len(adapted.options)} source={adapted.source}")
    if save:
        _save(
            f"{case['name']}_adapt",
            {
                "plan": plan.model_dump(mode="json"),
                "new_total": new_total,
                "response": _last_text(models, "adapt"),
            },
        )
    return outcome


async def main(only: str | None, save: bool) -> int:
    settings = get_settings()
    if settings.gemini_api_key is None:
        print("GEMINI_API_KEY is not set. Put it in .env or the environment.")
        return 2
    sdk = _sdk_client(
        settings.gemini_api_key.get_secret_value(), int(settings.ai_deadline_seconds * 1000)
    )
    models = RecordingModels(sdk.aio.models)
    ai = GeminiClient(
        models,
        deadline_seconds=settings.ai_deadline_seconds,
        fallback_models=settings.fallback_models,
    )
    ref = get_reference_data()
    today = get_today()
    cases = json.loads(BRIEFS.read_text(encoding="utf-8"))["briefs"]
    if only:
        cases = [c for c in cases if c["name"] == only]

    outcomes: list[Outcome] = []
    for case in cases:
        outcomes.append(await run_brief(case, ai, models, ref, today, save=save))
        await asyncio.sleep(PAUSE_SECONDS)

    print("\nCalls")
    for call in models.calls:
        status = "ok" if call.ok else f"failed ({call.error})"
        print(f"  {call.step:<9} {call.model:<28} {call.seconds:6.2f}s  {status}")
    print("\nBriefs")
    for outcome in outcomes:
        print(f"  {'PASS' if outcome.passed else 'FAIL'}  {outcome.brief}")
        for note in outcome.notes:
            print(f"        {note}")
        for problem in outcome.problems:
            print(f"        problem: {problem}")
    passed = sum(o.passed for o in outcomes)
    print(f"\n{passed} of {len(outcomes)} briefs passed")
    return 0 if passed == len(outcomes) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run one brief by name")
    parser.add_argument("--save", action="store_true", help="save live responses as fixtures")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.only, args.save)))
