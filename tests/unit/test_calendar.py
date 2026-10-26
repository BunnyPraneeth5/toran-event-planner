from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from app.engines.calendar import escape_text, fold, plan_to_ics
from app.models import Plan
from app.web.links import google_calendar_url
from tests.factories import make_allocated_plan

STAMP = datetime(2026, 10, 26, 6, 30, tzinfo=UTC)


def _events(ics: str) -> list[str]:
    return ics.split("BEGIN:VEVENT")[1:]


def _unfold(ics: str) -> str:
    return ics.replace("\r\n ", "")


def test_calendar_wraps_events_with_crlf_lines() -> None:
    ics = plan_to_ics(make_allocated_plan(), stamp=STAMP)

    header = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Toran//Event planner//EN\r\n"
    assert ics.startswith(header)
    assert ics.endswith("END:VCALENDAR\r\n")
    assert "\n" not in ics.replace("\r\n", "")
    assert "X-WR-CALNAME:Sister's wedding" in ics


def test_one_all_day_event_per_task_and_one_timed_event_per_function() -> None:
    plan = make_allocated_plan()

    events = _events(plan_to_ics(plan, stamp=STAMP))

    assert len(events) == len(plan.tasks) + len(plan.functions)
    all_day = [e for e in events if "DTSTART;VALUE=DATE:" in e]
    assert len(all_day) == len(plan.tasks)
    venue = next(e for e in all_day if "Book the venue: Haldi" in e)
    assert "DTSTART;VALUE=DATE:20260814" in venue
    assert "DTEND;VALUE=DATE:20260815" in venue


def test_function_times_are_utc_converted_from_ist() -> None:
    events = _events(plan_to_ics(make_allocated_plan(), stamp=STAMP))

    haldi = next(e for e in events if "SUMMARY:Haldi" in e)
    assert "DTSTART:20270210T043000Z" in haldi
    assert "DTEND:20270210T073000Z" in haldi
    assert "LOCATION:Jodhpur" in haldi


def test_uids_are_stable_and_unique() -> None:
    plan = make_allocated_plan()

    first = plan_to_ics(plan, stamp=STAMP)
    second = plan_to_ics(plan, stamp=datetime(2027, 1, 1, tzinfo=UTC))

    uids = [line for line in first.split("\r\n") if line.startswith("UID:")]
    assert len(uids) == len(set(uids))
    assert uids == [line for line in second.split("\r\n") if line.startswith("UID:")]
    assert "UID:task-t1@toran-event-planner" in uids
    assert "UID:function-haldi@toran-event-planner" in uids
    assert "DTSTAMP:20261026T063000Z" in first


def test_user_text_is_escaped() -> None:
    assert escape_text("a;b,c\\d\ne") == "a\\;b\\,c\\\\d\\ne"

    data = make_allocated_plan().model_dump(mode="json")
    data["event"]["title"] = "Asha, Ravi; party\nBEGIN:VEVENT"
    ics = plan_to_ics(Plan.model_validate(data), stamp=STAMP)

    assert "X-WR-CALNAME:Asha\\, Ravi\\; party\\nBEGIN:VEVENT" in _unfold(ics)
    plan = Plan.model_validate(data)
    event_lines = [line for line in _unfold(ics).split("\r\n") if line == "BEGIN:VEVENT"]
    assert len(event_lines) == len(plan.tasks) + len(plan.functions)


def test_long_lines_fold_at_75_octets_without_splitting_characters() -> None:
    line = "SUMMARY:" + "मेहंदी ₹ " * 30

    folded = fold(line)

    parts = folded.split("\r\n")
    assert all(len(part.encode("utf-8")) <= 75 for part in parts)
    assert all(part.startswith(" ") for part in parts[1:])
    assert folded.replace("\r\n ", "") == line


def test_google_calendar_link_is_an_all_day_event() -> None:
    task = make_allocated_plan().tasks[0]

    url = google_calendar_url(task, "Sister's wedding")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "calendar.google.com"
    assert query["action"] == ["TEMPLATE"]
    assert query["text"] == [task.title]
    assert query["dates"] == ["20260814/20260815"]
    assert query["details"] == ["Task from Toran for Sister's wedding."]
