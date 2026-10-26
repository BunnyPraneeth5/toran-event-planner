import json
import re
from datetime import timedelta
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import BANNER_TEXT, AIErrorKind, get_ai_client
from app.api.deps import get_today
from app.config import Settings, get_settings
from app.engines.budget import budget_status
from app.main import create_app
from app.models import Plan
from app.planner import NOTHING_TO_FIX
from tests.factories import DAY0, make_allocated_plan
from tests.fakes import fake_client, response

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai"
HTMX = {"HX-Request": "true"}
CUT = {"kind": "budget_cut", "new_total": 2_000_000}


KINDS = ("budget_cut", "vendor_cancelled", "guests_changed", "date_moved", "function_dropped")


def _client(
    settings: Settings, steps: list[Any] | None, days_before: int = 365
) -> TestClient:
    ai = fake_client(*steps)[0] if steps is not None else None
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: ai
    app.dependency_overrides[get_today] = lambda: DAY0 - timedelta(days=days_before)
    return TestClient(app)


def _plan() -> dict[str, Any]:
    data: dict[str, Any] = make_allocated_plan().model_dump(mode="json")
    return data


def _options_html(client: TestClient, change: dict[str, Any] = CUT) -> str:
    response_ = client.post(
        "/api/adapt/options", json={"plan": _plan(), "change": change}, headers=HTMX
    )
    assert response_.status_code == 200, response_.text[:300]
    return response_.text


def _apply_bodies(html: str) -> list[dict[str, Any]]:
    return [json.loads(unescape(raw)) for raw in re.findall(r"data-body='([^']*)'", html)]


# the form


def test_dashboard_has_a_form_for_every_change_kind(settings: Settings) -> None:
    html = _client(settings, None).post(
        "/api/plan/recompute", json={"plan": _plan()}, headers=HTMX
    ).text

    assert 'hx-post="/api/adapt/options" hx-target="#options"' in html
    for kind in KINDS:
        assert f'<option value="{kind}">' in html
        assert f'data-change-kind="{kind}"' in html
    assert re.search(r'data-change-kind="vendor_cancelled" hidden disabled', html)
    assert 'name="change.new_total"' in html
    assert ">Catering for Reception, ₹6,76,056</option>" in html
    assert '<option value="haldi">Haldi</option>' in html


def test_app_js_sends_only_the_chosen_kind(client: TestClient) -> None:
    script = client.get("/static/js/app.js").text

    assert "syncChangeKind" in script
    assert "fieldset.disabled = !active" in script
    assert 'apply: ["plan", "change", "option"]' in script


# options


def test_budget_cut_shows_impact_then_verified_options(settings: Settings) -> None:
    html = _options_html(_client(settings, [response((FIXTURES / "adapt_valid.json").read_text())]))

    assert html.index("Over budget by ₹5,00,000.") < html.index("Ways to fix it")
    bodies = _apply_bodies(html)
    assert 2 <= len(bodies) <= 3
    assert html.count("Plan total after this:") == len(bodies)
    for body in bodies:
        assert body["change"] == CUT
        assert body["option"]["result"]["over_by"] == 0
    assert 'role="status"' not in html


def test_fallback_options_carry_the_banner(settings: Settings) -> None:
    html = _options_html(_client(settings, None))

    assert BANNER_TEXT[AIErrorKind.UNAVAILABLE] in html
    assert _apply_bodies(html)


def test_nothing_to_fix_says_so(settings: Settings) -> None:
    later = {"kind": "date_moved", "new_start_date": (DAY0 + timedelta(days=7)).isoformat()}

    html = _options_html(_client(settings, None), later)

    assert NOTHING_TO_FIX in html
    assert "Use option" not in html


# applying


@pytest.mark.parametrize("index", [0, 1])
def test_applying_an_option_updates_and_saves_the_plan(settings: Settings, index: int) -> None:
    client = _client(settings, [response((FIXTURES / "adapt_valid.json").read_text())])
    body = _apply_bodies(_options_html(client))[index]

    html = client.post(
        "/api/adapt/apply", json={"plan": _plan(), **body}, headers=HTMX
    ).text

    raw = re.search(r'data-plan="([^"]*)"', html).group(1)  # type: ignore[union-attr]
    applied = Plan.model_validate_json(unescape(raw))
    committed, over_by, _ = budget_status(applied)
    assert applied.event.total_budget == 2_000_000
    assert over_by == 0
    assert committed <= 2_000_000
    assert 'data-focus>Sister&#39;s wedding</h2>' in html


def test_vendor_cancellation_offers_skip_and_simpler_options(settings: Settings) -> None:
    plan = make_allocated_plan()
    caterer = next(
        i for i in plan.line_items if i.category == "catering" and i.function_id == "reception"
    )
    change = {"kind": "vendor_cancelled", "line_item_id": caterer.id}

    html = _options_html(_client(settings, None, days_before=21), change)

    assert "1 task now late or at risk." in html
    assert "Skip this vendor and keep the money" in html


def test_disabled_fieldsets_are_left_out_of_requests(client: TestClient) -> None:
    script = client.get("/static/js/app.js").text

    assert 'field.matches(":disabled")' in script
    assert "field.disabled ||" not in script
