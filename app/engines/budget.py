"""Budget engine: turns weights into rupee line items and rebalances them on what-if.

All money is integer rupees and every split uses the largest remainder method, so
active line items add up to the exact total whenever the total can cover what is
locked. Locked lines (booked or paid) never move.
"""

from collections.abc import Callable, Mapping, Sequence

from app.data.loader import CategoryInfo, CityTier
from app.models.budget import (
    BudgetResult,
    BudgetWarning,
    SetCategory,
    SetFunctionGuests,
    SetGuests,
    SetTier,
    SetTotal,
    WhatIf,
)
from app.models.common import MAX_GUESTS, Tier, new_id
from app.models.event import Event, Function, LineItem
from app.models.plan import Plan

TierMultipliers = Mapping[Tier, int]


def split(total: int, weights: Sequence[int]) -> list[int]:
    """Split `total` into integer parts proportional to `weights`, summing exactly to `total`.

    Largest remainder method; ties go to the earlier index. All-zero weights split equally.
    """
    if total < 0:
        raise ValueError("total must not be negative")
    if any(w < 0 for w in weights):
        raise ValueError("weights must not be negative")
    if not weights:
        return []
    shares = list(weights) if sum(weights) > 0 else [1] * len(weights)
    denominator = sum(shares)
    parts = [total * share // denominator for share in shares]
    remainders = [total * share % denominator for share in shares]
    shortfall = total - sum(parts)
    for index in sorted(range(len(shares)), key=lambda i: (-remainders[i], i))[:shortfall]:
        parts[index] += 1
    return parts


def allocate(
    event: Event,
    functions: Sequence[Function],
    weights: Mapping[str, int],
    categories: Sequence[CategoryInfo],
    tier_multipliers: TierMultipliers,
    id_factory: Callable[[], str] = new_id,
) -> list[LineItem]:
    """Split the event budget into line items that sum exactly to `event.total_budget`.

    Category amounts follow `weights`. Function-scoped categories are then split across
    functions by guests (per-plate categories) and venue tier (tier-sensitive ones).
    """
    unknown = set(weights) - {c.key for c in categories}
    if unknown:
        raise ValueError(f"weights for unknown categories: {sorted(unknown)}")
    funded = [c for c in categories if weights.get(c.key, 0) > 0]
    if not funded:
        raise ValueError("at least one category needs a positive weight")

    items: list[LineItem] = []
    amounts = split(event.total_budget, [weights[c.key] for c in funded])
    for category, amount in zip(funded, amounts, strict=True):
        if category.scope == "function" and functions:
            function_weights = [_function_weight(category, f, tier_multipliers) for f in functions]
            shares = split(amount, function_weights)
            items.extend(
                LineItem(id=id_factory(), function_id=f.id, category=category.key, planned=share)
                for f, share in zip(functions, shares, strict=True)
            )
        else:
            items.append(LineItem(id=id_factory(), category=category.key, planned=amount))
    return items


def what_if(
    plan: Plan,
    changes: Sequence[WhatIf],
    categories: Sequence[CategoryInfo],
    tier_multipliers: TierMultipliers,
) -> BudgetResult:
    """Apply what-if changes, then rebalance the remaining lines to fit the total.

    Lines the user changed, directly or through guests and tier, keep their new amounts.
    Locked lines never move. Every other active line absorbs the difference in proportion
    to its current amount. If locked and changed lines alone exceed the total, nothing
    else moves and the overrun is reported.
    """
    draft = _Draft(plan, categories, tier_multipliers)
    for change in changes:
        draft.apply(change)
    return draft.finish()


def realism_warnings(
    plan: Plan, categories: Sequence[CategoryInfo], city_tier: CityTier
) -> list[BudgetWarning]:
    """Flag per-plate lines below the usual range, before anything is booked.

    The range comes from the category's per-plate prices for the city type and the
    function's tier (budget, standard or premium). Event-wide lines use standard.
    """
    info = {c.key: c for c in categories}
    functions = {f.id: f for f in plan.functions}
    warnings: list[BudgetWarning] = []
    for item in plan.line_items:
        category = info.get(item.category)
        if category is None or not item.active:
            continue
        function = functions.get(item.function_id or "")
        tier: Tier = function.tier if function else "standard"
        price = category.price_range(city_tier, tier)
        if price is None:
            continue
        guests = function.guests if function else plan.event.guests
        typical_low, typical_high = price.low * guests, price.high * guests
        if item.spend < typical_low:
            warnings.append(
                BudgetWarning(
                    kind="below_typical",
                    amount=typical_low - item.spend,
                    category=item.category,
                    function_id=item.function_id,
                    typical_low=typical_low,
                    typical_high=typical_high,
                )
            )
    return warnings


def _function_weight(
    category: CategoryInfo, function: Function, tier_multipliers: TierMultipliers
) -> int:
    guests = function.guests if category.per_plate else 1
    tier = tier_multipliers[function.tier] if category.tier_sensitive else 100
    return guests * tier


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half up, for non-negative numbers."""
    return (numerator + denominator // 2) // denominator


class _Draft:
    """Working copy of a plan while what-if changes are applied."""

    def __init__(
        self, plan: Plan, categories: Sequence[CategoryInfo], tier_multipliers: TierMultipliers
    ) -> None:
        self.plan = plan
        self.info = {c.key: c for c in categories}
        self.tiers = tier_multipliers
        self.total = plan.event.total_budget
        self.event_guests = plan.event.guests
        self.functions = {f.id: f for f in plan.functions}
        self.planned = {i.id: i.planned for i in plan.line_items}
        self.adjustable = [i for i in plan.line_items if i.active and not i.locked]
        self.pinned: set[str] = set()

    def apply(self, change: WhatIf) -> None:
        match change:
            case SetTotal(total=total):
                self.total = total
            case SetGuests(guests=guests):
                self._set_event_guests(guests)
            case SetFunctionGuests(function_id=function_id, guests=guests):
                self._set_function_guests(function_id, guests, override=True)
            case SetTier(function_id=function_id, tier=tier):
                self._set_tier(function_id, tier)
            case SetCategory(category=category, amount=amount):
                self._set_category(category, amount)

    def finish(self) -> BudgetResult:
        active = [i for i in self.plan.line_items if i.active]
        flexible = [i for i in active if not self._fixed(i)]
        remaining = self.total - sum(self._committed(i) for i in active if self._fixed(i))
        if flexible and remaining >= 0:
            shares = split(remaining, [self.planned[i.id] for i in flexible])
            for item, share in zip(flexible, shares, strict=True):
                self.planned[item.id] = share

        committed = sum(self._committed(i) for i in active)
        over_by = max(0, committed - self.total)
        warnings = [BudgetWarning(kind="over_budget", amount=over_by)] if over_by else []
        event = self.plan.event.model_copy(
            update={"total_budget": self.total, "guests": self.event_guests}
        )
        plan = Plan(
            event=event,
            functions=list(self.functions.values()),
            line_items=[self._updated(i) for i in self.plan.line_items],
            tasks=self.plan.tasks,
            people=self.plan.people,
            ideas=self.plan.ideas,
            sources=self.plan.sources,
        )
        return BudgetResult(
            plan=plan,
            over_by=over_by,
            unallocated=max(0, self.total - committed),
            warnings=warnings,
        )

    def _set_event_guests(self, guests: int) -> None:
        previous = self.event_guests
        self.event_guests = guests
        if guests != previous:
            self._scale(self._items(None, per_plate=True), guests, previous)
        for function in list(self.functions.values()):
            if not function.guests_override:
                scaled = _round_div(function.guests * guests, previous)
                self._set_function_guests(
                    function.id, min(MAX_GUESTS, max(1, scaled)), override=False
                )

    def _set_function_guests(self, function_id: str, guests: int, *, override: bool) -> None:
        function = self._function(function_id)
        if guests != function.guests:
            self._scale(self._items(function_id, per_plate=True), guests, function.guests)
        self.functions[function_id] = function.model_copy(
            update={"guests": guests, "guests_override": function.guests_override or override}
        )

    def _set_tier(self, function_id: str, tier: Tier) -> None:
        function = self._function(function_id)
        if tier == function.tier:
            return
        ids = self._items(function_id, tier_sensitive=True)
        self._scale(ids, self.tiers[tier], self.tiers[function.tier])
        self.functions[function_id] = function.model_copy(update={"tier": tier})

    def _set_category(self, category: str, amount: int) -> None:
        in_category = [i for i in self.plan.line_items if i.active and i.category == category]
        open_items = [i for i in in_category if not i.locked]
        if not open_items:
            raise ValueError(f"no adjustable line items in category {category}")
        target = max(0, amount - sum(i.spend for i in in_category if i.locked))
        shares = split(target, [self.planned[i.id] for i in open_items])
        for item, share in zip(open_items, shares, strict=True):
            self.planned[item.id] = share
            self.pinned.add(item.id)

    def _function(self, function_id: str) -> Function:
        if function_id not in self.functions:
            raise ValueError(f"unknown function {function_id}")
        return self.functions[function_id]

    def _items(
        self, function_id: str | None, *, per_plate: bool = False, tier_sensitive: bool = False
    ) -> list[str]:
        """Adjustable lines of one function (None: event-wide) matching the given flags."""
        ids: list[str] = []
        for item in self.adjustable:
            info = self.info.get(item.category)
            if item.function_id != function_id or info is None:
                continue
            if (per_plate and info.per_plate) or (tier_sensitive and info.tier_sensitive):
                ids.append(item.id)
        return ids

    def _scale(self, item_ids: Sequence[str], numerator: int, denominator: int) -> None:
        for item_id in item_ids:
            self.planned[item_id] = _round_div(self.planned[item_id] * numerator, denominator)
            self.pinned.add(item_id)

    def _fixed(self, item: LineItem) -> bool:
        return item.locked or item.id in self.pinned

    def _committed(self, item: LineItem) -> int:
        return item.spend if item.locked else self.planned[item.id]

    def _updated(self, item: LineItem) -> LineItem:
        if item.locked or not item.active or self.planned[item.id] == item.planned:
            return item
        return item.model_copy(update={"planned": self.planned[item.id]})
