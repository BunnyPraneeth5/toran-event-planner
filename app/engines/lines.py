"""Bookings engine: mark a budget line planned, booked or paid, with its actual cost.

Booked and paid lines lock (a LineItem rule), so what-if and Something changed never move
them, and their actual cost is what counts towards the budget. The line's task follows.
"""

from app.models.event import LineItem, Task
from app.models.lines import BookingStatus
from app.models.plan import Plan


def update_line(
    plan: Plan, line_item_id: str, status: BookingStatus, actual: int | None
) -> Plan:
    """A new plan with one line's status and actual cost set, and its task updated.

    Marking a line planned unlocks it and clears its actual cost, which only counts once
    the line is booked. Raises ValueError for an unknown or cancelled line.
    """
    item = next((i for i in plan.line_items if i.id == line_item_id), None)
    if item is None:
        raise ValueError(f"unknown line item {line_item_id}")
    if not item.active:
        raise ValueError("this line was cancelled, so it cannot be booked")
    booked = status != "planned"
    updated = LineItem.model_validate(
        {
            **item.model_dump(),
            "status": status,
            "actual": actual if booked else None,
            "locked": booked,
        }
    )
    items = [updated if i.id == line_item_id else i for i in plan.line_items]
    tasks = [_follow(t, updated, items) for t in plan.tasks]
    return Plan(
        event=plan.event,
        functions=plan.functions,
        line_items=items,
        tasks=tasks,
        people=plan.people,
        ideas=plan.ideas,
        sources=plan.sources,
    )


def over_plan(item: LineItem) -> int:
    """How far a booked or paid line's actual cost is above its plan, else 0."""
    if not item.locked or item.actual is None:
        return 0
    return max(0, item.actual - item.planned)


def _follow(task: Task, changed: LineItem, items: list[LineItem]) -> Task:
    """The task for the changed line: done once any matching line is booked, else to-do."""
    if (task.function_id, task.category) != (changed.function_id, changed.category):
        return task
    booked = any(
        i.active and i.locked and (i.function_id, i.category) == (task.function_id, task.category)
        for i in items
    )
    if booked:
        return task.model_copy(update={"status": "done"})
    if task.status == "done":
        return task.model_copy(update={"status": "todo"})
    return task
