"""Use cases. The only module that calls both the AI layer and the engines.

Gemini proposes raw values; the engines convert and check them; nothing the model
returns reaches the user without passing through here.
"""

import calendar
from datetime import date

from app.ai.client import BANNER_TEXT, AIError, AIErrorKind, GeminiClient
from app.ai.schemas import BriefDraft
from app.ai.service import extract_brief
from app.engines.parse import parse_amount, parse_date
from app.engines.sanitize import clamp_guests
from app.models.common import MAX_RUPEES, MIN_BUDGET
from app.models.intake import (
    MAX_QUESTIONS,
    REQUIRED_FIELDS,
    Brief,
    BriefField,
    IntakeRequest,
    IntakeResult,
    Question,
)

MAX_NAME = 120
MAX_NOTES = 500
MAX_QUESTION = 300

NOT_EVENT_MESSAGE = (
    "Toran plans weddings, birthdays and community events. Try something like: "
    "Sister's wedding in Jaipur, February 2027, about 400 guests, 25 lakh budget."
)
NO_AI_BANNER = BANNER_TEXT[AIErrorKind.UNAVAILABLE]

FIELD_QUESTIONS: dict[BriefField, str] = {
    "event_type": "Is this a wedding, a birthday or a community event?",
    "city": "Which city is it in?",
    "start_date": "What date does it start?",
    "guests": "About how many guests?",
    "total_budget": "What is the total budget?",
}


async def intake(
    request: IntakeRequest, ai: GeminiClient | None, *, model: str, today: date
) -> IntakeResult:
    """Free text (plus any answers) to a brief, with questions for whatever is missing.

    Without AI, or when the call fails, the user gets an empty brief form and a banner.
    """
    if ai is None:
        return _fallback_intake(NO_AI_BANNER)
    try:
        draft = await extract_brief(ai, model=model, text=request.text, answers=request.answers)
    except AIError as exc:
        return _fallback_intake(exc.banner)
    if not draft.is_event:
        return IntakeResult(status="not_event", brief=Brief(), message=NOT_EVENT_MESSAGE)

    brief, notices, date_question = _brief_from_draft(draft, today)
    missing = brief.missing
    return IntakeResult(
        status="needs_answers" if missing else "ready",
        brief=brief,
        questions=_questions(missing, date_question, draft.questions),
        missing=missing,
        notices=notices,
    )


def _brief_from_draft(draft: BriefDraft, today: date) -> tuple[Brief, list[str], str | None]:
    """Convert raw values with the engines. A bad value becomes missing, never a guess."""
    notices: list[str] = []

    guests: int | None = None
    if draft.guests is not None and draft.guests > 0:
        guests = clamp_guests(draft.guests)
        if guests != draft.guests:
            notices.append(f"Guest count adjusted to {guests}.")

    budget: int | None = None
    if draft.budget_amount is not None:
        try:
            amount = parse_amount(draft.budget_amount, draft.budget_unit or "")
        except ValueError:
            notices.append("The budget could not be read. Please enter it.")
        else:
            if MIN_BUDGET <= amount <= MAX_RUPEES:
                budget = amount
            else:
                notices.append("The budget looks out of range. Please confirm it.")

    start_date, date_question = None, None
    parsed = parse_date(draft.year, draft.month, draft.day, today)
    if parsed.in_past:
        notices.append("That date has already passed.")
        date_question = "The date you gave has passed. What date did you mean?"
    elif parsed.value is not None:
        start_date = parsed.value
    elif parsed.missing == "day" and draft.month is not None:
        month = calendar.month_name[draft.month]
        when = f"{month} {draft.year}" if draft.year else month
        date_question = f"Which day in {when}?"

    brief = Brief(
        event_type=draft.event_type,
        title=_clean(draft.title, MAX_NAME),
        city=_clean(draft.city, MAX_NAME),
        start_date=start_date,
        guests=guests,
        total_budget=budget,
        style_notes=_clean(draft.style_notes, MAX_NOTES) or "",
    )
    return brief, notices, date_question


def _questions(
    missing: list[BriefField], date_question: str | None, extra: list[str]
) -> list[Question]:
    """Questions for missing fields first, then Gemini's own, at most MAX_QUESTIONS."""
    questions = [
        Question(field=field, text=FIELD_QUESTIONS[field])
        if field != "start_date" or date_question is None
        else Question(field=field, text=date_question)
        for field in missing
    ]
    seen = {q.text.casefold() for q in questions}
    for text in extra:
        cleaned = _clean(text, MAX_QUESTION)
        if cleaned and cleaned.casefold() not in seen:
            questions.append(Question(field="other", text=cleaned))
            seen.add(cleaned.casefold())
    return questions[:MAX_QUESTIONS]


def _fallback_intake(banner: str) -> IntakeResult:
    return IntakeResult(
        status="needs_answers",
        brief=Brief(),
        questions=[Question(field=f, text=FIELD_QUESTIONS[f]) for f in REQUIRED_FIELDS][
            :MAX_QUESTIONS
        ],
        missing=list(REQUIRED_FIELDS),
        source="fallback",
        banner=banner,
    )


def _clean(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    collapsed = " ".join(text.split())[:limit]
    return collapsed or None
