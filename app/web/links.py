"""Links to other services, built for display. No requests are made here."""

from datetime import timedelta
from urllib.parse import urlencode

from app.models.event import Task

GOOGLE_CALENDAR = "https://calendar.google.com/calendar/render"


def google_calendar_url(task: Task, event_title: str) -> str:
    """An "Add to Google Calendar" link for one task, as an all-day event on its due date."""
    end = task.due_date + timedelta(days=1)
    query = {
        "action": "TEMPLATE",
        "text": task.title,
        "dates": f"{task.due_date:%Y%m%d}/{end:%Y%m%d}",
        "details": f"Task from Toran for {event_title}.",
    }
    return f"{GOOGLE_CALENDAR}?{urlencode(query)}"


ICON_KEYS = frozenset(
    {
        "venue",
        "catering",
        "decor",
        "music_entertainment",
        "photo_video",
        "attire",
        "mehendi_makeup",
        "priest_rituals",
        "invitations_gifts",
        "travel_stay",
        "cake",
        "other",
    }
)
"""Budget categories with an icon in static/img/icons.svg; a test keeps this in step."""


def category_icon(category: str) -> str:
    """Link to a category's icon in the sprite, or the general one for an unknown category."""
    key = category if category in ICON_KEYS else "other"
    return f"/static/img/icons.svg#cat-{key}"
