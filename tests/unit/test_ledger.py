import random
from typing import Any

import pytest

from app.engines.ledger import (
    add_person,
    assign_payers,
    equal_shares,
    ledger_summary,
    remove_person,
    update_pledge,
)
from app.models import LineItem, Person, Plan
from app.models.plan import MAX_PEOPLE
from tests.factories import make_plan

BRIDE = Person(id="bride_side", name="Bride's family", side_or_role="bride side", pledge=1_200_000)
GROOM = Person(id="groom_side", name="Groom's family", side_or_role="groom side", pledge=800_000)


def _item(item_id: str, planned: int, *shares: tuple[str, int], **extra: Any) -> LineItem:
    payers = [{"person_id": pid, "share_pct": pct} for pid, pct in shares]
    return LineItem.model_validate(
        {"id": item_id, "category": "other", "planned": planned, "payers": payers, **extra}
    )


def _plan(*items: LineItem) -> Plan:
    return make_plan(people=[BRIDE, GROOM], line_items=list(items), tasks=[])


def _row(summary: Any, person_id: str) -> Any:
    return next(r for r in summary.rows if r.person_id == person_id)


def test_single_payer_lines_assign_in_full() -> None:
    summary = ledger_summary(_plan(_item("a", 500_000, ("bride_side", 100))))

    bride = _row(summary, "bride_side")
    assert (bride.pledged, bride.assigned, bride.paid) == (1_200_000, 500_000, 0)
    assert bride.gap == 500_000 - 1_200_000


def test_split_lines_allocate_every_rupee() -> None:
    summary = ledger_summary(_plan(_item("a", 100_001, ("bride_side", 50), ("groom_side", 50))))

    assert _row(summary, "bride_side").assigned == 50_001
    assert _row(summary, "groom_side").assigned == 50_000
    assert summary.total_assigned == 100_001


def test_paid_follows_actual_shares() -> None:
    shares = (("bride_side", 60), ("groom_side", 40))
    item = _item("a", 400_000, *shares, status="paid", actual=450_000)

    summary = ledger_summary(_plan(item))

    assert _row(summary, "bride_side").paid == 270_000
    assert _row(summary, "groom_side").paid == 180_000
    assert summary.total_paid == 450_000


def test_unassigned_lines_reported() -> None:
    summary = ledger_summary(
        _plan(_item("a", 300_000, ("groom_side", 100)), _item("b", 200_000), _item("c", 50_000))
    )

    assert summary.unassigned == 250_000
    assert summary.total_planned == 550_000


def test_positive_gap_means_assigned_more_than_pledged() -> None:
    summary = ledger_summary(_plan(_item("a", 1_000_000, ("groom_side", 100))))

    assert _row(summary, "groom_side").gap == 200_000


def test_cancelled_lines_ignored() -> None:
    summary = ledger_summary(
        _plan(_item("a", 300_000, ("bride_side", 100), status="cancelled"), _item("b", 10_000))
    )

    assert _row(summary, "bride_side").assigned == 0
    assert summary.total_planned == 10_000


def test_people_without_lines_still_listed() -> None:
    summary = ledger_summary(_plan())

    assert [r.person_id for r in summary.rows] == ["bride_side", "groom_side"]
    assert summary.total_pledged == 2_000_000
    assert summary.unassigned == 0


def test_totals_balance_for_random_plans() -> None:
    rng = random.Random(11)
    for _ in range(100):
        items = []
        for index in range(rng.randint(1, 20)):
            planned = rng.randint(0, 5_000_000)
            choice = rng.randint(0, 3)
            if choice == 0:
                items.append(_item(f"i{index}", planned))
            elif choice == 1:
                items.append(_item(f"i{index}", planned, ("bride_side", 100)))
            else:
                bride_pct = rng.randint(1, 99)
                shares = (("bride_side", bride_pct), ("groom_side", 100 - bride_pct))
                items.append(_item(f"i{index}", planned, *shares))
        summary = ledger_summary(_plan(*items))

        assert summary.total_assigned + summary.unassigned == summary.total_planned
        assert summary.total_planned == sum(i.planned for i in items)


# editing people and payers


def _owned_plan() -> Plan:
    plan = make_plan(
        people=[BRIDE, GROOM],
        line_items=[
            _item("a", 300_000, ("bride_side", 100)),
            _item("b", 200_000, ("bride_side", 60), ("groom_side", 40)),
            _item("c", 100_000, ("groom_side", 100)),
        ],
    )
    assert plan.tasks[0].owner_id == "bride_side"
    return plan


def test_add_person_returns_new_plan() -> None:
    plan = _plan()
    aunt = Person(id="aunt", name="Aunt", pledge=50_000)

    changed = add_person(plan, aunt)

    assert [p.id for p in changed.people] == ["bride_side", "groom_side", "aunt"]
    assert len(plan.people) == 2


def test_add_person_refuses_duplicate_id_and_past_limit() -> None:
    with pytest.raises(ValueError, match="already exists"):
        add_person(_plan(), BRIDE)
    full = make_plan(
        people=[Person(id=f"p{i}", name=f"P{i}") for i in range(MAX_PEOPLE)], tasks=[]
    )
    with pytest.raises(ValueError, match="at most 50"):
        add_person(full, Person(id="extra", name="Extra"))


def test_update_pledge_changes_only_that_person() -> None:
    changed = update_pledge(_plan(), "groom_side", 900_000)

    assert [p.pledge for p in changed.people] == [1_200_000, 900_000]
    with pytest.raises(ValueError, match="unknown person"):
        update_pledge(_plan(), "nobody", 1)


def test_remove_person_clears_payers_and_task_owners() -> None:
    plan = _owned_plan()

    changed, affected = remove_person(plan, "bride_side")

    assert affected == 2
    assert [p.id for p in changed.people] == ["groom_side"]
    payers = {i.id: [(s.person_id, s.share_pct) for s in i.payers] for i in changed.line_items}
    assert payers == {"a": [], "b": [], "c": [("groom_side", 100)]}
    assert all(t.owner_id is None for t in changed.tasks)
    assert ledger_summary(changed).unassigned == 500_000


def test_assign_single_payer_and_split() -> None:
    plan = _plan(_item("a", 100_000))

    single = assign_payers(plan, "a", [("groom_side", 100)])
    split_plan = assign_payers(single, "a", [("bride_side", 70), ("groom_side", 30)])
    cleared = assign_payers(split_plan, "a", [])

    assert _row(ledger_summary(single), "groom_side").assigned == 100_000
    summary = ledger_summary(split_plan)
    assert (_row(summary, "bride_side").assigned, _row(summary, "groom_side").assigned) == (
        70_000,
        30_000,
    )
    assert ledger_summary(cleared).unassigned == 100_000


@pytest.mark.parametrize(
    ("line", "shares", "message"),
    [
        ("missing", [("bride_side", 100)], "unknown line item"),
        ("a", [("nobody", 100)], "unknown person"),
        ("a", [("bride_side", 60), ("groom_side", 30)], "add up to 100"),
        ("a", [("bride_side", 50), ("bride_side", 50)], "appears twice"),
    ],
)
def test_assign_payers_refuses_bad_input(
    line: str, shares: list[tuple[str, int]], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        assign_payers(_plan(_item("a", 100_000)), line, shares)


@pytest.mark.parametrize("count", [1, 2, 3, 6, 7, 50])
def test_equal_shares_add_to_exactly_100(count: int) -> None:
    shares = equal_shares([f"p{i}" for i in range(count)])

    assert sum(pct for _, pct in shares) == 100
    assert max(pct for _, pct in shares) - min(pct for _, pct in shares) <= 1


def test_split_equally_gives_exact_rupees() -> None:
    people = [Person(id=f"p{i}", name=f"P{i}") for i in range(3)]
    plan = make_plan(people=people, line_items=[_item("a", 100_000)], tasks=[])

    changed = assign_payers(plan, "a", equal_shares([p.id for p in people]))

    summary = ledger_summary(changed)
    assert sorted(r.assigned for r in summary.rows) == [33_000, 33_000, 34_000]
    assert summary.total_assigned == 100_000
