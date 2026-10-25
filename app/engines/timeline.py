"""Timeline engine: backward schedule from function dates, plus late and at-risk flags.

`today` is always passed in (as an IST date) so results are reproducible and testable.
"""

from collections.abc import Callable, Sequence
from datetime import date, timedelta

from app.data.loader import LeadTime
from app.models.common import new_id
from app.models.event import Task
from app.models.plan import Plan
from app.models.timeline import TaskAssessment

MAX_TITLE = 120


def target_date(plan: Plan, function_id: str | None) -> date:
    """The day a task's work is needed: its function's start date, else the event start."""
    for function in plan.functions:
        if function.id == function_id:
            return function.start.date()
    return plan.event.start_date


def build_tasks(
    plan: Plan,
    lead_times: Sequence[LeadTime],
    today: date,
    id_factory: Callable[[], str] = new_id,
) -> list[Task]:
    """One task per active line item, due `lead_days` before the date it serves.

    When the ideal due date has already passed, the task is due today instead (it will
    show as at risk), never in the past. Due dates never fall after the target date, so
    never after the event. Lines that are already booked or paid get a done task.
    """
    leads = {lt.category: lt for lt in lead_times}
    names = {f.id: f.name for f in plan.functions}
    tasks: list[Task] = []
    for item in plan.line_items:
        lead = leads.get(item.category)
        if lead is None or not item.active:
            continue
        target = target_date(plan, item.function_id)
        ideal = target - timedelta(days=lead.lead_days)
        name = names.get(item.function_id or "")
        title = f"{lead.task}: {name}" if name else lead.task
        tasks.append(
            Task(
                id=id_factory(),
                title=title[:MAX_TITLE],
                function_id=item.function_id,
                category=item.category,
                due_date=min(max(ideal, today), target),
                lead_days=lead.lead_days,
                status="done" if item.locked else "todo",
            )
        )
    return sorted(tasks, key=lambda t: (t.due_date, t.title))


def assess_tasks(plan: Plan, today: date) -> list[TaskAssessment]:
    """Late and at-risk flags for every task, as of `today`."""
    assessments: list[TaskAssessment] = []
    for task in plan.tasks:
        days_until_due = (task.due_date - today).days
        if task.status == "done":
            assessments.append(
                TaskAssessment(
                    task_id=task.id, late=False, at_risk=False, days_until_due=days_until_due
                )
            )
            continue
        ready_by = max(today, task.due_date) + timedelta(days=task.lead_days)
        at_risk = ready_by > target_date(plan, task.function_id)
        assessments.append(
            TaskAssessment(
                task_id=task.id,
                late=task.due_date < today,
                at_risk=at_risk,
                days_until_due=days_until_due,
                ready_by=ready_by if at_risk else None,
            )
        )
    return assessments


def flagged_task_ids(plan: Plan, today: date) -> set[str]:
    """Ids of tasks that are late or at risk as of `today`."""
    return {a.task_id for a in assess_tasks(plan, today) if a.late or a.at_risk}
