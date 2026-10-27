"""Replays the live eval responses (tests/fixtures/ai/evals) through the fake client.

They were saved by `python -m tests.evals.run_evals --save` from real Gemini output, so
these tests keep real-world answers for all six briefs working without any network.
"""

import asyncio
import json
from datetime import date
from typing import Any

import pytest

from app import planner
from app.data.loader import load_reference_data
from app.models.adapt import AdaptRequest, ApplyRequest
from app.models.generate import CompleteBrief, GenerateRequest
from app.models.intake import IntakeRequest
from app.models.plan import Plan
from tests.evals.run_evals import BRIEFS, FIXTURE_DIR, plan_problems
from tests.fakes import fake_client, response

REF = load_reference_data()
CASES = {c["name"]: c for c in json.loads(BRIEFS.read_text(encoding="utf-8"))["briefs"]}


def _fixture(name: str, step: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (FIXTURE_DIR / f"{name}_{step}.json").read_text(encoding="utf-8")
    )
    return data


def _client(data: dict[str, Any]) -> Any:
    client, _ = fake_client(response(json.dumps(data["response"])))
    return client


def test_every_brief_has_all_three_fixtures() -> None:
    saved = {p.stem for p in FIXTURE_DIR.glob("*.json")}

    for name in CASES:
        for step in ("intake", "generate", "adapt"):
            assert f"{name}_{step}" in saved


@pytest.mark.parametrize("name", sorted(CASES))
def test_intake_reads_what_the_brief_says(name: str) -> None:
    data = _fixture(name, "intake")

    result = asyncio.run(
        planner.intake(
            IntakeRequest(text=data["text"]),
            _client(data),
            model="gemini-test",
            today=date.fromisoformat(data["today"]),
        )
    )

    assert result.source == "ai"
    assert result.status in {"ready", "needs_answers"}
    read = result.brief.model_dump(mode="json")
    for key, expected in CASES[name]["expect"].items():
        assert read[key] == expected, key


@pytest.mark.parametrize("name", sorted(CASES))
def test_generate_gives_a_plan_that_holds_every_invariant(name: str) -> None:
    data = _fixture(name, "generate")
    brief = CompleteBrief.model_validate(data["brief"])

    result = asyncio.run(
        planner.generate(
            GenerateRequest(brief=brief),
            _client(data),
            model="gemini-test",
            ref=REF,
            today=date.fromisoformat(data["today"]),
        )
    )

    assert result.plan.sources.plan == "ai"
    assert result.banner is None
    assert result.plan.functions
    assert plan_problems(result.plan, budget=brief.total_budget, exact=True) == []


@pytest.mark.parametrize("name", sorted(CASES))
def test_adapt_options_all_fix_the_budget_cut(name: str) -> None:
    data = _fixture(name, "adapt")
    today = date.fromisoformat(data["today"])
    plan = Plan.model_validate(data["plan"])
    request = AdaptRequest.model_validate(
        {"plan": plan, "change": {"kind": "budget_cut", "new_total": data["new_total"]}}
    )

    result = asyncio.run(
        planner.adapt_options(request, _client(data), model="gemini-test", ref=REF, today=today)
    )

    assert result.source == "ai"
    assert result.options
    for option in result.options:
        fixed = planner.apply_option(
            ApplyRequest(plan=plan, change=request.change, option=option), ref=REF, today=today
        )
        assert plan_problems(fixed, budget=data["new_total"], exact=False) == []
