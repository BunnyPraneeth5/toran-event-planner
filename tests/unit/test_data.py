import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.data.loader import DATA_DIR, get_reference_data, load_reference_data

FILES = ("categories.json", "lead_times.json", "function_templates.json", "city_tiers.json")


def test_reference_data_consistent() -> None:
    ref = load_reference_data()

    keys = {c.key for c in ref.categories.categories}
    assert {lt.category for lt in ref.lead_times.lead_times} == keys
    for weights in ref.categories.default_weights.values():
        assert sum(weights.values()) == 100
        assert set(weights) <= keys
    assert {t.event_type for t in ref.templates.templates} == {"wedding", "birthday", "community"}


def test_every_file_says_rough_defaults() -> None:
    for name in FILES:
        note = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))["note"]
        assert note.startswith("Rough defaults")


def test_loader_is_cached() -> None:
    assert get_reference_data() is get_reference_data()


def test_city_tier_lookup() -> None:
    ref = load_reference_data()

    assert ref.city_tier("Mumbai") == "metro"
    assert ref.city_tier("  jodhpur ") == "tier3"
    assert ref.city_tier("Somewhere new") == "tier2"


def test_category_lookup() -> None:
    ref = load_reference_data()

    assert ref.category("catering").per_plate is True
    with pytest.raises(KeyError):
        ref.category("fireworks")


def test_catering_price_ranges() -> None:
    catering = load_reference_data().category("catering")

    standard = catering.price_range("tier3", "standard")
    assert standard is not None
    assert (standard.low, standard.high) == (500, 800)
    for city_tier in ("metro", "tier2", "tier3"):
        lows = [catering.price_range(city_tier, t).low for t in ("budget", "standard", "premium")]
        assert lows == sorted(lows)
    assert load_reference_data().category("venue").price_range("metro", "premium") is None


def _broken_copy(tmp_path: Path, name: str, edit: Callable[[Any], None]) -> Path:
    for file in FILES:
        shutil.copy(DATA_DIR / file, tmp_path / file)
    data = json.loads((tmp_path / name).read_text(encoding="utf-8"))
    edit(data)
    (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def _drop_lead_time(data: Any) -> None:
    data["lead_times"] = data["lead_times"][1:]


def _bad_weights(data: Any) -> None:
    data["default_weights"]["wedding"]["venue"] -= 1


def _unknown_weight(data: Any) -> None:
    data["default_weights"]["birthday"]["fireworks"] = 0


def _no_birthday_template(data: Any) -> None:
    data["templates"] = [t for t in data["templates"] if t["event_type"] != "birthday"]


def _missing_tier(data: Any) -> None:
    del data["tier_multipliers"]["premium"]


def _catering_ranges(data: Any) -> Any:
    return next(c for c in data["categories"] if c["key"] == "catering")["per_plate_ranges"]


def _range_low_above_high(data: Any) -> None:
    _catering_ranges(data)["tier2"]["budget"] = {"low": 900, "high": 400}


def _range_missing_city_type(data: Any) -> None:
    del _catering_ranges(data)["metro"]


def _range_missing_tier(data: Any) -> None:
    del _catering_ranges(data)["tier3"]["premium"]


def _range_not_rising(data: Any) -> None:
    _catering_ranges(data)["metro"]["premium"] = {"low": 100, "high": 5000}


def _ranges_on_non_per_plate(data: Any) -> None:
    venue = next(c for c in data["categories"] if c["key"] == "venue")
    venue["per_plate_ranges"] = _catering_ranges(data)


@pytest.mark.parametrize(
    ("name", "edit", "message"),
    [
        ("lead_times.json", _drop_lead_time, "without a lead time"),
        ("categories.json", _bad_weights, "sum to 100"),
        ("categories.json", _unknown_weight, "unknown categories"),
        ("function_templates.json", _no_birthday_template, "every event type"),
        ("categories.json", _missing_tier, "tier_multipliers"),
        ("categories.json", _range_low_above_high, "low is above high"),
        ("categories.json", _range_missing_city_type, "metro, tier2 and tier3"),
        ("categories.json", _range_missing_tier, "budget, standard and premium"),
        ("categories.json", _range_not_rising, "rise from budget to premium"),
        ("categories.json", _ranges_on_non_per_plate, "per_plate to be true"),
    ],
)
def test_inconsistent_data_rejected(
    tmp_path: Path, name: str, edit: Callable[[Any], None], message: str
) -> None:
    data_dir = _broken_copy(tmp_path, name, edit)

    with pytest.raises(ValidationError, match=message):
        load_reference_data(data_dir)
