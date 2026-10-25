"""The one place that reads the wall clock. Everything else receives `today` as an argument."""

from datetime import date, datetime

from app.models.common import IST


def today_ist() -> date:
    """Today's date in India Standard Time, whatever timezone the server runs in."""
    return datetime.now(IST).date()
