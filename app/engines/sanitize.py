"""Sanitize engine: makes schema-valid but nonsensical model output safe for the engines.

Every fix comes back as a plain-language notice, so nothing changes silently.
"""

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, time, timedelta

from app.engines.budget import split
from app.models.common import MAX_GUESTS
from app.models.plan import MAX_FUNCTIONS

TIERS = ("budget", "standard", "premium")
MIN_DURATION, MAX_DURATION = 15, 1440
MAX_NAME = 120
WEIGHT_RESOLUTION = 1_000_000
MAX_DAY_OFFSET = 6
DEFAULT_START = time(10, 0)


@dataclass(frozen=True)
class FunctionDraft:
    """A proposed function before ids are assigned. Values may be out of range."""

    name: str
    day: date
    start_time: time
    duration_minutes: int
    guests: int
    tier: str = "standard"


@dataclass(frozen=True)
class FunctionProposal:
    """A function as proposed by Gemini or a template: relative day and guest share."""

    name: str
    day_offset: int
    start_time: str
    duration_minutes: int
    guest_percent: int
    tier: str = "standard"


def clamp_guests(guests: int) -> int:
    return min(MAX_GUESTS, max(1, guests))


def place_functions(
    proposals: Sequence[FunctionProposal], start: date, event_guests: int
) -> tuple[list[FunctionDraft], list[str]]:
    """Turn day offsets into dates and guest shares into guest counts, then sanitize.

    Offsets outside 0 to MAX_DAY_OFFSET fall outside the event window and are dropped.
    An unreadable start time becomes 10:00, with a notice.
    """
    notices: list[str] = []
    drafts: list[FunctionDraft] = []
    for proposal in proposals:
        try:
            start_time = time.fromisoformat(proposal.start_time.strip())
        except ValueError:
            start_time = DEFAULT_START
            label = " ".join(proposal.name.split())[:40] or "a function"
            notices.append(f"Set {label} to start at 10:00.")
        percent = min(100, max(1, proposal.guest_percent))
        offset = min(366, max(-366, proposal.day_offset))
        drafts.append(
            FunctionDraft(
                name=proposal.name,
                day=start + timedelta(days=offset),
                start_time=start_time.replace(second=0, microsecond=0, tzinfo=None),
                duration_minutes=proposal.duration_minutes,
                guests=max(1, (event_guests * percent + 50) // 100),
                tier=proposal.tier,
            )
        )
    kept, more = sanitize_functions(drafts, start, start + timedelta(days=MAX_DAY_OFFSET))
    return kept, notices + more


def sanitize_weights(
    raw: Mapping[str, float], known: Collection[str], defaults: Mapping[str, int]
) -> tuple[dict[str, int], list[str]]:
    """Integer percents summing to 100, using only known categories.

    Negative or non-finite weights count as zero, unknown categories fold into "other",
    and if nothing positive is left the defaults are used.
    """
    if "other" not in known:
        raise ValueError("known categories must include 'other'")
    notices: list[str] = []
    merged: dict[str, float] = {}
    for key, weight in raw.items():
        label = key[:40]
        usable = weight if math.isfinite(weight) and weight > 0 else 0.0
        if usable == 0.0 and weight != 0:
            notices.append(f"Ignored an invalid weight for {label}.")
        target = key if key in known else "other"
        if target != key:
            notices.append(f"Moved unknown category {label} into other.")
        merged[target] = merged.get(target, 0.0) + usable

    total = sum(merged.values())
    if total <= 0:
        notices.append("Used the default category split.")
        return dict(defaults), notices
    keys = list(merged)
    scaled = [int(merged[k] / total * WEIGHT_RESOLUTION) for k in keys]
    percents = split(100, scaled)
    return {k: p for k, p in zip(keys, percents, strict=True) if p > 0}, notices


def sanitize_functions(
    drafts: Sequence[FunctionDraft], start: date, end: date
) -> tuple[list[FunctionDraft], list[str]]:
    """Functions that fit the event: inside its dates, sane values, unique names.

    Exact repeats (same name, day and time) are dropped; a reused name on another day
    or time is numbered ("Puja 2"). At most MAX_FUNCTIONS are kept.
    """
    kept: list[FunctionDraft] = []
    notices: list[str] = []
    seen_exact: set[tuple[str, date, time]] = set()
    name_counts: dict[str, int] = {}
    for draft in drafts:
        name = " ".join(draft.name.split())[:MAX_NAME]
        if not name:
            notices.append("Dropped a function with no name.")
            continue
        if not start <= draft.day <= end:
            notices.append(f"Dropped {name}: it falls outside the event dates.")
            continue
        exact = (name.casefold(), draft.day, draft.start_time)
        if exact in seen_exact:
            notices.append(f"Dropped a repeated {name}.")
            continue
        if len(kept) == MAX_FUNCTIONS:
            notices.append(f"Kept the first {MAX_FUNCTIONS} functions.")
            break
        seen_exact.add(exact)

        count = name_counts.get(name.casefold(), 0) + 1
        name_counts[name.casefold()] = count
        if count > 1:
            renamed = f"{name} {count}"[:MAX_NAME]
            notices.append(f"Renamed a second {name} to {renamed}.")
            name = renamed

        guests = clamp_guests(draft.guests)
        if guests != draft.guests:
            notices.append(f"Adjusted guests for {name} to {guests}.")
        duration = min(MAX_DURATION, max(MIN_DURATION, draft.duration_minutes))
        if duration != draft.duration_minutes:
            notices.append(f"Adjusted the length of {name} to {duration} minutes.")
        tier = draft.tier if draft.tier in TIERS else "standard"
        if tier != draft.tier:
            notices.append(f"Set {name} to the standard tier.")

        kept.append(
            replace(draft, name=name, guests=guests, duration_minutes=duration, tier=tier)
        )
    return kept, notices
