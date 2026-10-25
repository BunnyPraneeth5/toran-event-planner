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


class CategoryInfo(DomainModel):
    key: CategoryKey
    label: Name
    scope: Literal["function", "event"]
    per_plate: bool = False
    tier_sensitive: bool = False
    per_guest_floor: Rupees | None = None


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
    tiers: dict[CityTier, int]
    cities: dict[str, CityTier]

    @model_validator(mode="after")
    def _all_tiers_priced(self) -> Self:
        if set(self.tiers) != {"metro", "tier2", "tier3"} or min(self.tiers.values()) <= 0:
            raise ValueError("tiers needs a positive multiplier for metro, tier2 and tier3")
        return self


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

    def city_multiplier(self, city: str) -> int:
        """Cost multiplier for a city, as percent of tier-2 costs."""
        tier = self.city_tiers.cities.get(city.strip().lower(), self.city_tiers.default_tier)
        return self.city_tiers.tiers[tier]


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
