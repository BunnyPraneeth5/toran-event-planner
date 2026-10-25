from datetime import date

import pytest

from app.engines.parse import parse_amount, parse_date

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (25, "lakh", 2_500_000),
        ("25", "Lakhs", 2_500_000),
        (2.5, "crore", 25_000_000),
        ("1.25", "cr", 12_500_000),
        (80, "k", 80_000),
        (50, "thousand", 50_000),
        ("25,00,000", "", 2_500_000),
        (300000, "rupees", 300_000),
        ("12.5", "L.", 1_250_000),
        (0.000005, "lakh", 1),
        (0, "lakh", 0),
        (1500, "₹", 1500),
    ],
)
def test_parse_amount(value: int | float | str, unit: str, expected: int) -> None:
    assert parse_amount(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "unit", "message"),
    [
        (25, "bucks", "unknown amount unit"),
        ("lots", "lakh", "must be a number"),
        (-5, "lakh", "non-negative"),
        ("nan", "lakh", "non-negative"),
        (True, "lakh", "must be a number"),
    ],
)
def test_parse_amount_rejects_garbage(value: object, unit: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_amount(value, unit)  # type: ignore[arg-type]


def test_full_date() -> None:
    result = parse_date(2027, 2, 14, TODAY)

    assert result.value == date(2027, 2, 14)
    assert result.missing is None
    assert result.in_past is False


def test_missing_day_is_asked_not_guessed() -> None:
    result = parse_date(2027, 2, None, TODAY)

    assert result.value is None
    assert result.missing == "day"
    assert result.in_past is False


def test_missing_month() -> None:
    assert parse_date(2027, None, 14, TODAY).missing == "month"
    assert parse_date(2027, 13, 14, TODAY).missing == "month"


def test_impossible_day_is_asked() -> None:
    result = parse_date(2027, 2, 30, TODAY)

    assert result.value is None
    assert result.missing == "day"


def test_missing_year_means_next_occurrence() -> None:
    assert parse_date(None, 12, 5, TODAY).value == date(2026, 12, 5)
    assert parse_date(None, 2, 14, TODAY).value == date(2027, 2, 14)
    assert parse_date(None, 10, 25, TODAY).value == TODAY


def test_past_dates_flagged() -> None:
    assert parse_date(2025, 2, 14, TODAY).in_past is True
    assert parse_date(2026, 3, None, TODAY).in_past is True
    assert parse_date(2026, 10, None, TODAY).in_past is False
