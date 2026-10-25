"""The event and what hangs off it: functions, line items, tasks, people and ideas."""

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from app.models.common import (
    IST,
    Budget,
    CategoryKey,
    DomainModel,
    EventType,
    Guests,
    Id,
    Language,
    Name,
    Note,
    Rupees,
    ShortText,
    Tier,
)

MAX_EVENT_DAYS = 30

LineItemStatus = Literal["planned", "booked", "paid", "cancelled"]
TaskStatus = Literal["todo", "doing", "done"]
CostBand = Literal["low", "mid", "high"]

LOCKING_STATUSES: frozenset[str] = frozenset({"booked", "paid"})


class Event(DomainModel):
    id: Id
    type: EventType
    title: Name
    city: Name
    start_date: date
    end_date: date
    guests: Guests
    total_budget: Budget
    language: Language = "en"
    style_notes: Note = ""

    @model_validator(mode="after")
    def _dates_in_order(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date is before start_date")
        if (self.end_date - self.start_date).days >= MAX_EVENT_DAYS:
            raise ValueError(f"an event can span at most {MAX_EVENT_DAYS} days")
        return self


class Function(DomainModel):
    """One ceremony or gathering within the event, such as haldi or reception."""

    id: Id
    name: Name
    start: AwareDatetime
    duration_minutes: int = Field(strict=True, ge=15, le=1440)
    guests: Guests
    guests_override: bool = False
    tier: Tier = "standard"

    @field_validator("start")
    @classmethod
    def _to_ist(cls, value: datetime) -> datetime:
        return value.astimezone(IST)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


class PayerShare(DomainModel):
    person_id: Id
    share_pct: int = Field(strict=True, ge=1, le=100)


class LineItem(DomainModel):
    """A budget line. `function_id` is None for event-wide costs such as attire."""

    id: Id
    function_id: Id | None = None
    category: CategoryKey
    planned: Rupees
    actual: Rupees | None = None
    payers: list[PayerShare] = Field(default_factory=list, max_length=10)
    status: LineItemStatus = "planned"
    locked: bool = False

    @model_validator(mode="before")
    @classmethod
    def _lock_follows_status(cls, data: Any) -> Any:
        """Booked or paid lines are always locked; cancelled lines never are."""
        if isinstance(data, dict):
            status = data.get("status")
            if status in LOCKING_STATUSES:
                return {**data, "locked": True}
            if status == "cancelled":
                return {**data, "locked": False}
        return data

    @model_validator(mode="after")
    def _payer_shares_valid(self) -> Self:
        if self.payers:
            if sum(p.share_pct for p in self.payers) != 100:
                raise ValueError("payer shares must sum to 100")
            person_ids = [p.person_id for p in self.payers]
            if len(set(person_ids)) != len(person_ids):
                raise ValueError("a person appears twice in payers")
        return self

    @property
    def active(self) -> bool:
        return self.status != "cancelled"

    @property
    def spend(self) -> int:
        """Money this line commits: the actual amount once known, otherwise the plan."""
        return self.actual if self.actual is not None else self.planned


class Task(DomainModel):
    """A dated to-do. Late and at-risk are computed per request, never stored."""

    id: Id
    title: Name
    function_id: Id | None = None
    category: CategoryKey
    due_date: date
    lead_days: int = Field(strict=True, ge=0, le=730)
    status: TaskStatus = "todo"
    owner_id: Id | None = None


class Person(DomainModel):
    """A family member or committee member. Can pay for lines and own tasks."""

    id: Id
    name: Name
    side_or_role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] = ""
    pledge: Rupees = 0


class Idea(DomainModel):
    id: Id
    function_id: Id | None = None
    text: ShortText
    cost_band: CostBand
