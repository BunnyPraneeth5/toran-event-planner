import itertools
from datetime import date, timedelta
from typing import Any

import pytest

from app.data.loader import ReferenceData, load_reference_data
from app.engines.budget import allocate
from app.engines.timeline import assess_tasks, build_tasks, flagged_task_ids, target_date
from app.models import Function, Plan
from tests.factories import DAY0, make_event, make_function


@pytest.fixture(scope="module")
def ref() -> ReferenceData:
    return load_reference_data()


def _counter(prefix: str) -> Any:
    counter = itertools.count(1)
    return lambda: f"{prefix}{next(counter)}"


def _functions() -> list[Function]:
    return [
        make_function("haldi", day=0, hour=10, guests=100, tier="budget"),
        make_function("reception", day=1, hour=19, guests=400, tier="premium"),
    ]


def _plan(ref: ReferenceData, today: date, functions: list[Function] | None = None) -> Plan:
    event = make_event()
    functions = functions if functions is not None else _functions()
    items = allocate(
        event,
        functions,
        ref.categories.default_weights["wedding"],
        ref.categories.categories,
        ref.categories.tier_multipliers,
        id_factory=_counter("li"),
    )
    base = Plan(event=event, functions=functions, line_items=items)
    tasks = build_tasks(base, ref.lead_times.lead_times, today, id_factory=_counter("t"))
    return Plan(event=event, functions=functions, line_items=items, tasks=tasks)


def _task(plan: Plan, category: str, function_id: str | None = None) -> Any:
    return next(t for t in plan.tasks if t.category == category and t.function_id == function_id)


def _assessment(plan: Plan, today: date, task_id: str) -> Any:
    return next(a for a in assess_tasks(plan, today) if a.task_id == task_id)


FAR_AHEAD = DAY0 - timedelta(days=365)


def test_tasks_scheduled_backward_from_function_date(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    reception_date = DAY0 + timedelta(days=1)
    assert _task(plan, "catering", "reception").due_date == reception_date - timedelta(days=120)
    assert _task(plan, "catering", "haldi").due_date == DAY0 - timedelta(days=120)


def test_event_wide_tasks_count_back_from_event_start(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    attire = _task(plan, "attire")
    assert attire.due_date == DAY0 - timedelta(days=150)
    assert attire.title == "Order outfits and jewellery"


def test_one_task_per_active_line_with_function_name(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    assert len(plan.tasks) == len(plan.line_items)
    assert _task(plan, "venue", "reception").title == "Book the venue: Reception"


def test_tasks_sorted_by_due_date(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    dues = [t.due_date for t in plan.tasks]
    assert dues == sorted(dues)


@pytest.mark.parametrize("offset", [-400, -180, -21, -1, 0, 1, 3, 30])
def test_no_task_due_after_event(ref: ReferenceData, offset: int) -> None:
    plan = _plan(ref, DAY0 + timedelta(days=offset))

    assert all(t.due_date <= plan.event.end_date for t in plan.tasks)


def test_on_track_when_plenty_of_time(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    assert flagged_task_ids(plan, FAR_AHEAD) == set()


def test_event_three_weeks_away_marks_long_lead_tasks_at_risk(ref: ReferenceData) -> None:
    today = DAY0 - timedelta(days=21)
    plan = _plan(ref, today)

    venue = _task(plan, "venue", "haldi")
    assert venue.due_date == today
    venue_status = _assessment(plan, today, venue.id)
    assert venue_status.at_risk is True
    assert venue_status.late is False
    assert venue_status.ready_by == today + timedelta(days=180)
    assert all(t.due_date >= today for t in plan.tasks)

    other_task = _task(plan, "other")
    other_status = _assessment(plan, today, other_task.id)
    assert other_status.at_risk is False
    assert other_status.ready_by is None


def test_late_once_due_date_passes(ref: ReferenceData) -> None:
    built_on = FAR_AHEAD
    plan = _plan(ref, built_on)
    venue = _task(plan, "venue", "haldi")

    status = _assessment(plan, venue.due_date + timedelta(days=1), venue.id)

    assert status.late is True
    assert status.at_risk is True
    assert status.days_until_due == -1


def test_done_tasks_are_never_flagged(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)
    data = plan.model_dump()
    for task in data["tasks"]:
        task["status"] = "done"
    done = Plan.model_validate(data)

    assert flagged_task_ids(done, DAY0) == set()


def test_booked_lines_get_done_tasks_and_cancelled_get_none(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)
    data = plan.model_dump()
    data["tasks"] = []
    data["line_items"][0]["status"] = "booked"
    data["line_items"][1]["status"] = "cancelled"
    changed = Plan.model_validate(data)

    tasks = build_tasks(changed, ref.lead_times.lead_times, FAR_AHEAD)

    booked, cancelled = data["line_items"][0], data["line_items"][1]
    booked_task = next(
        t
        for t in tasks
        if t.category == booked["category"] and t.function_id == booked["function_id"]
    )
    assert booked_task.status == "done"
    assert not any(
        t.category == cancelled["category"] and t.function_id == cancelled["function_id"]
        for t in tasks
    )


def test_overnight_function_stays_within_event_dates(ref: ReferenceData) -> None:
    overnight = make_function("sangeet", day=1, hour=22, duration_minutes=300, guests=300)

    plan = _plan(ref, FAR_AHEAD, functions=[overnight])

    assert overnight.end.date() == plan.event.end_date + timedelta(days=1)
    assert target_date(plan, "sangeet") == plan.event.end_date
    assert all(t.due_date <= plan.event.end_date for t in plan.tasks)


def test_target_date_falls_back_to_event_start(ref: ReferenceData) -> None:
    plan = _plan(ref, FAR_AHEAD)

    assert target_date(plan, None) == DAY0
    assert target_date(plan, "unknown") == DAY0
