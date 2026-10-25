"""Outputs of the ledger engine."""

from pydantic import Field

from app.models.common import MAX_RUPEES, DomainModel, Id, Name, Rupees


class LedgerRow(DomainModel):
    """One person's position. `gap` is assigned minus pledged: positive means they
    have been assigned more than they pledged, negative means pledge not yet used."""

    person_id: Id
    name: Name
    pledged: Rupees
    assigned: Rupees
    paid: Rupees
    gap: int = Field(strict=True, ge=-MAX_RUPEES, le=MAX_RUPEES)


class LedgerSummary(DomainModel):
    rows: list[LedgerRow]
    total_planned: Rupees
    total_pledged: Rupees
    total_assigned: Rupees
    total_paid: Rupees
    unassigned: Rupees
