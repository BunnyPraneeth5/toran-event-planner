"""Ledger engine: who pledged what, who is assigned which lines, who has paid.

Split lines are divided between payers by largest remainder, so every rupee of every
line lands with exactly one person.
"""

from app.engines.budget import split
from app.models.ledger import LedgerRow, LedgerSummary
from app.models.plan import Plan


def ledger_summary(plan: Plan) -> LedgerSummary:
    """Pledged, assigned, paid and gap per person, plus the planned money nobody holds yet.

    Assigned comes from each payer's share of a line's planned amount; paid from their
    share of its actual amount, once known. Cancelled lines are ignored.
    """
    assigned = {p.id: 0 for p in plan.people}
    paid = {p.id: 0 for p in plan.people}
    unassigned = 0
    total_planned = 0
    for item in plan.line_items:
        if not item.active:
            continue
        total_planned += item.planned
        if not item.payers:
            unassigned += item.planned
            continue
        shares = [p.share_pct for p in item.payers]
        for payer, amount in zip(item.payers, split(item.planned, shares), strict=True):
            assigned[payer.person_id] += amount
        if item.actual is not None:
            for payer, amount in zip(item.payers, split(item.actual, shares), strict=True):
                paid[payer.person_id] += amount

    rows = [
        LedgerRow(
            person_id=person.id,
            name=person.name,
            pledged=person.pledge,
            assigned=assigned[person.id],
            paid=paid[person.id],
            gap=assigned[person.id] - person.pledge,
        )
        for person in plan.people
    ]
    return LedgerSummary(
        rows=rows,
        total_planned=total_planned,
        total_pledged=sum(r.pledged for r in rows),
        total_assigned=sum(r.assigned for r in rows),
        total_paid=sum(r.paid for r in rows),
        unassigned=unassigned,
    )
