"""Editing people and payers: one change per request, applied by the ledger engine."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.models.common import DomainModel, Id, Name, Percent, Rupees
from app.models.plan import MAX_PEOPLE, Plan

PayerMode = Literal["none", "single", "everyone", "custom"]


class AddPerson(DomainModel):
    action: Literal["add_person"]
    name: Name
    side_or_role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] = ""
    pledge: Rupees = 0


class UpdatePledge(DomainModel):
    action: Literal["update_pledge"]
    person_id: Id
    pledge: Rupees


class RemovePerson(DomainModel):
    action: Literal["remove_person"]
    person_id: Id


class ShareInput(DomainModel):
    """One person's percent in a custom split. Zero means not part of the split."""

    person_id: Id
    share_pct: Percent


class SetPayers(DomainModel):
    """Who pays for one line: no one, one person, everyone equally, or a custom split."""

    action: Literal["set_payers"]
    line_item_id: Id
    mode: PayerMode
    person_id: Id | None = None
    shares: list[ShareInput] = Field(default_factory=list, max_length=MAX_PEOPLE)


PeopleChange = Annotated[
    AddPerson | UpdatePledge | RemovePerson | SetPayers, Field(discriminator="action")
]


class PeopleRequest(DomainModel):
    plan: Plan
    change: PeopleChange
