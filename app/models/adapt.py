"""Something changed: the request, the measured impact and the verified options."""

from pydantic import Field

from app.models.change import Change, Impact, Option
from app.models.common import DomainModel, Source
from app.models.plan import Plan

MAX_OPTIONS = 3


class AdaptRequest(DomainModel):
    plan: Plan
    change: Change


class AdaptResult(DomainModel):
    """`options` are already verified by the engines; their figures come from them too."""

    impact: Impact
    options: list[Option] = Field(default_factory=list, max_length=MAX_OPTIONS)
    source: Source = "ai"
    banner: str | None = None
    message: str | None = None
    notices: list[str] = Field(default_factory=list, max_length=20)


class ApplyRequest(DomainModel):
    """The original plan, the change and the chosen option. The server recomputes all of it."""

    plan: Plan
    change: Change
    option: Option
