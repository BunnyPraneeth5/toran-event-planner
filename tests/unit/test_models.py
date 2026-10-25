from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models import IST, Change, LineItem, Option, Plan, Task
from app.models.change import BudgetCut, ScaleCategory
from tests.factories import DAY0, make_event, make_function, make_plan


def test_plan_round_trips_through_json() -> None:
    plan = make_plan()

    restored = Plan.model_validate_json(plan.model_dump_json())

    assert restored == plan
    assert restored.schema_version == 1


@pytest.mark.parametrize("bad", [1000.0, 1000.5, -1, True, "1000"])
def test_money_must_be_non_negative_int(bad: object) -> None:
    with pytest.raises(ValidationError):
        LineItem.model_validate({"id": "x", "category": "venue", "planned": bad})


def test_money_float_rejected_in_json() -> None:
    raw = '{"id": "x", "category": "venue", "planned": 1000.0}'

    with pytest.raises(ValidationError):
        LineItem.model_validate_json(raw)


def test_function_start_is_converted_to_ist() -> None:
    utc_start = datetime(2027, 2, 10, 4, 30, tzinfo=UTC)

    function = make_function("haldi", start=utc_start)

    assert function.start.utcoffset() == timedelta(hours=5, minutes=30)
    assert function.start.hour == 10
    assert function.end == function.start + timedelta(minutes=180)


def test_function_start_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        make_function("haldi", start=datetime(2027, 2, 10, 10, 0))


def test_overnight_function_is_valid() -> None:
    function = make_function("sangeet", hour=22, duration_minutes=300)

    assert function.end.date() == DAY0 + timedelta(days=1)


@pytest.mark.parametrize("status", ["booked", "paid"])
def test_booked_or_paid_lines_are_locked(status: str) -> None:
    item = LineItem.model_validate(
        {"id": "x", "category": "venue", "planned": 1, "status": status, "locked": False}
    )

    assert item.locked is True


def test_cancelled_lines_are_never_locked() -> None:
    item = LineItem.model_validate(
        {"id": "x", "category": "venue", "planned": 1, "status": "cancelled", "locked": True}
    )

    assert item.locked is False
    assert item.active is False


def test_spend_prefers_actual() -> None:
    assert LineItem(id="x", category="venue", planned=100).spend == 100
    assert LineItem(id="x", category="venue", planned=100, actual=150).spend == 150


def _item_with_payers(*shares: tuple[str, int]) -> LineItem:
    payers = [{"person_id": pid, "share_pct": pct} for pid, pct in shares]
    return LineItem.model_validate(
        {"id": "x", "category": "venue", "planned": 1, "payers": payers}
    )


def test_payer_shares_must_sum_to_100() -> None:
    assert len(_item_with_payers(("a", 50), ("b", 50)).payers) == 2
    with pytest.raises(ValidationError, match="sum to 100"):
        _item_with_payers(("a", 50), ("b", 40))


def test_payer_listed_twice_rejected() -> None:
    with pytest.raises(ValidationError, match="twice"):
        _item_with_payers(("a", 50), ("a", 50))


def test_task_stores_no_late_flag() -> None:
    assert not {"is_late", "late", "at_risk"} & set(Task.model_fields)


@pytest.mark.parametrize(
    ("section", "patch", "message"),
    [
        ("line_items", {"function_id": "nope"}, "unknown function"),
        ("line_items", {"payers": [{"person_id": "nobody", "share_pct": 100}]}, "unknown payer"),
        ("tasks", {"owner_id": "nobody"}, "unknown owner"),
        ("tasks", {"function_id": "nope"}, "unknown function"),
    ],
)
def test_dangling_references_rejected(section: str, patch: dict[str, object], message: str) -> None:
    data = make_plan().model_dump()
    data[section][0].update(patch)

    with pytest.raises(ValidationError, match=message):
        Plan.model_validate(data)


def test_duplicate_ids_rejected() -> None:
    data = make_plan().model_dump()
    data["line_items"][1]["id"] = data["line_items"][0]["id"]

    with pytest.raises(ValidationError, match="duplicate id"):
        Plan.model_validate(data)


def test_function_outside_event_dates_rejected() -> None:
    with pytest.raises(ValidationError, match="outside the event dates"):
        make_plan(functions=[make_function("late", day=5)], line_items=[])


def test_task_after_event_rejected() -> None:
    data = make_plan().model_dump()
    data["tasks"][0]["due_date"] = DAY0 + timedelta(days=10)

    with pytest.raises(ValidationError, match="due after the event"):
        Plan.model_validate(data)


def test_event_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError, match="before start_date"):
        make_event(end_date=DAY0 - timedelta(days=1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "x" * 121},
        {"style_notes": "x" * 501},
        {"guests": 0},
        {"guests": 5001},
        {"total_budget": 999},
        {"city": "   "},
    ],
)
def test_event_limits_enforced(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_event(**overrides)


def test_function_count_limited() -> None:
    functions = [make_function(f"f{i}") for i in range(13)]

    with pytest.raises(ValidationError):
        make_plan(functions=functions, line_items=[])


def test_unknown_fields_rejected() -> None:
    data = make_plan().model_dump()
    data["event"]["is_admin"] = True

    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_change_parses_by_kind() -> None:
    change = TypeAdapter(Change).validate_python({"kind": "budget_cut", "new_total": 2_000_000})

    assert isinstance(change, BudgetCut)


def test_scale_category_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        ScaleCategory(category="decor", percent=0)


def test_option_rationale_must_not_contain_digits() -> None:
    ops = [{"op": "drop_item", "line_item_id": "li1"}]

    Option.model_validate({"id": "o1", "rationale": "Trim decor at haldi", "ops": ops})
    with pytest.raises(ValidationError, match="numbers"):
        Option.model_validate({"id": "o1", "rationale": "Save 2 lakh on decor", "ops": ops})


def test_ist_is_fixed_offset() -> None:
    assert IST.utcoffset(None) == timedelta(hours=5, minutes=30)
