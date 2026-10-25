"""Adapt engine: applies a reported change, measures its impact, and checks fixes.

Gemini may propose options, but every option passes through `verify_option` here before
the user sees it: ops are applied to a copy, every invariant is re-checked, locked lines
must be untouched, and the problem must actually be solved.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from app.data.loader import CategoryInfo, LeadTime
from app.engines.budget import TierMultipliers, budget_status, what_if
from app.engines.timeline import flagged_task_ids, target_date
from app.models.budget import (
    SetCategory,
    SetFunctionGuests,
    SetGuests,
    SetTier,
    SetTotal,
    WhatIf,
)
from app.models.change import (
    BudgetCut,
    Change,
    ChangeTier,
    DateMoved,
    DropItem,
    FunctionDropped,
    GuestsChanged,
    Impact,
    Op,
    Option,
    OptionResult,
    ReduceGuests,
    ScaleCategory,
    VendorCancelled,
)
from app.models.common import Tier, new_id
from app.models.event import Event, Function, Idea, LineItem, Task
from app.models.plan import Plan

MAX_TITLE = 120
MAX_TRIM_PERCENT = 90
TRIM_CATEGORIES = 5
LOWER_TIER: dict[Tier, Tier] = {"premium": "standard", "standard": "budget"}


@dataclass(frozen=True)
class AdaptContext:
    """Reference data and clock the adapt engine needs. `today` is an IST date."""

    categories: Sequence[CategoryInfo]
    tier_multipliers: TierMultipliers
    lead_times: Sequence[LeadTime]
    today: date
    id_factory: Callable[[], str] = new_id


# Changes


def apply_change(plan: Plan, change: Change, ctx: AdaptContext) -> Plan:
    """The plan after the change, without any fix. Raises ValueError for unknown ids."""
    match change:
        case BudgetCut(new_total=new_total):
            return _raw_what_if(plan, ctx, SetTotal(total=new_total))
        case GuestsChanged(guests=guests):
            return _raw_what_if(plan, ctx, SetGuests(guests=guests))
        case VendorCancelled(line_item_id=line_item_id):
            return _cancel_vendor(plan, line_item_id, ctx)
        case DateMoved(new_start_date=new_start_date):
            return _move_dates(plan, new_start_date)
        case FunctionDropped(function_id=function_id):
            return _drop_function(plan, function_id)


def impact(before: Plan, after: Plan, today: date) -> Impact:
    """Money position after a change, tasks it pushed late or at risk, lines it touched."""
    committed, over_by, unallocated = budget_status(after)
    old = {i.id: i for i in before.line_items}
    new = {i.id: i for i in after.line_items}
    affected = [i for i in new if old.get(i) != new[i]] + [i for i in old if i not in new]
    newly = flagged_task_ids(after, today) - flagged_task_ids(before, today)
    return Impact(
        total_committed=committed,
        over_by=over_by,
        unallocated=unallocated,
        newly_flagged_task_ids=sorted(newly),
        affected_line_ids=affected,
    )


# Options


def apply_ops(plan: Plan, ops: Sequence[Op], ctx: AdaptContext) -> Plan:
    """Apply ops in order and return a new plan. Raises ValueError on any invalid op."""
    for op in ops:
        plan = _apply_op(plan, op, ctx)
    return plan


def verify_option(
    original: Plan, changed: Plan, option: Option, ctx: AdaptContext
) -> Option | None:
    """The option with engine figures attached if it is safe and solves the problem.

    Safe and solving means: every op applies, the plan still validates, locked lines are
    untouched, nothing is over budget, and no task becomes late or at risk that was not
    already. Otherwise None.
    """
    try:
        result = apply_ops(changed, option.ops, ctx)
    except ValueError:
        return None
    committed, over_by, _ = budget_status(result)
    if over_by or _locked(result) != _locked(changed):
        return None
    flagged_after = flagged_task_ids(result, ctx.today)
    if not flagged_after <= flagged_task_ids(changed, ctx.today):
        return None
    newly = len(flagged_after - flagged_task_ids(original, ctx.today))
    figures = OptionResult(total_committed=committed, over_by=0, newly_late_tasks=newly)
    return option.model_copy(update={"result": figures})


def rule_based_options(
    original: Plan, changed: Plan, change: Change, ctx: AdaptContext
) -> list[Option]:
    """Deterministic fixes, used when Gemini is unavailable or its options all fail.

    Only verified options are returned, so every one is safe to show.
    """
    candidates: list[tuple[str, list[Op]]] = []
    _, over_by, _ = budget_status(changed)
    if over_by:
        candidates.append(("Trim the largest open categories evenly", _trim_ops(changed)))
        candidates.append(
            ("Protect catering and trim the rest", _trim_ops(changed, exclude={"catering"}))
        )
        downgrade = _downgrade_op(changed, ctx)
        if downgrade is not None:
            after_tier = _try_ops(changed, [downgrade], ctx)
            if after_tier is not None:
                ops: list[Op] = [downgrade, *_trim_ops(after_tier, limit=TRIM_CATEGORIES - 1)]
                candidates.append(("Move the costliest function down a tier", ops))
    if isinstance(change, VendorCancelled):
        replacement = _replacement_line(original, changed)
        if replacement is not None:
            candidates.append(
                ("Skip this vendor and keep the money", [DropItem(line_item_id=replacement.id)])
            )
            simpler = _simpler_replacement_op(changed, replacement, ctx)
            if simpler is not None:
                candidates.append(("Book a simpler replacement", [simpler]))

    options: list[Option] = []
    for rationale, ops in candidates:
        if not ops:
            continue
        option = Option(id=ctx.id_factory(), rationale=rationale, ops=ops)
        verified = verify_option(original, changed, option, ctx)
        if verified is not None and verified.ops not in [o.ops for o in options]:
            options.append(verified)
    return options


# Change helpers


def _raw_what_if(plan: Plan, ctx: AdaptContext, *changes: WhatIf) -> Plan:
    """Apply budget changes without rebalancing, so only the changed lines move."""
    return what_if(plan, changes, ctx.categories, ctx.tier_multipliers, rebalance=False).plan


def _cancel_vendor(plan: Plan, line_item_id: str, ctx: AdaptContext) -> Plan:
    original = next((i for i in plan.line_items if i.id == line_item_id), None)
    if original is None or not original.active:
        raise ValueError(f"no active line item {line_item_id}")
    replacement = LineItem(
        id=ctx.id_factory(),
        function_id=original.function_id,
        category=original.category,
        planned=original.planned,
        payers=original.payers,
    )
    items = [_with_status(i, "cancelled") if i.id == line_item_id else i for i in plan.line_items]
    items.append(replacement)

    lead_days = next((lt.lead_days for lt in ctx.lead_times if lt.category == original.category), 0)
    target = target_date(plan, original.function_id)
    label = next((c.label for c in ctx.categories if c.key == original.category), "vendor")
    function_name = next((f.name for f in plan.functions if f.id == original.function_id), None)
    title = f"Find a replacement: {label}" + (f" for {function_name}" if function_name else "")
    task = Task(
        id=ctx.id_factory(),
        title=title[:MAX_TITLE],
        function_id=original.function_id,
        category=original.category,
        due_date=min(max(target - timedelta(days=lead_days), ctx.today), target),
        lead_days=lead_days,
    )
    return _rebuild(plan, line_items=items, tasks=[*plan.tasks, task])


def _move_dates(plan: Plan, new_start: date) -> Plan:
    shift = new_start - plan.event.start_date
    event = plan.event.model_copy(
        update={"start_date": new_start, "end_date": plan.event.end_date + shift}
    )
    functions = [f.model_copy(update={"start": f.start + shift}) for f in plan.functions]
    tasks = [t.model_copy(update={"due_date": t.due_date + shift}) for t in plan.tasks]
    return _rebuild(plan, event=event, functions=functions, tasks=tasks)


def _drop_function(plan: Plan, function_id: str) -> Plan:
    """Remove a function. Open lines go (money freed); locked lines stay as event-wide."""
    if all(f.id != function_id for f in plan.functions):
        raise ValueError(f"unknown function {function_id}")
    items: list[LineItem] = []
    for item in plan.line_items:
        if item.function_id != function_id:
            items.append(item)
        elif item.locked:
            items.append(item.model_copy(update={"function_id": None}))
    return _rebuild(
        plan,
        functions=[f for f in plan.functions if f.id != function_id],
        line_items=items,
        tasks=[t for t in plan.tasks if t.function_id != function_id],
        ideas=[i for i in plan.ideas if i.function_id != function_id],
    )


# Op helpers


def _apply_op(plan: Plan, op: Op, ctx: AdaptContext) -> Plan:
    match op:
        case ReduceGuests(function_id=function_id, guests=guests):
            current = _function(plan, function_id)
            if guests >= current.guests:
                raise ValueError("reduce_guests must lower the guest count")
            change = SetFunctionGuests(function_id=function_id, guests=guests)
            return _raw_what_if(plan, ctx, change)
        case ChangeTier(function_id=function_id, tier=tier):
            if _function(plan, function_id).tier == tier:
                raise ValueError("change_tier must change the tier")
            return _raw_what_if(plan, ctx, SetTier(function_id=function_id, tier=tier))
        case ScaleCategory(category=category, percent=percent):
            in_category = [i for i in plan.line_items if i.active and i.category == category]
            open_sum = sum(i.planned for i in in_category if not i.locked)
            if not any(not i.locked for i in in_category):
                raise ValueError(f"no adjustable line items in category {category}")
            locked_spend = sum(i.spend for i in in_category if i.locked)
            amount = locked_spend + open_sum * (100 + percent) // 100
            return _raw_what_if(plan, ctx, SetCategory(category=category, amount=amount))
        case DropItem(line_item_id=line_item_id):
            return _drop_item(plan, line_item_id)


def _drop_item(plan: Plan, line_item_id: str) -> Plan:
    """Cancel an open line and remove its pending task when no other line needs it."""
    target = next((i for i in plan.line_items if i.id == line_item_id), None)
    if target is None or not target.active:
        raise ValueError(f"no active line item {line_item_id}")
    if target.locked:
        raise ValueError("locked line items never change")
    items = [_with_status(i, "cancelled") if i.id == line_item_id else i for i in plan.line_items]
    key = (target.category, target.function_id)
    still_needed = any(i.active and (i.category, i.function_id) == key for i in items)
    tasks = [
        t
        for t in plan.tasks
        if still_needed or t.status == "done" or (t.category, t.function_id) != key
    ]
    return _rebuild(plan, line_items=items, tasks=tasks)


def _trim_ops(
    plan: Plan, exclude: frozenset[str] | set[str] = frozenset(), limit: int = TRIM_CATEGORIES
) -> list[Op]:
    """Scale the largest open categories by one shared percent that clears the overrun."""
    _, over_by, _ = budget_status(plan)
    if not over_by:
        return []
    open_by_category: dict[str, int] = {}
    for item in plan.line_items:
        if item.active and not item.locked and item.category not in exclude:
            open_by_category[item.category] = open_by_category.get(item.category, 0) + item.planned
    largest = sorted(open_by_category, key=lambda c: (-open_by_category[c], c))[:limit]
    pool = sum(open_by_category[c] for c in largest)
    if pool == 0:
        return []
    percent = -(-over_by * 100 // pool)  # ceiling
    if percent > MAX_TRIM_PERCENT:
        return []
    return [ScaleCategory(category=c, percent=-percent) for c in largest]


def _downgrade_op(plan: Plan, ctx: AdaptContext) -> ChangeTier | None:
    """Lower the tier of the function with the most open tier-sensitive spend."""
    sensitive = {c.key for c in ctx.categories if c.tier_sensitive}
    best: tuple[int, Function] | None = None
    for function in plan.functions:
        if function.tier not in LOWER_TIER:
            continue
        spend = sum(
            i.planned
            for i in plan.line_items
            if i.function_id == function.id
            and i.active
            and not i.locked
            and i.category in sensitive
        )
        if spend and (best is None or spend > best[0]):
            best = (spend, function)
    if best is None:
        return None
    function = best[1]
    return ChangeTier(function_id=function.id, tier=LOWER_TIER[function.tier])


def _simpler_replacement_op(
    plan: Plan, replacement: LineItem, ctx: AdaptContext
) -> ChangeTier | None:
    if replacement.function_id is None:
        return None
    category = next((c for c in ctx.categories if c.key == replacement.category), None)
    function = _function(plan, replacement.function_id)
    if category is None or not category.tier_sensitive or function.tier not in LOWER_TIER:
        return None
    return ChangeTier(function_id=function.id, tier=LOWER_TIER[function.tier])


def _replacement_line(original: Plan, changed: Plan) -> LineItem | None:
    known = {i.id for i in original.line_items}
    return next((i for i in changed.line_items if i.id not in known), None)


def _try_ops(plan: Plan, ops: Sequence[Op], ctx: AdaptContext) -> Plan | None:
    try:
        return apply_ops(plan, ops, ctx)
    except ValueError:
        return None


# Plan helpers


def _function(plan: Plan, function_id: str) -> Function:
    for function in plan.functions:
        if function.id == function_id:
            return function
    raise ValueError(f"unknown function {function_id}")


def _locked(plan: Plan) -> dict[str, LineItem]:
    return {i.id: i for i in plan.line_items if i.locked}


def _with_status(item: LineItem, status: str) -> LineItem:
    """Re-validate so the status rules (locking) apply."""
    return LineItem.model_validate({**item.model_dump(), "status": status})


def _rebuild(
    plan: Plan,
    *,
    event: Event | None = None,
    functions: list[Function] | None = None,
    line_items: list[LineItem] | None = None,
    tasks: list[Task] | None = None,
    ideas: list[Idea] | None = None,
) -> Plan:
    """A new Plan with some sections replaced. Construction re-runs every Plan check."""
    return Plan(
        event=event if event is not None else plan.event,
        functions=functions if functions is not None else plan.functions,
        line_items=line_items if line_items is not None else plan.line_items,
        tasks=tasks if tasks is not None else plan.tasks,
        people=plan.people,
        ideas=ideas if ideas is not None else plan.ideas,
        sources=plan.sources,
    )
