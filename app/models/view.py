"""What the dashboard shows: the plan plus everything the engines derive from it."""

from pydantic import Field

from app.models.budget import BudgetWarning, WhatIf
from app.models.common import CategoryKey, DomainModel, Id, Rupees
from app.models.ledger import LedgerSummary
from app.models.plan import Plan
from app.models.timeline import TaskAssessment

MAX_WHAT_IFS = 20


class CategoryTotal(DomainModel):
    category: CategoryKey
    label: str
    planned: Rupees
    locked: Rupees


class LineOverPlan(DomainModel):
    """A booked or paid line whose actual cost is above its plan, and by how much."""

    line_item_id: Id
    amount: Rupees


class BudgetView(DomainModel):
    committed: Rupees
    booked: Rupees = 0
    """What booked or paid lines commit; part of `committed`."""
    over_by: Rupees
    unallocated: Rupees
    by_category: list[CategoryTotal]
    warnings: list[BudgetWarning] = Field(default_factory=list)
    over_plan: list[LineOverPlan] = Field(default_factory=list)


class PlanView(DomainModel):
    """Derived views are recomputed on every request; only `plan` is ever stored."""

    plan: Plan
    budget: BudgetView
    tasks: list[TaskAssessment]
    ledger: LedgerSummary
    days_to_go: int = Field(default=0, strict=True, ge=-100_000, le=100_000)


class PlanResponse(DomainModel):
    view: PlanView
    notices: list[str] = Field(default_factory=list, max_length=50)
    banner: str | None = None


class PlanRequest(DomainModel):
    plan: Plan


class WhatIfRequest(DomainModel):
    plan: Plan
    changes: list[WhatIf] = Field(min_length=1, max_length=MAX_WHAT_IFS)
