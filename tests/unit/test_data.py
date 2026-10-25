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


def test_city_multiplier_lookup() -> None:
    ref = load_reference_data()

    assert ref.city_multiplier("Mumbai") == 140
    assert ref.city_multiplier("  jodhpur ") == 80
    assert ref.city_multiplier("Somewhere new") == 100


def test_category_lookup() -> None:
    ref = load_reference_data()

    assert ref.category("catering").per_plate is True
    with pytest.raises(KeyError):
        ref.category("fireworks")


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


@pytest.mark.parametrize(
    ("name", "edit", "message"),
    [
        ("lead_times.json", _drop_lead_time, "without a lead time"),
        ("categories.json", _bad_weights, "sum to 100"),
        ("categories.json", _unknown_weight, "unknown categories"),
        ("function_templates.json", _no_birthday_template, "every event type"),
        ("categories.json", _missing_tier, "tier_multipliers"),
    ],
)
def test_inconsistent_data_rejected(
    tmp_path: Path, name: str, edit: Callable[[Any], None], message: str
) -> None:
    data_dir = _broken_copy(tmp_path, name, edit)

    with pytest.raises(ValidationError, match=message):
        load_reference_data(data_dir)
