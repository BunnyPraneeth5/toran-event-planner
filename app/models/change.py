"""What the user reports as changed, and the fixes proposed for it.

Gemini may propose Ops, but only from this fixed vocabulary, and never with rupee
amounts. The adapt engine applies and verifies every Op before the user sees it.
"""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.models.common import (
    Budget,
    CategoryKey,
    DomainModel,
    Guests,
    Id,
    Rupees,
    ShortText,
    Tier,
)


class BudgetCut(DomainModel):
    kind: Literal["budget_cut"] = "budget_cut"
    new_total: Budget


class VendorCancelled(DomainModel):
    kind: Literal["vendor_cancelled"] = "vendor_cancelled"
    line_item_id: Id


class GuestsChanged(DomainModel):
    kind: Literal["guests_changed"] = "guests_changed"
    guests: Guests


class DateMoved(DomainModel):
    kind: Literal["date_moved"] = "date_moved"
    new_start_date: date


class FunctionDropped(DomainModel):
    kind: Literal["function_dropped"] = "function_dropped"
    function_id: Id


Change = Annotated[
    BudgetCut | VendorCancelled | GuestsChanged | DateMoved | FunctionDropped,
    Field(discriminator="kind"),
]


class ReduceGuests(DomainModel):
    op: Literal["reduce_guests"] = "reduce_guests"
    function_id: Id
    guests: Guests


class ChangeTier(DomainModel):
    op: Literal["change_tier"] = "change_tier"
    function_id: Id
    tier: Tier


class ScaleCategory(DomainModel):
    op: Literal["scale_category"] = "scale_category"
    category: CategoryKey
    percent: int = Field(strict=True, ge=-90, le=100)

    @field_validator("percent")
    @classmethod
    def _not_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("percent must not be zero")
        return value


class DropItem(DomainModel):
    op: Literal["drop_item"] = "drop_item"
    line_item_id: Id


Op = Annotated[
    ReduceGuests | ChangeTier | ScaleCategory | DropItem,
    Field(discriminator="op"),
]


class OptionResult(DomainModel):
    """Figures computed by the engine after applying an option. Never from Gemini."""

    total_committed: Rupees
    over_by: Rupees
    newly_late_tasks: int = Field(strict=True, ge=0, le=500)


class Option(DomainModel):
    id: Id
    rationale: ShortText
    ops: list[Op] = Field(min_length=1, max_length=5)
    result: OptionResult | None = None

    @field_validator("rationale")
    @classmethod
    def _no_digits(cls, value: str) -> str:
        if any(ch.isdigit() for ch in value):
            raise ValueError("rationale must not contain numbers; figures come from the engines")
        return value
