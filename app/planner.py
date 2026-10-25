"""Use cases. The only module that calls both the AI layer and the engines.

Gemini proposes raw values; the engines convert and check them; nothing the model
returns reaches the user without passing through here.
"""

import calendar
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime
from typing import cast

from app.ai.client import BANNER_TEXT, AIError, AIErrorKind, GeminiClient
from app.ai.schemas import BriefDraft, PlanDraft
from app.ai.service import extract_brief, propose_plan
from app.data.loader import FunctionTemplate, ReferenceData
from app.engines.budget import allocate
from app.engines.parse import parse_amount, parse_date
from app.engines.sanitize import (
    FunctionDraft,
    FunctionProposal,
    clamp_guests,
    place_functions,
    sanitize_weights,
)
from app.engines.timeline import build_tasks
from app.models.common import IST, MAX_RUPEES, MIN_BUDGET, Tier, new_id
from app.models.event import Event, Function, Idea
from app.models.generate import CompleteBrief, GenerateRequest, GenerateResult
from app.models.intake import (
    MAX_QUESTIONS,
    REQUIRED_FIELDS,
    Brief,
    BriefField,
    IntakeRequest,
    IntakeResult,
    Question,
)
from app.models.plan import MAX_IDEAS, Plan, Sources

MAX_NAME = 120
MAX_NOTES = 500
MAX_QUESTION = 300

NOT_EVENT_MESSAGE = (
    "Toran plans weddings, birthdays and community events. Try something like: "
    "Sister's wedding in Jaipur, February 2027, about 400 guests, 25 lakh budget."
)
NO_AI_BANNER = BANNER_TEXT[AIErrorKind.UNAVAILABLE]

MAX_IDEA = 300
PRICE_PATTERN = re.compile(r"₹|\brs\.?\s*\d|\brupees?\b|\binr\b|\blakh|\bcrore", re.IGNORECASE)
EVENT_LABELS = {"wedding": "Wedding", "birthday": "Birthday", "community": "Community event"}

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


async def generate(
    request: GenerateRequest,
    ai: GeminiClient | None,
    *,
    model: str,
    ref: ReferenceData,
    today: date,
    id_factory: Callable[[], str] = new_id,
) -> GenerateResult:
    """A complete brief to a full plan.

    Gemini proposes functions, category weights and ideas; the engines turn them into
    dates, guest counts, rupee line items and a dated checklist. Without AI, or when the
    call fails, the matching template and default weights are used, with a banner.
    """
    brief = request.brief
    template = _pick_template(ref, brief)
    categories = ref.categories.categories
    defaults = ref.categories.default_weights[brief.event_type]

    draft: PlanDraft | None = None
    banner: str | None = None
    if ai is None:
        banner = NO_AI_BANNER
    else:
        try:
            draft = await propose_plan(
                ai, model=model, brief=brief, template=template, categories=categories
            )
        except AIError as exc:
            banner = exc.banner

    notices: list[str] = []
    if draft is not None:
        proposals = [
            FunctionProposal(
                name=f.name,
                day_offset=f.day_offset,
                start_time=f.start_time,
                duration_minutes=f.duration_minutes,
                guest_percent=f.guest_percent,
                tier=f.tier,
            )
            for f in draft.functions
        ]
        raw_weights: dict[str, float] = {}
        for w in draft.weights:
            raw_weights[w.category] = raw_weights.get(w.category, 0.0) + w.weight
        weights, weight_notices = sanitize_weights(
            raw_weights, {c.key for c in categories}, defaults
        )
        notices += weight_notices
    else:
        proposals = _template_proposals(template)
        weights = dict(defaults)

    drafts, function_notices = place_functions(proposals, brief.start_date, brief.guests)
    notices += function_notices
    if not drafts:
        notices.append(f"Used the {template.label} functions instead.")
        drafts, _ = place_functions(
            _template_proposals(template), brief.start_date, brief.guests
        )

    plan = _assemble_plan(
        request, drafts, weights, draft, ref, today, id_factory, notices, banner is not None
    )
    return GenerateResult(plan=plan, notices=notices, banner=banner)


def _assemble_plan(
    request: GenerateRequest,
    drafts: list[FunctionDraft],
    weights: dict[str, int],
    draft: PlanDraft | None,
    ref: ReferenceData,
    today: date,
    id_factory: Callable[[], str],
    notices: list[str],
    used_fallback: bool,
) -> Plan:
    brief = request.brief
    event = Event(
        id=id_factory(),
        type=brief.event_type,
        title=brief.title or f"{EVENT_LABELS[brief.event_type]} in {brief.city}",
        city=brief.city,
        start_date=brief.start_date,
        end_date=max(d.day for d in drafts),
        guests=brief.guests,
        total_budget=brief.total_budget,
        style_notes=brief.style_notes,
    )
    functions = [
        Function(
            id=id_factory(),
            name=d.name,
            start=datetime.combine(d.day, d.start_time, tzinfo=IST),
            duration_minutes=d.duration_minutes,
            guests=d.guests,
            tier=cast(Tier, d.tier),  # sanitize guarantees a valid tier
        )
        for d in drafts
    ]
    items = allocate(
        event,
        functions,
        weights,
        ref.categories.categories,
        ref.categories.tier_multipliers,
        id_factory=id_factory,
    )
    ideas = _ideas(draft, functions, id_factory, notices) if draft is not None else []
    sources = Sources(brief=request.brief_source, plan="fallback" if used_fallback else "ai")
    base = Plan(event=event, functions=functions, line_items=items, sources=sources)
    tasks = build_tasks(base, ref.lead_times.lead_times, today, id_factory=id_factory)
    return Plan(
        event=event,
        functions=functions,
        line_items=items,
        tasks=tasks,
        ideas=ideas,
        sources=sources,
    )


def _pick_template(ref: ReferenceData, brief: CompleteBrief) -> FunctionTemplate:
    """The template for the event type, preferring one whose label the user mentioned."""
    candidates = [t for t in ref.templates.templates if t.event_type == brief.event_type]
    text = f"{brief.title or ''} {brief.style_notes}".casefold()
    for template in candidates:
        if template.label.casefold().split()[0] in text:
            return template
    return candidates[0]


def _template_proposals(template: FunctionTemplate) -> list[FunctionProposal]:
    return [
        FunctionProposal(
            name=f.name,
            day_offset=f.day_offset,
            start_time=f.start_time.strftime("%H:%M"),
            duration_minutes=f.duration_minutes,
            guest_percent=f.guest_pct,
            tier=f.tier,
        )
        for f in template.functions
    ]


def _ideas(
    draft: PlanDraft,
    functions: Sequence[Function],
    id_factory: Callable[[], str],
    notices: list[str],
) -> list[Idea]:
    """Ideas linked to their function by name. Ideas that quote prices are dropped."""
    by_name = {f.name.casefold(): f.id for f in functions}
    ideas: list[Idea] = []
    seen: set[str] = set()
    for proposal in draft.ideas:
        text = _clean(proposal.text, MAX_IDEA)
        if text is None or text.casefold() in seen:
            continue
        if PRICE_PATTERN.search(text):
            notices.append("Removed an idea that quoted a price.")
            continue
        seen.add(text.casefold())
        function_id = by_name.get(" ".join(proposal.function_name.split()).casefold())
        ideas.append(
            Idea(
                id=id_factory(),
                function_id=function_id,
                text=text,
                cost_band=proposal.cost_band,
            )
        )
        if len(ideas) == MAX_IDEAS:
            break
    return ideas


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
