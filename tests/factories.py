"""Small builders for test data. Tests only."""

import itertools
from datetime import date, datetime, time, timedelta
from typing import Any

from app.data.loader import load_reference_data
from app.engines.budget import allocate
from app.engines.timeline import build_tasks
from app.models import IST, Event, Function, LineItem, Person, Plan, Task

DAY0 = date(2027, 2, 10)


def make_event(**overrides: Any) -> Event:
    data: dict[str, Any] = {
        "id": "ev1",
        "type": "wedding",
        "title": "Sister's wedding",
        "city": "Jodhpur",
        "start_date": DAY0,
        "end_date": DAY0 + timedelta(days=1),
        "guests": 400,
        "total_budget": 2_500_000,
    }
    data.update(overrides)
    return Event.model_validate(data)


def make_function(fid: str, day: int = 0, hour: int = 10, **overrides: Any) -> Function:
    data: dict[str, Any] = {
        "id": fid,
        "name": fid.title(),
        "start": datetime.combine(DAY0 + timedelta(days=day), time(hour), tzinfo=IST),
        "duration_minutes": 180,
        "guests": 200,
    }
    data.update(overrides)
    return Function.model_validate(data)


def make_allocated_plan(today: date = DAY0 - timedelta(days=365)) -> Plan:
    """A realistic plan: two functions (haldi, reception), allocated lines li1.., tasks t1.."""
    ref = load_reference_data()
    event = make_event()
    functions = [
        make_function("haldi", day=0, hour=10, guests=100, tier="budget"),
        make_function("reception", day=1, hour=19, guests=400, tier="premium"),
    ]
    line_ids, task_ids = itertools.count(1), itertools.count(1)
    items = allocate(
        event,
        functions,
        ref.categories.default_weights["wedding"],
        ref.categories.categories,
        ref.categories.tier_multipliers,
        id_factory=lambda: f"li{next(line_ids)}",
    )
    base = Plan(event=event, functions=functions, line_items=items)
    tasks = build_tasks(
        base, ref.lead_times.lead_times, today, id_factory=lambda: f"t{next(task_ids)}"
    )
    return Plan(event=event, functions=functions, line_items=items, tasks=tasks)


def make_plan(**overrides: Any) -> Plan:
    data: dict[str, Any] = {
        "event": make_event(),
        "functions": [
            make_function("haldi", day=0, hour=10, guests=100),
            make_function("reception", day=1, hour=19, guests=400),
        ],
        "people": [
            Person(id="bride_side", name="Bride's family", side_or_role="bride side"),
            Person(id="groom_side", name="Groom's family", side_or_role="groom side"),
        ],
        "line_items": [
            LineItem(id="li1", function_id="reception", category="catering", planned=800_000),
            LineItem(id="li2", function_id=None, category="attire", planned=300_000),
        ],
        "tasks": [
            Task(
                id="t1",
                title="Book the venue",
                category="venue",
                due_date=DAY0 - timedelta(days=180),
                lead_days=180,
                owner_id="bride_side",
            )
        ],
    }
    data.update(overrides)
    return Plan.model_validate(data)
