"""Parse engine: turns the raw values Gemini extracts into rupees and dates.

Gemini returns pieces such as (25, "lakh") or (2027, 2, None). The arithmetic and the
date logic happen here, in tested code, never in the model.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

UNIT_MULTIPLIERS: dict[str, int] = {
    "": 1,
    "rupee": 1,
    "rupees": 1,
    "rs": 1,
    "inr": 1,
    "₹": 1,
    "thousand": 1_000,
    "k": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "l": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
}


@dataclass(frozen=True)
class DateResult:
    """A parsed date, or which part is still missing. Never a guess."""

    value: date | None
    missing: Literal["month", "day"] | None
    in_past: bool


def parse_amount(value: int | float | str, unit: str = "") -> int:
    """Whole rupees from a raw number and unit, e.g. (25, "lakh") is 2,500,000.

    Accepts Indian digit grouping ("25,00,000") and decimals ("2.5", "crore").
    Rounds half up to the nearest rupee.
    """
    multiplier = UNIT_MULTIPLIERS.get(unit.strip().lower().rstrip("."))
    if multiplier is None:
        raise ValueError(f"unknown amount unit: {unit[:20]!r}")
    if isinstance(value, bool):
        raise ValueError("amount must be a number")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError("amount must be a number") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("amount must be a non-negative number")
    return int((number * multiplier).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_date(year: int | None, month: int | None, day: int | None, today: date) -> DateResult:
    """A date from raw parts.

    A missing or impossible day is reported as missing so the user is asked, never
    guessed. A missing year means the next occurrence on or after `today`.
    """
    if month is None or not 1 <= month <= 12:
        return DateResult(value=None, missing="month", in_past=False)
    if day is None:
        past_month = year is not None and (year, month) < (today.year, today.month)
        return DateResult(value=None, missing="day", in_past=past_month)
    if year is None:
        this_year = _safe_date(today.year, month, day)
        year = today.year + 1 if this_year is not None and this_year < today else today.year
    value = _safe_date(year, month, day)
    if value is None:
        return DateResult(value=None, missing="day", in_past=False)
    return DateResult(value=value, missing=None, in_past=value < today)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
