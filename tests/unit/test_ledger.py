import random
from typing import Any

from app.engines.ledger import ledger_summary
from app.models import LineItem, Person, Plan
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
