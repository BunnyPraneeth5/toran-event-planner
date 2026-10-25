"""Intake: the free-text request and the brief that comes back from it."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.models.common import (
    Budget,
    DomainModel,
    EventType,
    Guests,
    Name,
    Note,
    ShortText,
    Source,
)

MAX_INTAKE_CHARS = 1000
MAX_QUESTIONS = 3

BriefField = Literal["event_type", "city", "start_date", "guests", "total_budget"]
REQUIRED_FIELDS: tuple[BriefField, ...] = (
    "event_type",
    "city",
    "start_date",
    "guests",
    "total_budget",
)


class Answer(DomainModel):
    question: ShortText
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class IntakeRequest(DomainModel):
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=MAX_INTAKE_CHARS)
    ]
    answers: list[Answer] = Field(default_factory=list, max_length=6)


class Brief(DomainModel):
    """What is known about the event so far. Any field may still be missing."""

    event_type: EventType | None = None
    title: Name | None = None
    city: Name | None = None
    start_date: date | None = None
    guests: Guests | None = None
    total_budget: Budget | None = None
    style_notes: Note = ""

    @property
    def missing(self) -> list[BriefField]:
        return [f for f in REQUIRED_FIELDS if getattr(self, f) is None]


class Question(DomainModel):
    """A question shown as a form field. `field` says which brief field it fills."""

    field: BriefField | Literal["other"]
    text: ShortText


class IntakeResult(DomainModel):
    status: Literal["ready", "needs_answers", "not_event"]
    brief: Brief
    questions: list[Question] = Field(default_factory=list, max_length=MAX_QUESTIONS)
    missing: list[BriefField] = Field(default_factory=list)
    message: str | None = None
    notices: list[str] = Field(default_factory=list, max_length=20)
    source: Source = "ai"
    banner: str | None = None
