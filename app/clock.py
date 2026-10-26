"""The one place that reads the wall clock. Everything else receives `today` as an argument."""

from datetime import UTC, date, datetime

from app.models.common import IST


def today_ist() -> date:
    """Today's date in India Standard Time, whatever timezone the server runs in."""
    return datetime.now(IST).date()


def now_utc() -> datetime:
    """The current moment in UTC, for timestamps such as an .ics file's DTSTAMP."""
    return datetime.now(UTC)
