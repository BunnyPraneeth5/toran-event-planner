import pytest

from app.engines.budget import budget_status, what_if
from app.engines.lines import over_plan, update_line
from app.models import LineItem, Plan, Task
from app.models.budget import SetTotal
from tests.factories import make_allocated_plan, make_plan

TASK_DAY = make_plan().tasks[0].due_date


def _plan() -> Plan:
    """Two catering lines and a task for each, plus attire with no task."""
    return make_plan(
        line_items=[
            LineItem(id="cat", function_id="reception", category="catering", planned=800_000),
            LineItem(id="att", function_id=None, category="attire", planned=300_000),
        ],
        tasks=[
            Task(
                id="t_cat",
                title="Book the caterer",
                function_id="reception",
                category="catering",
                due_date=TASK_DAY,
                lead_days=60,
            ),
            Task(
                id="t_att",
                title="Buy attire",
                category="attire",
                due_date=TASK_DAY,
                lead_days=60,
                status="doing",
            ),
        ],
    )


def _line(plan: Plan, line_id: str) -> LineItem:
    return next(i for i in plan.line_items if i.id == line_id)


def _task(plan: Plan, task_id: str) -> Task:
    return next(t for t in plan.tasks if t.id == task_id)


def test_booking_locks_the_line_and_marks_its_task_done() -> None:
    plan = _plan()

    booked = update_line(plan, "cat", "booked", None)

    assert (_line(booked, "cat").status, _line(booked, "cat").locked) == ("booked", True)
    assert _task(booked, "t_cat").status == "done"
    assert _task(booked, "t_att").status == "doing"
    assert _line(plan, "cat").status == "planned"


def test_paid_with_actual_counts_actual_towards_budget() -> None:
    plan = _plan()
    before, _, _ = budget_status(plan)

    paid = update_line(plan, "cat", "paid", 820_000)

    item = _line(paid, "cat")
    assert (item.status, item.actual, item.locked) == ("paid", 820_000, True)
    assert budget_status(paid)[0] == before + 20_000
    assert over_plan(item) == 20_000


def test_unbooking_unlocks_clears_actual_and_reopens_task() -> None:
    paid = update_line(_plan(), "cat", "paid", 820_000)

    unbooked = update_line(paid, "cat", "planned", 900_000)

    item = _line(unbooked, "cat")
    assert (item.status, item.locked, item.actual) == ("planned", False, None)
    assert _task(unbooked, "t_cat").status == "todo"
    assert over_plan(item) == 0


def test_unbooking_leaves_unrelated_open_tasks_alone() -> None:
    unbooked = update_line(_plan(), "att", "planned", None)

    assert _task(unbooked, "t_att").status == "doing"


def test_under_plan_actual_is_not_over() -> None:
    item = _line(update_line(_plan(), "cat", "booked", 700_000), "cat")

    assert over_plan(item) == 0


@pytest.mark.parametrize(
    ("line", "message"), [("missing", "unknown line item"), ("cancelled", "cancelled")]
)
def test_refuses_unknown_and_cancelled_lines(line: str, message: str) -> None:
    plan = _plan()
    cancelled = LineItem(id="cancelled", category="decor", planned=1, status="cancelled")
    plan = plan.model_copy(update={"line_items": [*plan.line_items, cancelled]})

    with pytest.raises(ValueError, match=message):
        update_line(plan, line, "booked", None)


def test_booked_line_is_unchanged_by_a_later_what_if() -> None:
    plan = make_allocated_plan()
    target = plan.line_items[0]
    booked = update_line(plan, target.id, "booked", target.planned + 5_000)

    result = what_if(booked, [SetTotal(change="set_total", total=1_500_000)], [], {})

    after = _line(result.plan, target.id)
    assert (after.planned, after.actual, after.status) == (
        target.planned,
        target.planned + 5_000,
        "booked",
    )
