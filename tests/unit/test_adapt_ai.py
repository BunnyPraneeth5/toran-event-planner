import asyncio
import itertools
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.ai.client import BANNER_TEXT, AIErrorKind, GeminiClient
from app.data.loader import load_reference_data
from app.engines.adapt import AdaptContext, apply_change, apply_ops, complete_option
from app.engines.budget import allocate, budget_status
from app.engines.timeline import build_tasks
from app.models import Option, Plan
from app.models.adapt import AdaptRequest, AdaptResult, ApplyRequest
from app.models.change import (
    BudgetCut,
    ChangeTier,
    DateMoved,
    ScaleCategory,
    VendorCancelled,
)
from app.planner import (
    NO_SAFE_FIX,
    NO_WORKING_OPTIONS_BANNER,
    NOTHING_TO_FIX,
    TOPPED_UP_NOTE,
    adapt_options,
    apply_option,
)
from tests.factories import DAY0, make_event, make_function
from tests.fakes import FakeModels, api_error, fake_client, response

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai"
REF = load_reference_data()
TODAY = DAY0 - timedelta(days=365)
CUT = BudgetCut(new_total=2_000_000)


def _counter(prefix: str) -> Any:
    counter = itertools.count(1)
    return lambda: f"{prefix}{next(counter)}"


def _plan() -> Plan:
    event = make_event()
    functions = [
        make_function("haldi", day=0, hour=10, guests=100, tier="budget"),
        make_function("reception", day=1, hour=19, guests=400, tier="premium"),
    ]
    items = allocate(
        event,
        functions,
        REF.categories.default_weights["wedding"],
        REF.categories.categories,
        REF.categories.tier_multipliers,
        id_factory=_counter("li"),
    )
    base = Plan(event=event, functions=functions, line_items=items)
    tasks = build_tasks(base, REF.lead_times.lead_times, TODAY, id_factory=_counter("t"))
    return Plan(event=event, functions=functions, line_items=items, tasks=tasks)


def _ctx(today: date = TODAY) -> AdaptContext:
    return AdaptContext(
        categories=REF.categories.categories,
        tier_multipliers=REF.categories.tier_multipliers,
        lead_times=REF.lead_times.lead_times,
        today=today,
        id_factory=_counter("o"),
    )


def _fixture(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def _run(
    client: GeminiClient | None, change: Any = CUT, plan: Plan | None = None, today: date = TODAY
) -> AdaptResult:
    request = AdaptRequest(plan=plan or _plan(), change=change)
    return asyncio.run(
        adapt_options(
            request, client, model="gemini-test", ref=REF, today=today, id_factory=_counter("o")
        )
    )


def _run_fixture(name: str, change: Any = CUT) -> tuple[AdaptResult, FakeModels]:
    client, models = fake_client(response(_fixture(name)))
    return _run(client, change), models


def _assert_safe(plan: Plan, result: AdaptResult, change: Any = CUT, today: date = TODAY) -> None:
    """Every option shown applies cleanly, fits the budget and carries engine figures."""
    changed = apply_change(plan, change, _ctx(today))
    locked = {i.id: i for i in changed.line_items if i.locked}
    for option in result.options:
        fixed = apply_ops(changed, option.ops, _ctx(today))
        committed, over_by, _ = budget_status(fixed)
        assert option.result is not None
        assert option.result.total_committed == committed
        assert option.result.over_by == over_by == 0
        assert {i.id: i for i in fixed.line_items if i.locked} == locked
        assert not any(ch.isdigit() for ch in option.rationale)


# fixtures


def test_valid_options_are_verified_and_carry_engine_figures() -> None:
    result, models = _run_fixture("adapt_valid")

    assert result.source == "ai"
    assert result.banner is None
    assert result.impact.over_by == 500_000
    assert len(result.options) == 3
    assert result.options[0].rationale == "Keep the guest list and make the reception simpler."
    _assert_safe(_plan(), result)
    assert models.calls[0]["config"].system_instruction.startswith("Something changed")


def test_one_invalid_option_dropped_and_slot_filled() -> None:
    result, _ = _run_fixture("adapt_one_invalid")

    assert result.source == "ai"
    assert result.options[0].rationale == "Make the reception simpler."
    assert not any(o.rationale.startswith("Cancel the engagement") for o in result.options)
    assert "Left out 1 suggestion(s) that did not fix the problem safely." in result.notices
    assert len(result.options) == 3
    _assert_safe(_plan(), result)


def test_all_invalid_falls_back_to_rule_based_options() -> None:
    result, _ = _run_fixture("adapt_all_invalid")

    assert result.source == "fallback"
    assert result.banner == NO_WORKING_OPTIONS_BANNER
    assert result.options
    assert "Left out 3 suggestion(s) that did not fix the problem safely." in result.notices
    _assert_safe(_plan(), result)


def test_rationale_with_digits_is_replaced_by_template() -> None:
    result, _ = _run_fixture("adapt_digits")

    first = result.options[0]
    assert first.rationale == "A standard setup for Reception and trim clothes and jewellery."
    _assert_safe(_plan(), result)


# completing short options


def test_short_option_is_completed_by_the_engine() -> None:
    draft = {
        "options": [
            {
                "rationale": "Trim catering a little.",
                "ops": [
                    {"op": "scale_category", "category": "catering", "percent": -10,
                     "function_id": None, "guests": None, "tier": None, "line_item_id": None}
                ],
            }
        ]
    }
    client, _ = fake_client(response(json.dumps(draft)))

    result = _run(client)

    first = result.options[0]
    assert first.ops[0] == ScaleCategory(category="catering", percent=-10)
    assert len(first.ops) > 1
    assert first.rationale == f"Trim catering a little. {TOPPED_UP_NOTE}"
    _assert_safe(_plan(), result)


def test_complete_option_returns_none_when_ops_are_invalid() -> None:
    plan = _plan()
    changed = apply_change(plan, CUT, _ctx())
    bad = Option(id="x", rationale="Bad", ops=[ChangeTier(function_id="nope", tier="budget")])

    assert complete_option(plan, changed, bad, _ctx()) is None


# other paths


def test_ai_failure_gives_rule_based_options_with_banner() -> None:
    client, _ = fake_client(api_error(503))

    result = _run(client)

    assert result.source == "fallback"
    assert result.banner == BANNER_TEXT[AIErrorKind.UNAVAILABLE]
    assert result.options
    _assert_safe(_plan(), result)


def test_no_ai_client_gives_rule_based_options() -> None:
    result = _run(None)

    assert result.source == "fallback"
    _assert_safe(_plan(), result)


def test_no_problem_means_no_ai_call() -> None:
    client, models = fake_client(response(_fixture("adapt_valid")))

    result = _run(client, DateMoved(new_start_date=DAY0 + timedelta(days=7)))

    assert result.options == []
    assert result.message == NOTHING_TO_FIX
    assert models.calls == []


def test_unfixable_problem_says_so() -> None:
    data = _plan().model_dump()
    for item in data["line_items"]:
        item["status"] = "booked"
    booked = Plan.model_validate(data)

    result = _run(None, plan=booked)

    assert result.options == []
    assert result.message == NO_SAFE_FIX


def test_vendor_cancelled_offers_skip_and_simpler_replacement() -> None:
    plan = _plan()
    caterer = next(
        i for i in plan.line_items if i.category == "catering" and i.function_id == "reception"
    )
    change = VendorCancelled(line_item_id=caterer.id)
    soon = DAY0 - timedelta(days=21)

    result = _run(None, change=change, plan=plan, today=soon)

    assert len(result.impact.newly_flagged_task_ids) == 1
    rationales = [o.rationale for o in result.options]
    assert "Skip this vendor and keep the money" in rationales
    assert "Book a simpler replacement" in rationales
    _assert_safe(plan, result, change, soon)


def test_prompt_fences_the_plan_and_gives_engine_figures() -> None:
    _, models = _run_fixture("adapt_valid")

    prompt = models.calls[0]["contents"]
    fenced = prompt.split("<plan>")[1].split("</plan>")[0]
    data = json.loads(fenced)
    assert data["impact"]["savings_needed_rupees"] == 500_000
    assert data["change"] == {"kind": "budget_cut", "new_total": 2_000_000}
    assert data["open_rupees_by_category"]["catering"] > 0
    assert {"id": "reception", "name": "Reception"}.items() <= data["functions"][1].items()
    assert all("locked" in item for item in data["line_items"])


def test_unknown_change_ids_raise() -> None:
    with pytest.raises(ValueError, match="no active line item"):
        _run(None, VendorCancelled(line_item_id="ghost"))


# apply_option


def test_apply_option_recomputes_on_the_server() -> None:
    plan = _plan()
    result, _ = _run_fixture("adapt_valid")
    option = result.options[0]

    applied = apply_option(ApplyRequest(plan=plan, change=CUT, option=option), ref=REF, today=TODAY)

    assert applied.event.total_budget == 2_000_000
    assert budget_status(applied)[1] == 0
    assert next(f for f in applied.functions if f.id == "reception").tier == "standard"


def test_apply_option_refuses_a_tampered_option() -> None:
    weak = Option(id="x", rationale="Tiny trim", ops=[ScaleCategory(category="decor", percent=-1)])

    with pytest.raises(ValueError, match="no longer fixes"):
        apply_option(ApplyRequest(plan=_plan(), change=CUT, option=weak), ref=REF, today=TODAY)


def test_apply_option_works_for_vendor_replacement_ids() -> None:
    plan = _plan()
    caterer = next(
        i for i in plan.line_items if i.category == "catering" and i.function_id == "reception"
    )
    change = VendorCancelled(line_item_id=caterer.id)
    soon = DAY0 - timedelta(days=21)
    result = _run(None, change=change, plan=plan, today=soon)
    skip = next(o for o in result.options if o.rationale.startswith("Skip"))

    applied = apply_option(ApplyRequest(plan=plan, change=change, option=skip), ref=REF, today=soon)

    replacement = next(i for i in applied.line_items if i.id == f"{caterer.id}-r")
    assert replacement.status == "cancelled"
