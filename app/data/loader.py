"""Load and validate the reference JSON in app/data.

Files are read once and checked against each other at startup, so a bad edit fails
loudly instead of producing a wrong plan. Engines receive this data as arguments.
"""

import json
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from app.models.common import (
    CategoryKey,
    DomainModel,
    EventType,
    Name,
    Percent,
    Rupees,
    Tier,
)

DATA_DIR = Path(__file__).parent

CityTier = Literal["metro", "tier2", "tier3"]
EVENT_TYPES: tuple[EventType, ...] = ("wedding", "birthday", "community")
TIERS: tuple[Tier, ...] = ("budget", "standard", "premium")
CITY_TIERS: tuple[CityTier, ...] = ("metro", "tier2", "tier3")


class PriceRange(DomainModel):
    """Typical rupees per guest, from low to high."""

    low: Rupees
    high: Rupees

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.low > self.high:
            raise ValueError("price range low is above high")
        return self


class CategoryInfo(DomainModel):
    key: CategoryKey
    label: Name
    scope: Literal["function", "event"]
    per_plate: bool = False
    tier_sensitive: bool = False
    per_plate_ranges: dict[CityTier, dict[Tier, PriceRange]] | None = None

    @model_validator(mode="after")
    def _ranges_complete(self) -> Self:
        if self.per_plate_ranges is None:
            return self
        if not self.per_plate:
            raise ValueError(f"{self.key}: per_plate_ranges need per_plate to be true")
        if set(self.per_plate_ranges) != set(CITY_TIERS):
            raise ValueError(f"{self.key}: per_plate_ranges need metro, tier2 and tier3")
        for city_tier, by_tier in self.per_plate_ranges.items():
            if set(by_tier) != set(TIERS):
                raise ValueError(f"{self.key}: {city_tier} needs budget, standard and premium")
            lows = [by_tier[t].low for t in TIERS]
            if lows != sorted(lows):
                raise ValueError(f"{self.key}: {city_tier} ranges must rise from budget to premium")
        return self

    def price_range(self, city_tier: CityTier, tier: Tier) -> PriceRange | None:
        if self.per_plate_ranges is None:
            return None
        return self.per_plate_ranges[city_tier][tier]


class CategoriesFile(DomainModel):
    note: str
    categories: list[CategoryInfo] = Field(min_length=1)
    default_weights: dict[EventType, dict[CategoryKey, Percent]]
    tier_multipliers: dict[Tier, int]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        keys = [c.key for c in self.categories]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate category key")
        if "other" not in keys:
            raise ValueError("an 'other' category is required")
        for event_type in EVENT_TYPES:
            weights = self.default_weights.get(event_type)
            if weights is None:
                raise ValueError(f"missing default weights for {event_type}")
            unknown = set(weights) - set(keys)
            if unknown:
                raise ValueError(f"unknown categories in {event_type} weights: {sorted(unknown)}")
            if sum(weights.values()) != 100:
                raise ValueError(f"{event_type} weights must sum to 100")
        if set(self.tier_multipliers) != set(TIERS) or min(self.tier_multipliers.values()) <= 0:
            raise ValueError("tier_multipliers needs a positive value for every tier")
        return self


class LeadTime(DomainModel):
    category: CategoryKey
    lead_days: int = Field(strict=True, ge=0, le=730)
    task: Name


class LeadTimesFile(DomainModel):
    note: str
    lead_times: list[LeadTime] = Field(min_length=1)


class TemplateFunction(DomainModel):
    name: Name
    day_offset: int = Field(strict=True, ge=0, le=6)
    start_time: time
    duration_minutes: int = Field(strict=True, ge=15, le=1440)
    guest_pct: int = Field(strict=True, ge=1, le=100)
    tier: Tier = "standard"


class FunctionTemplate(DomainModel):
    key: CategoryKey
    event_type: EventType
    label: Name
    functions: list[TemplateFunction] = Field(min_length=1, max_length=12)


class TemplatesFile(DomainModel):
    note: str
    templates: list[FunctionTemplate] = Field(min_length=1)


class CityTiersFile(DomainModel):
    note: str
    default_tier: CityTier
    cities: dict[str, CityTier]


class ReferenceData(DomainModel):
    categories: CategoriesFile
    lead_times: LeadTimesFile
    templates: TemplatesFile
    city_tiers: CityTiersFile

    @model_validator(mode="after")
    def _cross_file_consistent(self) -> Self:
        category_keys = {c.key for c in self.categories.categories}
        lead_keys = [lt.category for lt in self.lead_times.lead_times]
        missing = category_keys - set(lead_keys)
        if missing:
            raise ValueError(f"categories without a lead time: {sorted(missing)}")
        unknown = set(lead_keys) - category_keys
        if unknown:
            raise ValueError(f"lead times for unknown categories: {sorted(unknown)}")
        template_keys = [t.key for t in self.templates.templates]
        if len(set(template_keys)) != len(template_keys):
            raise ValueError("duplicate template key")
        covered = {t.event_type for t in self.templates.templates}
        if covered != set(EVENT_TYPES):
            raise ValueError("every event type needs at least one function template")
        return self

    def category(self, key: str) -> CategoryInfo:
        for info in self.categories.categories:
            if info.key == key:
                return info
        raise KeyError(key)

    def city_tier(self, city: str) -> CityTier:
        """City type used to pick per-plate price ranges. Unknown cities get the default."""
        return self.city_tiers.cities.get(city.strip().lower(), self.city_tiers.default_tier)


def load_reference_data(data_dir: Path = DATA_DIR) -> ReferenceData:
    """Read and validate every reference file in `data_dir`."""

    def read(name: str) -> Any:
        return json.loads((data_dir / name).read_text(encoding="utf-8"))

    return ReferenceData(
        categories=CategoriesFile.model_validate(read("categories.json")),
        lead_times=LeadTimesFile.model_validate(read("lead_times.json")),
        templates=TemplatesFile.model_validate(read("function_templates.json")),
        city_tiers=CityTiersFile.model_validate(read("city_tiers.json")),
    )


@lru_cache(maxsize=1)
def get_reference_data() -> ReferenceData:
    """Reference data singleton, loaded once per process."""
    return load_reference_data()


class SampleCity(DomainModel):
    name: Name
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SampleIdea(DomainModel):
    function: Name
    text: Name
    cost_band: Literal["low", "mid", "high"]


class SampleBooking(DomainModel):
    category: CategoryKey
    function: Name


class SamplePerson(DomainModel):
    id: CategoryKey
    name: Name
    side_or_role: Name
    pledge: Rupees


class SampleFile(DomainModel):
    """Inputs for the one-click sample plan. The engines build the plan from these."""

    note: str
    title: Name
    template: CategoryKey
    guests: int = Field(strict=True, ge=1, le=5000)
    total_budget: Rupees
    start_in_days: int = Field(strict=True, ge=1, le=365)
    default_city: Name
    people: list[SamplePerson]
    payers: dict[CategoryKey, list[tuple[CategoryKey, int]]]
    booked: list[SampleBooking]
    ideas: list[SampleIdea]
    cities: list[SampleCity] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [c.name for c in self.cities]
        if self.default_city not in names:
            raise ValueError("default_city must be one of the sample cities")
        people = {p.id for p in self.people}
        for category, shares in self.payers.items():
            if sum(pct for _, pct in shares) != 100:
                raise ValueError(f"sample payer shares for {category} must sum to 100")
            if any(person not in people for person, _ in shares):
                raise ValueError(f"sample payers for {category} name an unknown person")
        return self

    def city(self, name: str) -> SampleCity | None:
        return next((c for c in self.cities if c.name.casefold() == name.strip().casefold()), None)


@lru_cache(maxsize=1)
def get_sample() -> SampleFile:
    """The sample plan inputs, loaded once per process."""
    return SampleFile.model_validate(
        json.loads((DATA_DIR / "sample_plan.json").read_text(encoding="utf-8"))
    )
