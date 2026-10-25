import itertools
from datetime import date, timedelta
from typing import Any

import pytest

from app.data.loader import load_reference_data
from app.engines.adapt import (
    AdaptContext,
    apply_change,
    apply_ops,
    impact,
    rule_based_options,
    verify_option,
)
from app.engines.budget import allocate, budget_status
from app.engines.timeline import build_tasks, flagged_task_ids
from app.models import Option, Plan
from app.models.change import (
    BudgetCut,
    ChangeTier,
    DateMoved,
    DropItem,
    FunctionDropped,
    GuestsChanged,
    ReduceGuests,
    ScaleCategory,
    VendorCancelled,
)
from tests.factories import DAY0, make_event, make_function

REF = load_reference_data()
FAR_AHEAD = DAY0 - timedelta(days=365)
THREE_WEEKS_OUT = DAY0 - timedelta(days=21)


def _counter(prefix: str) -> Any:
    counter = itertools.count(1)
    return lambda: f"{prefix}{next(counter)}"


def _ctx(today: date = FAR_AHEAD) -> AdaptContext:
    return AdaptContext(
        categories=REF.categories.categories,
        tier_multipliers=REF.categories.tier_multipliers,
        lead_times=REF.lead_times.lead_times,
        today=today,
        id_factory=_counter("new"),
    )


def _plan(built_on: date = FAR_AHEAD) -> Plan:
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
    tasks = build_tasks(base, REF.lead_times.lead_times, built_on, id_factory=_counter("t"))
    return Plan(event=event, functions=functions, line_items=items, tasks=tasks)


def _line(plan: Plan, category: str, function_id: str | None = None) -> Any:
    return next(
        i
        for i in plan.line_items
        if i.category == category and i.function_id == function_id and i.active
    )


def _with_line(plan: Plan, line_id: str, **patch: Any) -> Plan:
    data = plan.model_dump()
    for item in data["line_items"]:
        if item["id"] == line_id:
            item.update(patch)
    return Plan.model_validate(data)


def _locked(plan: Plan) -> dict[str, Any]:
    return {i.id: i for i in plan.line_items if i.locked}


# apply_change and impact


def test_budget_cut_moves_no_lines_and_reports_overrun() -> None:
    plan = _plan()

    changed = apply_change(plan, BudgetCut(new_total=2_000_000), _ctx())
    result = impact(plan, changed, FAR_AHEAD)

    assert changed.event.total_budget == 2_000_000
    assert changed.line_items == plan.line_items
    assert result.over_by == 500_000
    assert result.affected_line_ids == []


def test_more_guests_raise_per_plate_lines_only() -> None:
    plan = _plan()

    changed = apply_change(plan, GuestsChanged(guests=600), _ctx())
    result = impact(plan, changed, FAR_AHEAD)

    assert result.over_by > 0
    assert set(result.affected_line_ids) == {
        i.id for i in plan.line_items if i.category in {"catering", "invitations_gifts"}
    }
    assert _line(changed, "attire").planned == _line(plan, "attire").planned


def test_vendor_cancelled_frees_line_and_adds_replacement_task() -> None:
    plan = _plan(FAR_AHEAD)
    caterer = _line(plan, "catering", "reception")
    plan = _with_line(plan, caterer.id, status="booked")

    changed = apply_change(plan, VendorCancelled(line_item_id=caterer.id), _ctx(THREE_WEEKS_OUT))
    result = impact(plan, changed, THREE_WEEKS_OUT)

    cancelled = next(i for i in changed.line_items if i.id == caterer.id)
    assert cancelled.status == "cancelled"
    assert cancelled.locked is False
    replacement = next(i for i in changed.line_items if i.id not in {x.id for x in plan.line_items})
    assert (replacement.category, replacement.planned) == ("catering", caterer.planned)
    task = next(t for t in changed.tasks if t.title.startswith("Find a replacement"))
    assert task.title == "Find a replacement: Catering for Reception"
    assert task.due_date == THREE_WEEKS_OUT
    assert task.id in result.newly_flagged_task_ids
    assert result.over_by == 0


def test_date_moved_shifts_everything() -> None:
    plan = _plan()
    new_start = DAY0 + timedelta(days=30)

    changed = apply_change(plan, DateMoved(new_start_date=new_start), _ctx())

    assert (changed.event.start_date, changed.event.end_date) == (
        new_start,
        new_start + timedelta(days=1),
    )
    assert changed.functions[0].start.date() == new_start
    assert changed.tasks[0].due_date == plan.tasks[0].due_date + timedelta(days=30)


def test_date_moved_earlier_flags_tasks() -> None:
    today = DAY0 - timedelta(days=150)
    plan = _plan(today)

    changed = apply_change(plan, DateMoved(new_start_date=today + timedelta(days=30)), _ctx(today))
    result = impact(plan, changed, today)

    assert result.newly_flagged_task_ids


def test_function_dropped_frees_open_lines_and_keeps_locked_ones() -> None:
    plan = _plan()
    venue = _line(plan, "venue", "haldi")
    plan = _with_line(plan, venue.id, status="paid", actual=venue.planned)

    changed = apply_change(plan, FunctionDropped(function_id="haldi"), _ctx())
    result = impact(plan, changed, FAR_AHEAD)

    assert [f.id for f in changed.functions] == ["reception"]
    kept = next(i for i in changed.line_items if i.id == venue.id)
    assert kept.function_id is None
    assert kept.planned == venue.planned
    assert not any(i.function_id == "haldi" for i in changed.line_items)
    assert not any(t.function_id == "haldi" for t in changed.tasks)
    assert result.unallocated > 0


@pytest.mark.parametrize(
    "change",
    [VendorCancelled(line_item_id="nope"), FunctionDropped(function_id="nope")],
)
def test_unknown_ids_rejected(change: Any) -> None:
    with pytest.raises(ValueError, match="nope"):
        apply_change(_plan(), change, _ctx())


# apply_ops


def test_apply_ops_returns_a_new_plan() -> None:
    plan = _plan()
    snapshot = plan.model_dump_json()

    result = apply_ops(plan, [ScaleCategory(category="decor", percent=-50)], _ctx())

    assert plan.model_dump_json() == snapshot
    decor_before = sum(i.planned for i in plan.line_items if i.category == "decor")
    decor_after = sum(i.planned for i in result.line_items if i.category == "decor")
    assert decor_after == decor_before * 50 // 100


def test_reduce_guests_scales_per_plate_lines() -> None:
    plan = _plan()

    result = apply_ops(plan, [ReduceGuests(function_id="reception", guests=300)], _ctx())

    reception = next(f for f in result.functions if f.id == "reception")
    assert reception.guests == 300
    assert _line(result, "catering", "reception").planned < _line(
        plan, "catering", "reception"
    ).planned


def test_drop_item_cancels_line_and_removes_its_task() -> None:
    plan = _plan()
    decor = _line(plan, "decor", "haldi")

    result = apply_ops(plan, [DropItem(line_item_id=decor.id)], _ctx())

    assert next(i for i in result.line_items if i.id == decor.id).status == "cancelled"
    assert not any(t.category == "decor" and t.function_id == "haldi" for t in result.tasks)


@pytest.mark.parametrize(
    ("op", "message"),
    [
        (ReduceGuests(function_id="nope", guests=10), "unknown function"),
        (ReduceGuests(function_id="reception", guests=400), "lower the guest count"),
        (ChangeTier(function_id="reception", tier="premium"), "change the tier"),
        (ScaleCategory(category="cake", percent=-10), "no adjustable"),
        (DropItem(line_item_id="nope"), "no active line item"),
    ],
)
def test_invalid_ops_rejected(op: Any, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        apply_ops(_plan(), [op], _ctx())


def test_drop_locked_item_rejected() -> None:
    plan = _plan()
    venue = _line(plan, "venue", "reception")
    plan = _with_line(plan, venue.id, status="booked")

    with pytest.raises(ValueError, match="locked"):
        apply_ops(plan, [DropItem(line_item_id=venue.id)], _ctx())


# verify_option


def _cut(plan: Plan, new_total: int = 2_000_000) -> Plan:
    return apply_change(plan, BudgetCut(new_total=new_total), _ctx())


def test_verify_keeps_option_that_clears_overrun() -> None:
    plan = _plan()
    changed = _cut(plan)
    option = Option(
        id="o1",
        rationale="Simpler reception",
        ops=[
            ChangeTier(function_id="reception", tier="standard"),
            ScaleCategory(category="attire", percent=-50),
        ],
    )

    verified = verify_option(plan, changed, option, _ctx())

    assert verified is not None
    assert verified.result is not None
    assert verified.result.over_by == 0
    assert verified.result.total_committed <= 2_000_000


def test_verify_drops_option_that_leaves_overrun() -> None:
    plan = _plan()
    option = Option(
        id="o1", rationale="Small trim", ops=[ScaleCategory(category="cake", percent=-10)]
    )
    small = Option(
        id="o2", rationale="Small trim", ops=[ScaleCategory(category="decor", percent=-5)]
    )

    assert verify_option(plan, _cut(plan), option, _ctx()) is None
    assert verify_option(plan, _cut(plan), small, _ctx()) is None


def test_verify_drops_option_with_unknown_ids() -> None:
    plan = _plan()
    option = Option(id="o1", rationale="Bad", ops=[DropItem(line_item_id="ghost")])

    assert verify_option(plan, _cut(plan), option, _ctx()) is None


# rule_based_options


def test_rule_based_options_for_budget_cut() -> None:
    plan = _plan()
    venue = _line(plan, "venue", "reception")
    plan = _with_line(plan, venue.id, status="booked")
    changed = _cut(plan)

    options = rule_based_options(plan, changed, BudgetCut(new_total=2_000_000), _ctx())

    assert options
    assert len({tuple(map(str, o.ops)) for o in options}) == len(options)
    for option in options:
        assert option.result is not None
        assert option.result.over_by == 0
        result = apply_ops(changed, option.ops, _ctx())
        assert budget_status(result)[1] == 0
        assert _locked(result) == _locked(changed)


def test_rule_based_options_for_vendor_cancelled() -> None:
    plan = _plan()
    caterer = _line(plan, "catering", "reception")
    change = VendorCancelled(line_item_id=caterer.id)
    ctx = _ctx(THREE_WEEKS_OUT)
    changed = apply_change(plan, change, ctx)

    options = rule_based_options(plan, changed, change, ctx)

    rationales = [o.rationale for o in options]
    assert "Skip this vendor and keep the money" in rationales
    assert "Book a simpler replacement" in rationales
    skip = next(o for o in options if o.rationale.startswith("Skip"))
    after = apply_ops(changed, skip.ops, ctx)
    assert flagged_task_ids(after, THREE_WEEKS_OUT) <= flagged_task_ids(changed, THREE_WEEKS_OUT)


def test_no_options_when_nothing_is_wrong() -> None:
    plan = _plan()
    change = DateMoved(new_start_date=DAY0 + timedelta(days=7))

    assert rule_based_options(plan, apply_change(plan, change, _ctx()), change, _ctx()) == []


def test_unfixable_overrun_returns_no_options() -> None:
    plan = _plan()
    for item in plan.line_items:
        plan = _with_line(plan, item.id, status="booked")
    changed = _cut(plan)

    assert rule_based_options(plan, changed, BudgetCut(new_total=2_000_000), _ctx()) == []


@pytest.mark.parametrize(
    "make_change",
    [
        lambda p: BudgetCut(new_total=1_800_000),
        lambda p: GuestsChanged(guests=700),
        lambda p: VendorCancelled(line_item_id=_line(p, "decor", "reception").id),
        lambda p: DateMoved(new_start_date=DAY0 + timedelta(days=3)),
        lambda p: FunctionDropped(function_id="reception"),
    ],
)
def test_locked_lines_never_change(make_change: Any) -> None:
    plan = _plan()
    for category, function_id in [("venue", "reception"), ("attire", None)]:
        line = _line(plan, category, function_id)
        plan = _with_line(plan, line.id, status="paid", actual=line.planned)
    locked_before = {k: v.model_dump(exclude={"function_id"}) for k, v in _locked(plan).items()}
    change = make_change(plan)

    changed = apply_change(plan, change, _ctx())
    for option in rule_based_options(plan, changed, change, _ctx()):
        fixed = apply_ops(changed, option.ops, _ctx())
        assert {
            k: v.model_dump(exclude={"function_id"}) for k, v in _locked(fixed).items()
        } == locked_before

    assert {
        k: v.model_dump(exclude={"function_id"}) for k, v in _locked(changed).items()
    } == locked_before
