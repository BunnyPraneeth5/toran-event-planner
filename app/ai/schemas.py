"""Flat response models for Gemini structured output.

Kept apart from the domain models on purpose: no ids, no defaults, no limits Gemini
might ignore, and raw values only (a number and its unit, date parts). The planner
converts and checks these with the engines before anything else uses them.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BriefDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_event: bool = Field(
        description="True only if the message is about planning a wedding, birthday or "
        "community event."
    )
    reason: str = Field(description="One short sentence on what the message is about.")
    event_type: Literal["wedding", "birthday", "community"] | None
    title: str | None = Field(description="Short neutral title, such as Sister's wedding.")
    city: str | None = Field(description="City named by the user, as written.")
    guests: int | None = Field(description="Guest count as stated, or null.")
    budget_amount: float | None = Field(
        description="Budget number exactly as written, without converting units."
    )
    budget_unit: str | None = Field(
        description="Budget unit as written: rupees, thousand, lakh or crore."
    )
    year: int | None = Field(description="Year if stated, else null.")
    month: int | None = Field(description="Month 1 to 12 if stated, else null.")
    day: int | None = Field(description="Day of month if stated, else null.")
    style_notes: str | None = Field(description="Preferences mentioned, such as theme or food.")
    questions: list[str] = Field(description="At most 3 short follow-up questions.")


class FunctionDraftOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Function name, such as Haldi or Reception.")
    day_offset: int = Field(description="Days after the event start date, 0 to 6.")
    start_time: str = Field(description="24-hour start time, HH:MM.")
    duration_minutes: int = Field(description="Length in minutes.")
    guest_percent: int = Field(description="Share of the total guests attending, 1 to 100.")
    tier: Literal["budget", "standard", "premium"]


class CategoryWeightOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str = Field(description="A category key from the given list.")
    weight: float = Field(description="Relative share of the budget, as a percent.")


class IdeaOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    function_name: str = Field(description="Name of the function this idea is for.")
    text: str = Field(description="One short, practical idea. No prices.")
    cost_band: Literal["low", "mid", "high"]


class PlanDraft(BaseModel):
    """Structure only: functions, how to weight the budget, and ideas. No money."""

    model_config = ConfigDict(extra="ignore")

    functions: list[FunctionDraftOut]
    weights: list[CategoryWeightOut]
    ideas: list[IdeaOut]


class OpOut(BaseModel):
    """One step of a fix. Fill only the fields its `op` needs; leave the rest null."""

    model_config = ConfigDict(extra="ignore")

    op: Literal["reduce_guests", "change_tier", "scale_category", "drop_item"]
    function_id: str | None = Field(description="For reduce_guests and change_tier.")
    guests: int | None = Field(description="New, lower guest count for reduce_guests.")
    tier: Literal["budget", "standard", "premium"] | None = Field(
        description="New tier for change_tier."
    )
    category: str | None = Field(description="Category key for scale_category.")
    percent: int | None = Field(
        description="For scale_category: negative to trim, for example -15."
    )
    line_item_id: str | None = Field(description="For drop_item.")


class OptionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rationale: str = Field(description="One short sentence. No numbers or amounts.")
    ops: list[OpOut]


class OptionsDraft(BaseModel):
    """Two or three alternative fixes. The engines check each one."""

    model_config = ConfigDict(extra="ignore")

    options: list[OptionOut]
