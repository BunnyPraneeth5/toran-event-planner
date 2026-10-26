import json
import re
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.api.deps import get_today
from app.config import Settings, get_settings
from app.data.loader import DATA_DIR, get_reference_data, get_sample
from app.engines.budget import budget_status
from app.engines.ledger import ledger_summary
from app.main import create_app
from app.models import Plan
from app.planner import sample_plan
from tests.fakes import FakeModels, fake_client

TODAY = date(2026, 10, 26)
HTMX = {"HX-Request": "true"}
ANDHRA_PRADESH = (
    "kurnool|guntur|nellore|tirupati|rajahmundry|kakinada|anantapur|kadapa|visakhapatnam"
    "|vijayawada|andhra"
)


@pytest.fixture
def app_and_models(settings: Settings) -> tuple[TestClient, FakeModels]:
    ai, models = fake_client()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: ai
    app.dependency_overrides[get_today] = lambda: TODAY
    return TestClient(app), models


def _sample(client: TestClient, city: str = "Mumbai", **headers: str) -> Any:
    return client.post("/api/plan/sample", json={"city": city}, headers=headers)


def test_sample_loads_without_any_ai_call(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, models = app_and_models

    response = _sample(client)

    assert response.status_code == 200
    assert models.calls == []
    plan = Plan.model_validate(response.json()["view"]["plan"])
    assert plan.event.title == "Sample wedding"
    assert plan.sources.plan == "sample"


@pytest.mark.parametrize("city", [c.name for c in get_sample().cities])
def test_sample_passes_every_invariant_in_every_city(city: str) -> None:
    plan = sample_plan(city, ref=get_reference_data(), sample=get_sample(), today=TODAY)

    committed, over_by, unallocated = budget_status(plan)
    assert committed == plan.event.total_budget
    assert (over_by, unallocated) == (0, 0)
    for function in plan.functions:
        assert plan.event.start_date <= function.start.date() <= plan.event.end_date
    assert all(t.due_date <= plan.event.end_date for t in plan.tasks)
    summary = ledger_summary(plan)
    assert summary.total_assigned + summary.unassigned == summary.total_planned
    assert Plan.model_validate_json(plan.model_dump_json()) == plan


def test_sample_shows_every_feature() -> None:
    plan = sample_plan("Mumbai", ref=get_reference_data(), sample=get_sample(), today=TODAY)

    assert len(plan.functions) == 4
    assert [i for i in plan.line_items if i.locked]
    assert any(len(i.payers) == 2 for i in plan.line_items)
    assert plan.ideas
    assert any(t.status == "done" for t in plan.tasks)


def test_city_change_reprices_catering(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models

    def catering_floor(city: str) -> int:
        warnings = _sample(client, city).json()["view"]["budget"]["warnings"]
        lows = [w["typical_low"] for w in warnings if w.get("category") == "catering"]
        return max(lows, default=0)

    assert catering_floor("Mumbai") > catering_floor("Jodhpur")


def test_sample_is_labelled_in_the_page(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models

    html = _sample(client, "Pune", **HTMX).text

    assert "This is a sample plan with made-up details" in html
    assert "Pune" in html
    assert 'id="plan-state"' in html


def test_unknown_city_is_rejected(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, _ = app_and_models

    response = _sample(client, "Atlantis")

    assert response.status_code == 422
    assert "sample cities" in response.json()["detail"]


def test_sample_data_names_no_real_people_or_andhra_pradesh_cities() -> None:
    raw = (DATA_DIR / "sample_plan.json").read_text(encoding="utf-8")

    assert not re.search(ANDHRA_PRADESH, raw, re.IGNORECASE)
    names = {p["name"] for p in json.loads(raw)["people"]}
    assert names == {"Bride's family", "Groom's family"}


def test_home_page_offers_the_sample_with_a_city_list(client: TestClient) -> None:
    html = client.get("/").text

    assert 'hx-post="/api/plan/sample"' in html
    assert '<option value="Mumbai" data-lat="19.076" data-lon="72.878" selected>' in html
    assert html.count("<option value=") == len(get_sample().cities)
    assert 'data-action="nearest-city"' in html
    assert '<script src="/static/js/sample.js" defer></script>' in html


def test_location_never_leaves_the_browser(client: TestClient) -> None:
    script = client.get("/static/js/sample.js").text

    assert "navigator.geolocation.getCurrentPosition" in script
    for sender in ("fetch(", "XMLHttpRequest", "sendBeacon", "htmx.ajax"):
        assert sender not in script
