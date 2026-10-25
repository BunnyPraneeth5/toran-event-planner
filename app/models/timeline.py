"""Outputs of the timeline engine."""

from datetime import date

from pydantic import Field

from app.models.common import DomainModel, Id


class TaskAssessment(DomainModel):
    """How a task stands as of a given day. Computed per request, never stored.

    `late` means the due date has passed. `at_risk` means the work can no longer be
    ready before its function; `ready_by` is then the earliest realistic date.
    """

    task_id: Id
    late: bool
    at_risk: bool
    days_until_due: int = Field(strict=True, ge=-10_000, le=10_000)
    ready_by: date | None = None
