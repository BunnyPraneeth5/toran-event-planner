"""Ledger engine: who pledged what, who is assigned which lines, who has paid, and the
edits that change people and payers.

Split lines are divided between payers by largest remainder, so every rupee of every
line lands with exactly one person.
"""

from collections.abc import Sequence

from app.engines.budget import split
from app.models.event import LineItem, Person, Task
from app.models.ledger import LedgerRow, LedgerSummary
from app.models.plan import MAX_PEOPLE, Plan


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


# Editing people and payers. Each function returns a new plan; the input is never changed.


def add_person(plan: Plan, person: Person) -> Plan:
    """Add a person or side. Raises ValueError for a duplicate id or past the people limit."""
    if any(p.id == person.id for p in plan.people):
        raise ValueError(f"person {person.id} already exists")
    if len(plan.people) >= MAX_PEOPLE:
        raise ValueError(f"a plan can have at most {MAX_PEOPLE} people")
    return _rebuild(plan, people=[*plan.people, person])


def update_pledge(plan: Plan, person_id: str, pledge: int) -> Plan:
    """Change one person's pledge. Raises ValueError for an unknown person."""
    _person(plan, person_id)
    people = [
        Person.model_validate({**p.model_dump(), "pledge": pledge}) if p.id == person_id else p
        for p in plan.people
    ]
    return _rebuild(plan, people=people)


def remove_person(plan: Plan, person_id: str) -> tuple[Plan, int]:
    """Remove a person, their payer shares and their task ownership.

    Returns the new plan and how many lines lost their payer. A line the person shared with
    others is left unassigned rather than guessed, so the user decides how to split it again.
    """
    _person(plan, person_id)
    affected = 0
    items: list[LineItem] = []
    for item in plan.line_items:
        if any(p.person_id == person_id for p in item.payers):
            affected += 1
            items.append(LineItem.model_validate({**item.model_dump(), "payers": []}))
        else:
            items.append(item)
    tasks = [
        t.model_copy(update={"owner_id": None}) if t.owner_id == person_id else t
        for t in plan.tasks
    ]
    people = [p for p in plan.people if p.id != person_id]
    return _rebuild(plan, people=people, line_items=items, tasks=tasks), affected


def assign_payers(plan: Plan, line_item_id: str, shares: Sequence[tuple[str, int]]) -> Plan:
    """Set who pays for one line: no one, one person at 100, or a split summing to 100.

    Raises ValueError for an unknown line or person, or shares that do not add up to 100.
    """
    if not any(i.id == line_item_id for i in plan.line_items):
        raise ValueError(f"unknown line item {line_item_id}")
    for person_id, _ in shares:
        _person(plan, person_id)
    if len({person_id for person_id, _ in shares}) != len(shares):
        raise ValueError("a person appears twice in the split")
    if shares and sum(pct for _, pct in shares) != 100:
        raise ValueError("payer shares must add up to 100")
    payers = [{"person_id": person_id, "share_pct": pct} for person_id, pct in shares]
    items = [
        LineItem.model_validate({**i.model_dump(), "payers": payers})
        if i.id == line_item_id
        else i
        for i in plan.line_items
    ]
    return _rebuild(plan, line_items=items)


def equal_shares(person_ids: Sequence[str]) -> list[tuple[str, int]]:
    """Whole-number percents that add up to exactly 100 (largest remainder)."""
    if not person_ids:
        return []
    return list(zip(person_ids, split(100, [1] * len(person_ids)), strict=True))


def _person(plan: Plan, person_id: str) -> Person:
    for person in plan.people:
        if person.id == person_id:
            return person
    raise ValueError(f"unknown person {person_id}")


def _rebuild(
    plan: Plan,
    *,
    people: list[Person] | None = None,
    line_items: list[LineItem] | None = None,
    tasks: list[Task] | None = None,
) -> Plan:
    """A new Plan with some sections replaced. Construction re-runs every Plan check."""
    return Plan(
        event=plan.event,
        functions=plan.functions,
        line_items=line_items if line_items is not None else plan.line_items,
        tasks=tasks if tasks is not None else plan.tasks,
        people=people if people is not None else plan.people,
        ideas=plan.ideas,
        sources=plan.sources,
    )
