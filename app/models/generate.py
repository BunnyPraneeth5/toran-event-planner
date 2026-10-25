"""Generate: a complete brief in, a full plan out."""

from datetime import date

from pydantic import Field

from app.models.common import Budget, DomainModel, EventType, Guests, Name, Note, Source
from app.models.plan import Plan


class CompleteBrief(DomainModel):
    """A brief with every required field filled, as confirmed by the user."""

    event_type: EventType
    title: Name | None = None
    city: Name
    start_date: date
    guests: Guests
    total_budget: Budget
    style_notes: Note = ""


class GenerateRequest(DomainModel):
    brief: CompleteBrief
    brief_source: Source = "ai"


class GenerateResult(DomainModel):
    plan: Plan
    notices: list[str] = Field(default_factory=list, max_length=50)
    banner: str | None = None
