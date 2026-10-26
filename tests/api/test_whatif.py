import json
import re
from html import unescape
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
from app.models import Plan
from app.web.formatting import format_inr
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


def _plan_with_booked_venue() -> dict[str, Any]:
    plan: dict[str, Any] = make_allocated_plan().model_dump(mode="json")
    for item in plan["line_items"]:
        if item["category"] == "venue" and item["function_id"] == "reception":
            item["status"] = "booked"
    return plan


def _state(html: str) -> Plan:
    raw = re.search(r'data-plan="([^"]*)"', html).group(1)  # type: ignore[union-attr]
    return Plan.model_validate_json(unescape(raw))


def _whatif(client: TestClient, plan: dict[str, Any], *changes: dict[str, Any]) -> Any:
    return client.post(
        "/api/budget/whatif", json={"plan": plan, "changes": list(changes)}, headers=HTMX
    )


def _slider(html: str, element_id: str) -> str:
    return re.search(rf'<(?:input|select) id="{element_id}"[^>]*>', html, re.S).group(0)  # type: ignore[union-attr]


def test_dashboard_has_whatif_controls(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models

    html = client.post(
        "/api/plan/recompute", json={"plan": _plan_with_booked_venue()}, headers=HTMX
    ).text

    total = _slider(html, "wi-total")
    assert 'hx-trigger="input changed delay:250ms"' in total
    assert 'hx-sync="this:replace"' in total
    assert 'aria-valuetext="₹25 lakh"' in total
    assert 'data-list-extra=\'{"change": "set_total"}\'' in total
    assert 'aria-valuetext="400 guests"' in _slider(html, "wi-guests")
    assert 'hx-trigger="change"' in _slider(html, "wi-tier-1")
    catering = _slider(html, "wi-cat-catering")
    assert 'aria-valuetext="₹7.5 lakh"' in catering
    assert '"category": "catering"' in catering
    assert "includes ₹3,13,043 booked" in html
    assert 'min="313043"' in _slider(html, "wi-cat-venue")


def test_fully_booked_category_has_no_slider(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models
    plan = _plan_with_booked_venue()
    for item in plan["line_items"]:
        if item["category"] == "attire":
            item["status"] = "paid"

    html = client.post("/api/plan/recompute", json={"plan": plan}, headers=HTMX).text

    assert 'id="wi-cat-attire"' not in html
    assert "Clothes and jewellery</strong>: ₹3,00,000, booked or paid, so it stays fixed." in html


def test_whatif_keeps_locked_lines_and_uses_no_ai(
    app_and_models: tuple[TestClient, FakeModels],
) -> None:
    client, models = app_and_models
    plan = _plan_with_booked_venue()

    change = {"change": "set_category", "category": "catering", "amount": 900_000}
    html = _whatif(client, plan, change).text

    after = _state(html)
    booked = next(i for i in after.line_items if i.locked)
    assert booked.planned == 313_043
    assert sum(i.planned for i in after.line_items if i.category == "catering") == 900_000
    assert sum(i.planned for i in after.line_items) == 2_500_000
    assert models.calls == []


def test_overrun_is_shown_as_text(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models

    html = _whatif(
        client, _plan_with_booked_venue(),
        {"change": "set_category", "category": "catering", "amount": 2_500_000},
    ).text

    after = _state(html)
    committed = sum(i.spend if i.locked else i.planned for i in after.line_items if i.active)
    over_by = committed - after.event.total_budget
    assert over_by > 0
    assert f'<strong class="over">Over by {format_inr(over_by)}.</strong>' in html


@pytest.mark.parametrize(
    "change",
    [
        {"change": "set_total", "total": 2_000_000},
        {"change": "set_guests", "guests": 500},
        {"change": "set_tier", "function_id": "reception", "tier": "standard"},
    ],
)
def test_each_slider_change_is_accepted(
    app_and_models: tuple[TestClient, FakeModels], change: dict[str, Any]
) -> None:
    client, models = app_and_models

    response = _whatif(client, _plan_with_booked_venue(), change)

    assert response.status_code == 200
    assert _state(response.text).line_items
    assert models.calls == []


def test_whatif_script_updates_readouts_and_keeps_focus(client: TestClient) -> None:
    script = client.get("/static/js/whatif.js").text

    assert 'setAttribute("aria-valuetext"' in script
    assert "data-keep-focus" in script
    assert "Plan updated." in script
    assert "fetch(" not in script


def test_whatif_extension_sends_only_the_moved_control(client: TestClient) -> None:
    script = client.get("/static/js/app.js").text

    assert 'whatif: ["plan", "changes"]' in script
    assert 'elt.matches("input, select, textarea") ? [elt]' in script
    assert json.dumps("data-list")[1:-1] in script.replace("dataset.list", "data-list")
