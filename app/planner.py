"""Use cases. The only module that calls both the AI layer and the engines.

Gemini proposes raw values; the engines convert and check them; nothing the model
returns reaches the user without passing through here.
"""

import calendar
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import cast

from pydantic import TypeAdapter, ValidationError

from app.ai.client import BANNER_TEXT, AIError, AIErrorKind, GeminiClient
from app.ai.schemas import BriefDraft, OpOut, OptionsDraft, PlanDraft
from app.ai.service import extract_brief, propose_options, propose_plan
from app.data.loader import FunctionTemplate, ReferenceData, SampleFile
from app.engines.adapt import (
    AdaptContext,
    apply_change,
    apply_ops,
    complete_option,
    impact,
    rule_based_options,
    verify_option,
)
from app.engines.budget import allocate, budget_status, realism_warnings, what_if
from app.engines.ledger import (
    add_person,
    assign_payers,
    equal_shares,
    ledger_summary,
    remove_person,
    update_pledge,
)
from app.engines.lines import over_plan
from app.engines.lines import update_line as book_line
from app.engines.parse import parse_amount, parse_date
from app.engines.sanitize import (
    FunctionDraft,
    FunctionProposal,
    clamp_guests,
    place_functions,
    sanitize_weights,
)
from app.engines.timeline import assess_tasks, build_tasks
from app.models.adapt import MAX_OPTIONS, AdaptRequest, AdaptResult, ApplyRequest
from app.models.budget import BudgetWarning
from app.models.change import ChangeTier, DropItem, Op, Option, ReduceGuests, ScaleCategory
from app.models.common import IST, MAX_RUPEES, MIN_BUDGET, Tier, new_id
from app.models.event import Event, Function, Idea, LineItem, Person
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
from app.models.lines import LineRequest
from app.models.people import AddPerson, PeopleRequest, RemovePerson, SetPayers, UpdatePledge
from app.models.plan import MAX_IDEAS, Plan, Sources
from app.models.view import BudgetView, CategoryTotal, LineOverPlan, PlanView, WhatIfRequest

MAX_NAME = 120
MAX_NOTES = 500
MAX_QUESTION = 300

NOT_EVENT_MESSAGE = (
    "Toran plans weddings, birthdays and community events. Try something like: "
    "Sister's wedding in Jaipur, February 2027, about 400 guests, 25 lakh budget."
)
NO_AI_BANNER = BANNER_TEXT[AIErrorKind.UNAVAILABLE]
NO_WORKING_OPTIONS_BANNER = (
    "The AI's suggestions did not fix the problem safely, so these are rule-based options."
)
NOTHING_TO_FIX = "Nothing else needs to change: the plan still fits the budget and the timeline."
TOPPED_UP_NOTE = "The rest of the gap is trimmed evenly from the largest categories."
NO_SAFE_FIX = (
    "No safe fix was found without touching booked or paid items. "
    "Consider raising the budget or changing a booking."
)

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


def sample_plan(
    city: str,
    *,
    ref: ReferenceData,
    sample: SampleFile,
    today: date,
    id_factory: Callable[[], str] = new_id,
) -> Plan:
    """The one-click sample wedding for a city, built by the engines with no AI call.

    Raises ValueError for a city that is not on the sample list.
    """
    chosen = sample.city(city)
    if chosen is None:
        raise ValueError(f"choose one of the sample cities, not {city[:40]}")
    template = next(t for t in ref.templates.templates if t.key == sample.template)
    start = today + timedelta(days=sample.start_in_days)
    drafts, _ = place_functions(_template_proposals(template), start, sample.guests)
    event = Event(
        id=id_factory(),
        type=template.event_type,
        title=sample.title,
        city=chosen.name,
        start_date=start,
        end_date=max(d.day for d in drafts),
        guests=sample.guests,
        total_budget=sample.total_budget,
        style_notes="A made-up sample to show how Toran works.",
    )
    functions = [
        Function(
            id=id_factory(),
            name=d.name,
            start=datetime.combine(d.day, d.start_time, tzinfo=IST),
            duration_minutes=d.duration_minutes,
            guests=d.guests,
            tier=cast(Tier, d.tier),
        )
        for d in drafts
    ]
    by_name = {f.name: f.id for f in functions}
    booked = {(b.category, by_name.get(b.function)) for b in sample.booked}
    items = [
        LineItem.model_validate(
            {
                **item.model_dump(),
                "payers": [
                    {"person_id": person, "share_pct": pct}
                    for person, pct in sample.payers.get(item.category, [])
                ],
                "status": "booked" if (item.category, item.function_id) in booked else "planned",
            }
        )
        for item in allocate(
            event,
            functions,
            ref.categories.default_weights[template.event_type],
            ref.categories.categories,
            ref.categories.tier_multipliers,
            id_factory=id_factory,
        )
    ]
    people = [
        Person(id=p.id, name=p.name, side_or_role=p.side_or_role, pledge=p.pledge)
        for p in sample.people
    ]
    ideas = [
        Idea(
            id=id_factory(),
            function_id=by_name.get(i.function),
            text=i.text,
            cost_band=i.cost_band,
        )
        for i in sample.ideas
    ]
    sources = Sources(brief="sample", plan="sample", options="sample")
    base = Plan(event=event, functions=functions, line_items=items, people=people, sources=sources)
    tasks = build_tasks(base, ref.lead_times.lead_times, today, id_factory=id_factory)
    return Plan(
        event=event,
        functions=functions,
        line_items=items,
        tasks=tasks,
        people=people,
        ideas=ideas,
        sources=sources,
    )


def recompute(plan: Plan, *, ref: ReferenceData, today: date) -> PlanView:
    """Everything the dashboard shows, derived fresh from the plan. No AI involved."""
    return _view(plan, ref, today, extra_warnings=[])


def run_what_if(request: WhatIfRequest, *, ref: ReferenceData, today: date) -> PlanView:
    """Apply what-if changes with the budget engine and return the new view. No AI.

    Raises ValueError for changes that refer to unknown functions or categories.
    """
    result = what_if(
        request.plan,
        request.changes,
        ref.categories.categories,
        ref.categories.tier_multipliers,
    )
    return _view(result.plan, ref, today, extra_warnings=result.warnings)


def _view(
    plan: Plan, ref: ReferenceData, today: date, extra_warnings: Sequence[BudgetWarning]
) -> PlanView:
    committed, over_by, unallocated = budget_status(plan)
    labels = {c.key: c.label for c in ref.categories.categories}
    planned: dict[str, int] = {}
    locked: dict[str, int] = {}
    for item in plan.line_items:
        if not item.active:
            continue
        planned[item.category] = planned.get(item.category, 0) + item.planned
        if item.locked:
            locked[item.category] = locked.get(item.category, 0) + item.spend
    by_category = [
        CategoryTotal(
            category=key,
            label=labels.get(key, key.replace("_", " ").capitalize()),
            planned=amount,
            locked=locked.get(key, 0),
        )
        for key, amount in sorted(planned.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    warnings = [w for w in extra_warnings if w.kind != "over_budget"]
    if over_by:
        warnings.insert(0, BudgetWarning(kind="over_budget", amount=over_by))
    warnings += realism_warnings(
        plan, ref.categories.categories, ref.city_tier(plan.event.city)
    )
    return PlanView(
        plan=plan,
        budget=BudgetView(
            committed=committed,
            over_by=over_by,
            unallocated=unallocated,
            by_category=by_category,
            warnings=warnings,
            over_plan=[
                LineOverPlan(line_item_id=item.id, amount=over_plan(item))
                for item in plan.line_items
                if item.active and over_plan(item)
            ],
        ),
        tasks=assess_tasks(plan, today),
        ledger=ledger_summary(plan),
    )


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


async def adapt_options(
    request: AdaptRequest,
    ai: GeminiClient | None,
    *,
    model: str,
    ref: ReferenceData,
    today: date,
    id_factory: Callable[[], str] = new_id,
) -> AdaptResult:
    """Apply a reported change, measure it, and offer verified fixes.

    Gemini proposes options as ops; the adapt engine applies each to a copy and keeps only
    those that solve the problem without touching locked lines. If none survive, or the
    call fails, rule-based options are offered with a banner. Raises ValueError for a
    change that refers to unknown ids.
    """
    ctx = _adapt_context(ref, today, id_factory)
    plan, change = request.plan, request.change
    changed = apply_change(plan, change, ctx)
    measured = impact(plan, changed, today)
    if not measured.over_by and not measured.newly_flagged_task_ids:
        return AdaptResult(impact=measured, message=NOTHING_TO_FIX)

    notices: list[str] = []
    banner: str | None = None
    options: list[Option] = []
    if ai is None:
        banner = NO_AI_BANNER
    else:
        titles = {t.id: t.title for t in changed.tasks}
        try:
            draft = await propose_options(
                ai,
                model=model,
                plan=changed,
                change=change,
                impact=measured,
                flagged_titles=[titles[i] for i in measured.newly_flagged_task_ids],
            )
        except AIError as exc:
            banner = exc.banner
        else:
            options = _verified_ai_options(draft, plan, changed, ctx, notices)

    rule_based = rule_based_options(plan, changed, change, ctx)
    if options:
        extra = [r for r in rule_based if r.ops not in [o.ops for o in options]]
        options = (options + extra)[:MAX_OPTIONS]
        return AdaptResult(impact=measured, options=options, notices=notices)
    fallback = rule_based[:MAX_OPTIONS]
    return AdaptResult(
        impact=measured,
        options=fallback,
        source="fallback",
        banner=banner or NO_WORKING_OPTIONS_BANNER,
        message=None if fallback else NO_SAFE_FIX,
        notices=notices,
    )


def apply_option(request: ApplyRequest, *, ref: ReferenceData, today: date) -> Plan:
    """The plan after the change and the chosen option, recomputed on the server.

    The option is verified again from scratch, so a tampered or stale option is refused
    with a ValueError instead of being applied.
    """
    ctx = _adapt_context(ref, today, new_id)
    changed = apply_change(request.plan, request.change, ctx)
    if verify_option(request.plan, changed, request.option, ctx) is None:
        raise ValueError("this option no longer fixes the problem")
    return apply_ops(changed, request.option.ops, ctx)


def _adapt_context(
    ref: ReferenceData, today: date, id_factory: Callable[[], str]
) -> AdaptContext:
    return AdaptContext(
        categories=ref.categories.categories,
        tier_multipliers=ref.categories.tier_multipliers,
        lead_times=ref.lead_times.lead_times,
        today=today,
        id_factory=id_factory,
    )


def _verified_ai_options(
    draft: OptionsDraft, plan: Plan, changed: Plan, ctx: AdaptContext, notices: list[str]
) -> list[Option]:
    """Gemini's options that parse, apply cleanly and solve the problem, at most three."""
    labels = {c.key: c.label for c in ctx.categories}
    kept: list[Option] = []
    dropped = 0
    for proposal in draft.options:
        try:
            ops = [_OP_ADAPTER.validate_python(_op_fields(o)) for o in proposal.ops]
            rationale = _rationale(proposal.rationale, ops, changed, labels)
            option = Option(id=ctx.id_factory(), rationale=rationale, ops=ops)
        except ValidationError:
            dropped += 1
            continue
        verified = complete_option(plan, changed, option, ctx)
        if verified is None or verified.ops in [o.ops for o in kept]:
            dropped += 1
            continue
        if len(verified.ops) > len(option.ops):
            note = f"{verified.rationale.rstrip('.')}. {TOPPED_UP_NOTE}"[:MAX_QUESTION]
            verified = verified.model_copy(update={"rationale": note})
        kept.append(verified)
        if len(kept) == MAX_OPTIONS:
            break
    if dropped:
        notices.append(f"Left out {dropped} suggestion(s) that did not fix the problem safely.")
    return kept


def _op_fields(op: OpOut) -> dict[str, object]:
    """Only the fields each op kind takes, so stray values cannot sneak through."""
    wanted = {
        "reduce_guests": ("function_id", "guests"),
        "change_tier": ("function_id", "tier"),
        "scale_category": ("category", "percent"),
        "drop_item": ("line_item_id",),
    }[op.op]
    return {"op": op.op, **{name: getattr(op, name) for name in wanted}}


def _rationale(text: str, ops: Sequence[Op], plan: Plan, labels: dict[str, str]) -> str:
    """Gemini's sentence if it has no numbers, else a plain description of the ops."""
    cleaned = _clean(text, MAX_QUESTION)
    if cleaned and not any(ch.isdigit() for ch in cleaned):
        return cleaned
    names = {f.id: _no_digits(f.name) for f in plan.functions}
    items = {i.id: i for i in plan.line_items}
    parts: list[str] = []
    for op in ops:
        match op:
            case ReduceGuests(function_id=function_id):
                parts.append(f"fewer guests at {names.get(function_id) or 'a function'}")
            case ChangeTier(function_id=function_id, tier=tier):
                parts.append(f"a {tier} setup for {names.get(function_id) or 'a function'}")
            case ScaleCategory(category=category, percent=percent):
                label = labels.get(category, category.replace("_", " ")).lower()
                parts.append(f"trim {label}" if percent < 0 else f"spend more on {label}")
            case DropItem(line_item_id=line_item_id):
                item = items.get(line_item_id)
                label = labels.get(item.category, "one line").lower() if item else "one line"
                parts.append(f"skip {label}")
    sentence = " and ".join(parts) or "adjust the plan"
    return (sentence[0].upper() + sentence[1:] + ".")[:MAX_QUESTION]


def _no_digits(text: str) -> str:
    return " ".join(re.sub(r"\d", "", text).split())


_OP_ADAPTER: TypeAdapter[Op] = TypeAdapter(Op)


def change_people(
    request: PeopleRequest, *, id_factory: Callable[[], str] = new_id
) -> tuple[Plan, list[str]]:
    """Apply one people or payer change with the ledger engine. No AI involved.

    Returns the new plan and notices for the user. Raises ValueError for unknown ids,
    splits that do not add up to 100, or one person too many.
    """
    plan, change = request.plan, request.change
    if isinstance(change, AddPerson):
        person = Person(
            id=id_factory(),
            name=change.name,
            side_or_role=change.side_or_role,
            pledge=change.pledge,
        )
        return add_person(plan, person), []
    if isinstance(change, UpdatePledge):
        return update_pledge(plan, change.person_id, change.pledge), []
    if isinstance(change, RemovePerson):
        name = next((p.name for p in plan.people if p.id == change.person_id), "")
        changed, affected = remove_person(plan, change.person_id)
        notice = f"Removed {name}."
        if affected:
            lines = "line now has" if affected == 1 else "lines now have"
            notice += f" {affected} {lines} no payer."
        return changed, [notice]
    return assign_payers(plan, change.line_item_id, _payer_shares(plan, change)), []


def _payer_shares(plan: Plan, change: SetPayers) -> list[tuple[str, int]]:
    if change.mode == "none":
        return []
    if change.mode == "single":
        if change.person_id is None:
            raise ValueError("choose who pays for this line")
        return [(change.person_id, 100)]
    if change.mode == "everyone":
        if not plan.people:
            raise ValueError("add a person before splitting a line")
        return equal_shares([p.id for p in plan.people])
    shares = [(s.person_id, s.share_pct) for s in change.shares if s.share_pct]
    if not shares:
        raise ValueError("enter a percent for at least one person")
    return shares


def update_line(request: LineRequest) -> Plan:
    """Mark one line planned, booked or paid with the bookings engine. No AI involved."""
    change = request.change
    return book_line(request.plan, change.line_item_id, change.status, change.actual)
