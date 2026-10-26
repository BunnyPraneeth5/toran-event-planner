import re
from html import unescape
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
from app.models import Plan
from tests.factories import make_allocated_plan
from tests.fakes import FakeModels, fake_client

HTMX = {"HX-Request": "true"}


@pytest.fixture
def app_and_models(settings: Settings) -> tuple[TestClient, FakeModels]:
    ai, models = fake_client()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: ai
    return TestClient(app), models


@pytest.fixture
def client(app_and_models: tuple[TestClient, FakeModels]) -> TestClient:
    return app_and_models[0]


def _plan() -> dict[str, Any]:
    plan: dict[str, Any] = make_allocated_plan().model_dump(mode="json")
    return plan


def _line(plan: dict[str, Any], category: str, function_id: str | None) -> dict[str, Any]:
    return next(
        i
        for i in plan["line_items"]
        if i["category"] == category and i["function_id"] == function_id
    )


def _task(plan: dict[str, Any], category: str, function_id: str | None) -> dict[str, Any]:
    return next(
        t for t in plan["tasks"] if t["category"] == category and t["function_id"] == function_id
    )


def _post(client: TestClient, plan: dict[str, Any], change: dict[str, Any], **headers: str) -> Any:
    return client.post("/api/lines", json={"plan": plan, "change": change}, headers=headers)


def _state(html: str) -> Plan:
    raw = re.search(r'data-plan="([^"]*)"', html).group(1)  # type: ignore[union-attr]
    return Plan.model_validate_json(unescape(raw))


def test_book_a_line(client: TestClient) -> None:
    plan = _plan()
    line = _line(plan, "catering", "reception")

    body = _post(client, plan, {"line_item_id": line["id"], "status": "booked"}).json()

    new_plan = body["view"]["plan"]
    booked = _line(new_plan, "catering", "reception")
    assert (booked["status"], booked["locked"]) == ("booked", True)
    assert _task(new_plan, "catering", "reception")["status"] == "done"
    catering = next(r for r in body["view"]["budget"]["by_category"] if r["category"] == "catering")
    assert catering["locked"] >= line["planned"]


def test_pay_with_actual_over_plan(client: TestClient) -> None:
    plan = _plan()
    line = _line(plan, "catering", "reception")
    change = {"line_item_id": line["id"], "status": "paid", "actual": line["planned"] + 20_000}

    body = _post(client, plan, change).json()

    budget = body["view"]["budget"]
    assert budget["over_plan"] == [{"line_item_id": line["id"], "amount": 20_000}]
    assert budget["committed"] == plan["event"]["total_budget"] + 20_000
    assert budget["over_by"] == 20_000


def test_unbook_reopens_task_and_unlocks(client: TestClient) -> None:
    plan = _plan()
    line = _line(plan, "catering", "reception")
    paid = _post(client, plan, {"line_item_id": line["id"], "status": "paid", "actual": 1}).json()

    body = _post(
        client, paid["view"]["plan"], {"line_item_id": line["id"], "status": "planned"}
    ).json()

    item = _line(body["view"]["plan"], "catering", "reception")
    assert (item["status"], item["locked"], item["actual"]) == ("planned", False, None)
    assert _task(body["view"]["plan"], "catering", "reception")["status"] == "todo"


def test_booked_line_stays_fixed_in_a_later_what_if(client: TestClient) -> None:
    plan = _plan()
    line = _line(plan, "catering", "reception")
    booked = _post(client, plan, {"line_item_id": line["id"], "status": "booked"}).json()

    response = client.post(
        "/api/budget/whatif",
        json={
            "plan": booked["view"]["plan"],
            "changes": [{"change": "set_total", "total": 1_500_000}],
        },
    )

    after = _line(response.json()["view"]["plan"], "catering", "reception")
    assert after["planned"] == line["planned"]


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"line_item_id": "missing", "status": "booked"}, 422),
        ({"line_item_id": "li1", "status": "booked", "actual": -5}, 422),
        ({"line_item_id": "li1", "status": "cancelled"}, 422),
        ({"line_item_id": "li1", "status": "booked", "locked": False}, 422),
    ],
)
def test_bad_changes_are_refused(client: TestClient, change: dict[str, Any], status: int) -> None:
    assert _post(client, _plan(), change).status_code == status


def test_unknown_line_has_clear_message(client: TestClient) -> None:
    response = _post(client, _plan(), {"line_item_id": "missing", "status": "booked"})

    assert response.json() == {"detail": "unknown line item missing"}


def test_cancelled_line_cannot_be_booked(client: TestClient) -> None:
    plan = _plan()
    plan["line_items"][0]["status"] = "cancelled"

    response = _post(client, plan, {"line_item_id": "li1", "status": "booked"})

    assert response.json() == {"detail": "this line was cancelled, so it cannot be booked"}


def test_bookings_make_no_ai_calls(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, models = app_and_models

    _post(client, _plan(), {"line_item_id": "li1", "status": "paid", "actual": 10})

    assert models.calls == []


def test_partial_shows_form_over_plan_text_and_state(client: TestClient) -> None:
    plan = _plan()
    line = _line(plan, "catering", "reception")
    change = {"line_item_id": line["id"], "status": "paid", "actual": line["planned"] + 20_000}

    html = _post(client, plan, change, **HTMX).text

    assert "Catering for Reception: ₹20,000 over the plan for this line." in html
    assert 'hx-post="/api/lines"' in html
    assert '<label for="booking-line">Budget line</label>' in html
    assert '<label for="booking-status">Status</label>' in html
    assert 'data-keep-focus="budget-heading"' in html
    assert ", paid at ₹" in html
    saved = next(i for i in _state(html).line_items if i.id == line["id"])
    assert saved.status == "paid"
