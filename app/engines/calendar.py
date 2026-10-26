"""Calendar engine: the plan as an iCalendar (.ics) file.

Pure functions. The timestamp is passed in, UIDs come from the plan's own ids (so a re-import
updates events instead of duplicating them), and all user text is escaped per RFC 5545.
"""

from datetime import UTC, date, datetime, timedelta

from app.models.event import Function, Task
from app.models.plan import Plan

PRODID = "-//Toran//Event planner//EN"
UID_DOMAIN = "toran-event-planner"
MAX_LINE_OCTETS = 75


def escape_text(value: str) -> str:
    """Escape a TEXT value: backslash, semicolon, comma and newlines (RFC 5545 3.3.11)."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line at 75 octets without splitting a UTF-8 character (RFC 5545 3.1)."""
    parts: list[str] = []
    current = ""
    limit = MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            parts.append(current)
            current = char
            limit = MAX_LINE_OCTETS - 1  # continuation lines start with a space
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def plan_to_ics(plan: Plan, *, stamp: datetime) -> str:
    """One all-day event per task and one timed event per function, times in UTC."""
    dtstamp = _utc(stamp)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_text(plan.event.title)}",
    ]
    for function in sorted(plan.functions, key=lambda f: f.start):
        lines += _function_event(function, plan, dtstamp)
    for task in sorted(plan.tasks, key=lambda t: (t.due_date, t.id)):
        lines += _task_event(task, plan, dtstamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def _function_event(function: Function, plan: Plan, dtstamp: str) -> list[str]:
    return [
        "BEGIN:VEVENT",
        f"UID:function-{function.id}@{UID_DOMAIN}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{_utc(function.start)}",
        f"DTEND:{_utc(function.end)}",
        f"SUMMARY:{escape_text(function.name)}",
        f"LOCATION:{escape_text(plan.event.city)}",
        f"DESCRIPTION:{escape_text(f'{plan.event.title}: {function.guests} guests.')}",
        "END:VEVENT",
    ]


def _task_event(task: Task, plan: Plan, dtstamp: str) -> list[str]:
    return [
        "BEGIN:VEVENT",
        f"UID:task-{task.id}@{UID_DOMAIN}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;VALUE=DATE:{_ics_date(task.due_date)}",
        f"DTEND;VALUE=DATE:{_ics_date(task.due_date + timedelta(days=1))}",
        f"SUMMARY:{escape_text(task.title)}",
        f"DESCRIPTION:{escape_text(f'Task for {plan.event.title}.')}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _ics_date(value: date) -> str:
    return value.strftime("%Y%m%d")
