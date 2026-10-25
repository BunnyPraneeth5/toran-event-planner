import json
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.data.loader import load_reference_data
from app.engines.sanitize import (
    FunctionDraft,
    FunctionProposal,
    clamp_guests,
    place_functions,
    sanitize_functions,
    sanitize_weights,
)

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "sanitize_cases.json").read_text(encoding="utf-8")
)
START = date.fromisoformat(CASES["event"]["start"])
END = date.fromisoformat(CASES["event"]["end"])

REF = load_reference_data()
KNOWN = {c.key for c in REF.categories.categories}
DEFAULTS = REF.categories.default_weights["wedding"]


def _draft(data: dict[str, Any]) -> FunctionDraft:
    return FunctionDraft(
        name=data["name"],
        day=date.fromisoformat(data["day"]),
        start_time=time.fromisoformat(data["start_time"]),
        duration_minutes=data["duration_minutes"],
        guests=data["guests"],
        tier=data.get("tier", "standard"),
    )


def _assert_notices(actual: list[str], expected: list[str]) -> None:
    for fragment in expected:
        assert any(fragment in notice for notice in actual), (fragment, actual)
    assert len(actual) == len(expected), actual


@pytest.mark.parametrize("case", CASES["weights"], ids=lambda c: c["name"])
def test_weights(case: dict[str, Any]) -> None:
    weights, notices = sanitize_weights(case["input"], KNOWN, DEFAULTS)

    expected = DEFAULTS if case["expected"] == "defaults" else case["expected"]
    assert weights == expected
    assert sum(weights.values()) == 100
    assert set(weights) <= KNOWN
    _assert_notices(notices, case["notices"])


@pytest.mark.parametrize("case", CASES["functions"], ids=lambda c: c["name"])
def test_functions(case: dict[str, Any]) -> None:
    kept, notices = sanitize_functions([_draft(d) for d in case["input"]], START, END)

    assert kept == [_draft(d) for d in case["expected"]]
    _assert_notices(notices, case["notices"])


def test_non_finite_weights_count_as_zero() -> None:
    weights, notices = sanitize_weights(
        {"venue": float("nan"), "decor": float("inf"), "catering": 1.0}, KNOWN, DEFAULTS
    )

    assert weights == {"catering": 100}
    assert len(notices) == 2


def test_known_must_include_other() -> None:
    with pytest.raises(ValueError, match="other"):
        sanitize_weights({"venue": 1}, {"venue"}, {"venue": 100})


def test_function_count_capped() -> None:
    drafts = [
        FunctionDraft(f"Function {i}", START, time(i % 24), 60, 50) for i in range(15)
    ]

    kept, notices = sanitize_functions(drafts, START, END)

    assert len(kept) == 12
    assert notices == ["Kept the first 12 functions."]


def test_clamp_guests() -> None:
    assert (clamp_guests(-3), clamp_guests(250), clamp_guests(10**6)) == (1, 250, 5000)


def test_place_functions_turns_offsets_and_shares_into_dates_and_guests() -> None:
    proposals = [
        FunctionProposal("Haldi", 0, "10:00", 150, 25, "budget"),
        FunctionProposal("Wedding", 2, "20:30", 300, 100, "premium"),
    ]

    kept, notices = place_functions(proposals, START, event_guests=401)

    assert [(d.day, d.start_time, d.guests) for d in kept] == [
        (START, time(10, 0), 100),
        (START + timedelta(days=2), time(20, 30), 401),
    ]
    assert notices == []


def test_place_functions_handles_bad_values() -> None:
    proposals = [
        FunctionProposal("Late", 7, "10:00", 60, 50),
        FunctionProposal("Early", -1, "10:00", 60, 50),
        FunctionProposal("Odd time", 0, "evening", 60, 0),
        FunctionProposal("Huge offset", 10**9, "10:00", 60, 50),
    ]

    kept, notices = place_functions(proposals, START, event_guests=200)

    assert [(d.name, d.start_time, d.guests) for d in kept] == [("Odd time", time(10, 0), 2)]
    assert "Set Odd time to start at 10:00." in notices
    assert sum("outside the event dates" in n for n in notices) == 3
