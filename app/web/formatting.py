"""Display formatting for rupees in the Indian system. Presentation only, no arithmetic
on the plan: the amounts were already computed by the engines."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

LAKH = 100_000
CRORE = 10_000_000


def format_inr(amount: int) -> str:
    """Indian digit grouping: 2500000 becomes ₹25,00,000."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{sign}₹{digits}"


def format_short(amount: int) -> str:
    """Compact form for headings: ₹25 lakh, ₹1.25 crore, or the full figure below a lakh."""
    if abs(amount) >= CRORE:
        return f"₹{_trim(Decimal(amount) / CRORE)} crore"
    if abs(amount) >= LAKH:
        return f"₹{_trim(Decimal(amount) / LAKH)} lakh"
    return format_inr(amount)


def _trim(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:f}".rstrip("0").rstrip(".")


def format_date(value: date) -> str:
    """8 Mar 2027 (no leading zero, same on every platform)."""
    return f"{value.day} {value:%b %Y}"


def format_datetime(value: datetime) -> str:
    """Mon 8 Mar, 19:00, in the time zone the value carries (IST for plan times)."""
    return f"{value:%a} {value.day} {value:%b}, {value:%H:%M}"


def format_time_range(start: datetime, end: datetime) -> str:
    """Sat 8 Mar, 19:00 to 23:00; the end gets its own day when it falls on the next one."""
    if end.date() == start.date():
        return f"{format_datetime(start)} to {end:%H:%M}"
    return f"{format_datetime(start)} to {format_datetime(end)}"
