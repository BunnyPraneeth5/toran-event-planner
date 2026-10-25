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
