"""Daily cap on Gemini calls: a spending safety net for the public deployment.

Counts every request sent to Gemini (retries and fallbacks included, since each one is
billed) per IST day. The count lives in process memory, so it resets on restart; the
hard cap is the Cloud quota, and this guards against loops and abuse in between.
"""

import threading
from collections.abc import Callable
from datetime import date

from app.clock import today_ist


class DailyCallCounter:
    def __init__(self, limit: int, today: Callable[[], date] = today_ist) -> None:
        self._limit = limit
        self._today = today
        self._day: date | None = None
        self._used = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        """Count one call if today's limit allows it. A limit of 0 allows none."""
        with self._lock:
            day = self._today()
            if day != self._day:
                self._day, self._used = day, 0
            if self._used >= self._limit:
                return False
            self._used += 1
            return True

    @property
    def used_today(self) -> int:
        with self._lock:
            return self._used if self._day == self._today() else 0
