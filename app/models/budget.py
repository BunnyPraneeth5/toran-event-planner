"""Inputs and outputs of the budget engine."""

from typing import Annotated, Literal

from pydantic import Field

from app.models.common import Budget, CategoryKey, DomainModel, Guests, Id, Rupees, Tier
from app.models.plan import Plan


class SetTotal(DomainModel):
    change: Literal["set_total"] = "set_total"
    total: Budget


class SetGuests(DomainModel):
    """Event-wide guest count. Functions without a guest override scale with it."""

    change: Literal["set_guests"] = "set_guests"
    guests: Guests


class SetFunctionGuests(DomainModel):
    change: Literal["set_function_guests"] = "set_function_guests"
    function_id: Id
    guests: Guests


class SetTier(DomainModel):
    change: Literal["set_tier"] = "set_tier"
    function_id: Id
    tier: Tier


class SetCategory(DomainModel):
    """Target for a whole category, including any locked lines in it."""

    change: Literal["set_category"] = "set_category"
    category: CategoryKey
    amount: Rupees


WhatIf = Annotated[
    SetTotal | SetGuests | SetFunctionGuests | SetTier | SetCategory,
    Field(discriminator="change"),
]


class BudgetWarning(DomainModel):
    """`amount` is the overrun for over_budget and the shortfall for below_typical."""

    kind: Literal["over_budget", "below_typical"]
    amount: Rupees
    category: CategoryKey | None = None
    function_id: Id | None = None


class BudgetResult(DomainModel):
    plan: Plan
    over_by: Rupees
    unallocated: Rupees
    warnings: list[BudgetWarning] = Field(default_factory=list)
