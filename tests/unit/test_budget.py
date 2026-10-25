import itertools
import random
from collections.abc import Callable
from typing import Any

import pytest

from app.data.loader import ReferenceData, load_reference_data
from app.engines.budget import allocate, realism_warnings, split, what_if
from app.models import Function, Plan
from app.models.budget import SetCategory, SetFunctionGuests, SetGuests, SetTier, SetTotal
from app.models.common import EventType
from tests.factories import make_event, make_function


@pytest.fixture(scope="module")
def ref() -> ReferenceData:
    return load_reference_data()


def _ids() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"li{next(counter)}"


def _functions() -> list[Function]:
    return [
        make_function("haldi", day=0, hour=10, guests=100, tier="budget"),
        make_function("reception", day=1, hour=19, guests=400, tier="premium"),
    ]


def _plan(ref: ReferenceData, total: int = 2_500_000, event_type: EventType = "wedding") -> Plan:
    event = make_event(total_budget=total, type=event_type)
    functions = _functions()
    items = allocate(
        event,
        functions,
        ref.categories.default_weights[event_type],
        ref.categories.categories,
        ref.categories.tier_multipliers,
        id_factory=_ids(),
    )
    return Plan(event=event, functions=functions, line_items=items)


def _committed(plan: Plan) -> int:
    return sum(i.spend if i.locked else i.planned for i in plan.line_items if i.active)


def _with_item(plan: Plan, item_id: str, **patch: Any) -> Plan:
    data = plan.model_dump()
    for item in data["line_items"]:
        if item["id"] == item_id:
            item.update(patch)
    return Plan.model_validate(data)


def _item(plan: Plan, category: str, function_id: str | None = None) -> Any:
    return next(
        i for i in plan.line_items if i.category == category and i.function_id == function_id
    )


def _run(plan: Plan, ref: ReferenceData, *changes: Any) -> Any:
    return what_if(plan, changes, ref.categories.categories, ref.categories.tier_multipliers)


# split


def test_split_sums_exactly() -> None:
    rng = random.Random(7)
    for _ in range(500):
        total = rng.randint(0, 10**9)
        weights = [rng.randint(0, 1000) for _ in range(rng.randint(1, 12))]
        parts = split(total, weights)
        assert sum(parts) == total
        assert all(p >= 0 for p in parts)


def test_split_ties_go_to_earlier_index() -> None:
    assert split(10, [1, 1, 1]) == [4, 3, 3]


def test_split_zero_weights_split_equally() -> None:
    assert split(10, [0, 0]) == [5, 5]


def test_split_empty() -> None:
    assert split(0, []) == []


def test_split_rejects_negative() -> None:
    with pytest.raises(ValueError, match="weights"):
        split(10, [1, -1])
    with pytest.raises(ValueError, match="total"):
        split(-1, [1])


# allocate


@pytest.mark.parametrize("event_type", ["wedding", "birthday", "community"])
@pytest.mark.parametrize("total", [1_000, 1_234_567, 2_500_000, 1_000_000_000])
def test_allocate_sums_to_total(ref: ReferenceData, event_type: EventType, total: int) -> None:
    plan = _plan(ref, total=total, event_type=event_type)

    assert sum(i.planned for i in plan.line_items) == total


def test_allocate_splits_per_plate_by_guests_and_tier(ref: ReferenceData) -> None:
    plan = _plan(ref)

    haldi = _item(plan, "catering", "haldi").planned
    reception = _item(plan, "catering", "reception").planned
    # haldi weight 100 guests x 70, reception 400 guests x 160
    assert reception > haldi * 9
    assert _item(plan, "music_entertainment", "haldi").planned == pytest.approx(
        _item(plan, "music_entertainment", "reception").planned, abs=1
    )


def test_allocate_event_scoped_lines_have_no_function(ref: ReferenceData) -> None:
    plan = _plan(ref)

    assert _item(plan, "attire").function_id is None
    assert {i.function_id for i in plan.line_items if i.category == "venue"} == {
        "haldi",
        "reception",
    }


def test_allocate_single_category(ref: ReferenceData) -> None:
    items = allocate(
        make_event(total_budget=50_000),
        [],
        {"other": 100},
        ref.categories.categories,
        ref.categories.tier_multipliers,
    )

    assert [(i.category, i.planned) for i in items] == [("other", 50_000)]


def test_allocate_rejects_bad_weights(ref: ReferenceData) -> None:
    args = (make_event(), _functions())
    cats, tiers = ref.categories.categories, ref.categories.tier_multipliers

    with pytest.raises(ValueError, match="unknown categories"):
        allocate(*args, {"fireworks": 100}, cats, tiers)
    with pytest.raises(ValueError, match="positive weight"):
        allocate(*args, {"venue": 0}, cats, tiers)


# what_if


def test_lower_total_rebalances_and_keeps_locked(ref: ReferenceData) -> None:
    venue = _item(_plan(ref), "venue", "reception")
    plan = _with_item(_plan(ref), venue.id, status="booked")

    result = _run(plan, ref, SetTotal(total=2_000_000))

    assert _committed(result.plan) == 2_000_000
    assert result.plan.event.total_budget == 2_000_000
    assert _item(result.plan, "venue", "reception") == _item(plan, "venue", "reception")
    assert result.over_by == 0
    assert result.unallocated == 0


def test_set_category_pins_it_and_others_absorb(ref: ReferenceData) -> None:
    result = _run(_plan(ref), ref, SetCategory(category="catering", amount=900_000))

    catering = sum(i.planned for i in result.plan.line_items if i.category == "catering")
    assert catering == 900_000
    assert _committed(result.plan) == 2_500_000


def test_set_category_counts_locked_lines(ref: ReferenceData) -> None:
    plan = _plan(ref)
    plan = _with_item(plan, _item(plan, "catering", "haldi").id, status="paid", actual=100_000)

    result = _run(plan, ref, SetCategory(category="catering", amount=700_000))

    assert _item(result.plan, "catering", "reception").planned == 600_000


def test_more_guests_scale_per_plate_lines(ref: ReferenceData) -> None:
    plan = _plan(ref)
    before = _item(plan, "catering", "reception").planned

    result = _run(plan, ref, SetGuests(guests=500))

    reception = next(f for f in result.plan.functions if f.id == "reception")
    assert reception.guests == 500
    assert result.plan.event.guests == 500
    assert _item(result.plan, "catering", "reception").planned == (before * 500 + 200) // 400
    assert _committed(result.plan) == 2_500_000


def test_function_guest_override_survives_event_guest_change(ref: ReferenceData) -> None:
    result = _run(
        _plan(ref),
        ref,
        SetFunctionGuests(function_id="haldi", guests=60),
        SetGuests(guests=800),
    )

    guests = {f.id: (f.guests, f.guests_override) for f in result.plan.functions}
    assert guests["haldi"] == (60, True)
    assert guests["reception"] == (800, False)


def test_cheaper_tier_frees_money_for_other_lines(ref: ReferenceData) -> None:
    plan = _plan(ref)
    venue_before = _item(plan, "venue", "reception").planned
    attire_before = _item(plan, "attire").planned

    result = _run(plan, ref, SetTier(function_id="reception", tier="standard"))

    assert _item(result.plan, "venue", "reception").planned == (venue_before * 100 + 80) // 160
    assert _item(result.plan, "attire").planned > attire_before
    assert _committed(result.plan) == 2_500_000


def test_overrun_reported_when_locked_spend_exceeds_total(ref: ReferenceData) -> None:
    plan = _plan(ref)
    plan = _with_item(plan, _item(plan, "venue", "reception").id, status="paid", actual=1_500_000)
    plan = _with_item(plan, _item(plan, "attire").id, status="booked", actual=900_000)

    result = _run(plan, ref, SetTotal(total=2_000_000))

    assert result.over_by == _committed(result.plan) - 2_000_000
    assert result.over_by > 0
    assert result.warnings[0].kind == "over_budget"
    assert result.warnings[0].amount == result.over_by
    assert _item(result.plan, "venue", "reception").actual == 1_500_000


def test_all_lines_locked_reports_unallocated(ref: ReferenceData) -> None:
    plan = _plan(ref)
    for item in plan.line_items:
        plan = _with_item(plan, item.id, status="booked")

    result = _run(plan, ref, SetTotal(total=3_000_000))

    assert result.unallocated == 500_000
    assert result.plan.line_items == plan.line_items


def test_cancelled_lines_are_ignored(ref: ReferenceData) -> None:
    plan = _plan(ref)
    decor = _item(plan, "decor", "haldi")
    plan = _with_item(plan, decor.id, status="cancelled")

    result = _run(plan, ref, SetTotal(total=2_000_000))

    assert _item(result.plan, "decor", "haldi").planned == decor.planned
    assert _committed(result.plan) == 2_000_000


def test_what_if_does_not_mutate_input(ref: ReferenceData) -> None:
    plan = _plan(ref)
    snapshot = plan.model_dump_json()

    _run(plan, ref, SetTotal(total=1_500_000), SetGuests(guests=600))

    assert plan.model_dump_json() == snapshot


def test_unknown_function_rejected(ref: ReferenceData) -> None:
    with pytest.raises(ValueError, match="unknown function"):
        _run(_plan(ref), ref, SetTier(function_id="nope", tier="budget"))


def test_category_without_adjustable_lines_rejected(ref: ReferenceData) -> None:
    with pytest.raises(ValueError, match="no adjustable"):
        _run(_plan(ref), ref, SetCategory(category="cake", amount=10_000))


# realism


def test_realism_flags_thin_catering(ref: ReferenceData) -> None:
    plan = _plan(ref, total=300_000)
    cats = ref.categories.categories

    warnings = realism_warnings(plan, cats, ref.city_multiplier("Jodhpur"))
    reception = next(w for w in warnings if w.function_id == "reception")

    typical = 350 * 80 * 400 // 100
    assert reception.kind == "below_typical"
    assert reception.amount == typical - _item(plan, "catering", "reception").planned
    metro = realism_warnings(plan, cats, ref.city_multiplier("Mumbai"))
    assert sum(w.amount for w in metro) > sum(w.amount for w in warnings)


def test_realism_quiet_for_healthy_budget(ref: ReferenceData) -> None:
    plan = _plan(ref, total=5_000_000)

    assert realism_warnings(plan, ref.categories.categories, 100) == []
