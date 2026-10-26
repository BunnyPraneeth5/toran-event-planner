"""Shared field types, limits and the base class for domain models."""

from datetime import timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

IST = timezone(timedelta(hours=5, minutes=30), name="IST")
"""India Standard Time. A fixed offset with no daylight saving, so no tz database is needed."""

MAX_RUPEES = 1_000_000_000  # 100 crore
MIN_BUDGET = 1_000
MAX_GUESTS = 5_000

Id = Annotated[str, StringConstraints(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9_-]+$")]
Rupees = Annotated[int, Field(strict=True, ge=0, le=MAX_RUPEES)]
Budget = Annotated[int, Field(strict=True, ge=MIN_BUDGET, le=MAX_RUPEES)]
Guests = Annotated[int, Field(strict=True, ge=1, le=MAX_GUESTS)]
Percent = Annotated[int, Field(strict=True, ge=0, le=100)]
CategoryKey = Annotated[
    str, StringConstraints(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

EventType = Literal["wedding", "birthday", "community"]
Tier = Literal["budget", "standard", "premium"]
Language = Literal["en", "te", "hi"]
Source = Literal["ai", "fallback", "sample"]
"""Where a section came from: Gemini, rule-based fallback, or the one-click sample."""


def new_id() -> str:
    """Short random id. Assigned by the server, never by Gemini."""
    return uuid4().hex[:12]


class DomainModel(BaseModel):
    """Base for domain models: unknown fields are rejected and instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)
