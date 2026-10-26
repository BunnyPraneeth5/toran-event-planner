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
from app.main import create_app
from app.models import Plan
from tests.factories import make_allocated_plan
from tests.fakes import fake_client, response

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai"
HTMX = {"HX-Request": "true"}


def _client(settings: Settings, steps: list[Any] | None = None) -> TestClient:
    ai = fake_client(*steps)[0] if steps is not None else None
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: ai
    return TestClient(app)


def _intake_reply(name: str, **changes: Any) -> Any:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["response"]
    data.update(changes)
    return response(json.dumps(data))


def _assert_csp_safe(html: str) -> None:
    """No inline scripts, no inline styles, no hx-on, no CDN scripts."""
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert 'src="/static/' in tag, tag
    assert "style=" not in html
    assert "hx-on" not in html
    assert "javascript:" not in html


# base layout and intake page


def test_home_page_has_accessible_layout(client: TestClient) -> None:
    response_ = client.get("/")

    assert response_.status_code == 200
    html = response_.text
    assert '<html lang="en">' in html
    assert '<a class="skip-link" href="#main">' in html
    assert '<main id="main"' in html
    assert html.count('aria-live="polite"') == 1
    assert '<label for="intake-text">' in html
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html
    _assert_csp_safe(html)


def test_htmx_config_turns_off_eval_and_inline_styles(client: TestClient) -> None:
    html = client.get("/").text

    config = json.loads(re.search(r"name=\"htmx-config\" content='([^']+)'", html).group(1))  # type: ignore[union-attr]
    assert config == {
        "includeIndicatorStyles": False,
        "allowEval": False,
        "allowScriptTags": False,
        "selfRequestsOnly": True,
    }


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/static/vendor/htmx.min.js", "javascript"),
        ("/static/js/app.js", "javascript"),
        ("/static/css/app.css", "css"),
    ],
)
def test_static_assets_are_served_locally(client: TestClient, path: str, kind: str) -> None:
    response_ = client.get(path)

    assert response_.status_code == 200
    assert kind in response_.headers["content-type"]


def test_vendored_htmx_is_the_pinned_version(client: TestClient) -> None:
    assert 'version:"2.0.11"' in client.get("/static/vendor/htmx.min.js").text


def test_app_js_defines_the_json_extension_and_error_handling(client: TestClient) -> None:
    script = client.get("/static/js/app.js").text

    assert 'htmx.defineExtension("toran-json"' in script
    assert "htmx:responseError" in script
    assert "htmx:sendError" in script
    assert "eval(" not in script


# brief form


def test_brief_form_highlights_missing_fields_and_asks_questions(settings: Settings) -> None:
    client = _client(settings, [_intake_reply("intake_hinglish")])

    body = {"text": "Behen ki shaadi Pune mein"}
    html = client.post("/api/plan/intake", json=body, headers=HTMX).text

    assert '<form class="brief-form" hx-post="/api/plan/generate"' in html
    date_input = re.search(r'<input id="f-start-date"[^>]*>', html).group(0)  # type: ignore[union-attr]
    assert 'aria-invalid="true"' in date_input
    assert 'value=""' in date_input
    assert 'Needed: Which day in March 2027?' in html
    assert 'value="Pune"' in html
    assert 'data-type="int" required value="300"' in html
    assert 'data-answer-for="Which functions would you like to include?"' in html
    assert 'value="Behen ki shaadi Pune mein"' in html
    assert 'data-shape="intake">Update with my answers' in html
    assert "That is ₹20 lakh." in html
    _assert_csp_safe(html)


def test_complete_brief_has_no_needed_fields(settings: Settings) -> None:
    client = _client(settings, [_intake_reply("intake_valid")])

    html = client.post("/api/plan/intake", json={"text": "Sister's wedding"}, headers=HTMX).text

    assert "Needed" not in html
    assert 'aria-invalid' not in html
    assert "Everything needed is here." in html


def test_not_an_event_shows_message_without_form(settings: Settings) -> None:
    client = _client(settings, [_intake_reply("intake_non_event")])

    html = client.post("/api/plan/intake", json={"text": "Write a poem"}, headers=HTMX).text

    assert "Toran plans weddings, birthdays and community events" in html
    assert "<form" not in html


def test_user_text_is_escaped_in_the_form(settings: Settings) -> None:
    client = _client(settings, [_intake_reply("intake_valid", city='"><script>alert(1)</script>')])

    html = client.post("/api/plan/intake", json={"text": "<b>hi</b> wedding"}, headers=HTMX).text

    assert "<script>alert(1)" not in html
    assert "&lt;b&gt;hi&lt;/b&gt;" in html
    _assert_csp_safe(html)


# fallback banners


def test_intake_without_ai_shows_banner_and_empty_form(settings: Settings) -> None:
    html = _client(settings).post("/api/plan/intake", json={"text": "A wedding"}, headers=HTMX).text

    assert f'<p class="banner" role="status">{BANNER_TEXT[AIErrorKind.UNAVAILABLE]}</p>' in html
    assert html.count('aria-invalid="true"') == 5


def test_fallback_plan_shows_banner_even_without_banner_text(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["sources"]["plan"] = "fallback"

    html = _client(settings).post("/api/plan/recompute", json={"plan": plan}, headers=HTMX).text

    assert "Parts of this plan use rule-based defaults" in html
    _assert_csp_safe(html)


def test_ai_plan_has_no_banner(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")

    html = _client(settings).post("/api/plan/recompute", json={"plan": plan}, headers=HTMX).text

    assert 'class="banner"' not in html


# T16 dashboard and state contract


def _dashboard_client(settings: Settings, today: Any = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: None
    if today is not None:
        app.dependency_overrides[get_today] = lambda: today
    return TestClient(app)


def _plan_state(html: str) -> Plan:
    found = re.findall(r'<div id="plan-state" hidden data-plan="([^"]*)"></div>', html)
    assert len(found) == 1
    return Plan.model_validate_json(unescape(found[0]))


def _post_all_plan_routes(client: TestClient) -> dict[str, str]:
    plan = make_allocated_plan().model_dump(mode="json")
    cut = {"kind": "budget_cut", "new_total": 2_000_000}
    option = {"id": "o1", "rationale": "Trim evenly",
              "ops": [{"op": "scale_category", "category": c, "percent": -30}
                      for c in ("catering", "venue", "attire", "decor", "photo_video")]}
    brief = {"event_type": "wedding", "city": "Jaipur", "start_date": "2027-02-14",
             "guests": 400, "total_budget": 2_500_000}
    requests = {
        "generate": ("/api/plan/generate", {"brief": brief}),
        "recompute": ("/api/plan/recompute", {"plan": plan}),
        "whatif": ("/api/budget/whatif",
                   {"plan": plan, "changes": [{"change": "set_total", "total": 2_000_000}]}),
        "apply": ("/api/adapt/apply", {"plan": plan, "change": cut, "option": option}),
    }
    pages = {}
    for name, (path, body) in requests.items():
        response_ = client.post(path, json=body, headers=HTMX)
        assert response_.status_code == 200, (name, response_.text[:300])
        pages[name] = response_.text
    return pages


def test_dashboard_partials_embed_plan_state(settings: Settings) -> None:
    pages = _post_all_plan_routes(_dashboard_client(settings))

    for name, html in pages.items():
        plan = _plan_state(html)
        assert plan.schema_version == 1, name
        _assert_csp_safe(html)
    assert _plan_state(pages["whatif"]).event.total_budget == 2_000_000


def test_dashboard_shows_every_section(settings: Settings) -> None:
    html = _post_all_plan_routes(_dashboard_client(settings))["recompute"]

    for heading in ("Budget", "Functions", "Timeline", "Who pays", "Keep your plan"):
        assert f">{heading}</h3>" in html, heading
    categories = {i.category for i in make_allocated_plan().line_items}
    assert html.count("<meter ") == len(categories)
    assert "<caption>Budget by category</caption>" in html
    assert "₹25 lakh planned of ₹25 lakh." in html
    assert "Haldi" in html
    assert "Due in " in html
    assert 'data-action="export-plan"' in html
    assert 'data-action="import-plan"' in html


def test_timeline_labels_late_and_at_risk_in_text(settings: Settings) -> None:
    plan = make_allocated_plan()
    soon = plan.event.start_date - timedelta(days=30)

    html = _dashboard_client(settings, today=soon).post(
        "/api/plan/recompute", json={"plan": plan.model_dump(mode="json")}, headers=HTMX
    ).text

    assert '<span class="status status-late">Late, ready by' in html
    assert re.search(r"\d+ tasks: [1-9]\d* late, \d+ more at risk, \d+ done\.", html)


def test_ledger_shows_people_and_balances(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["people"] = [{"id": "bride", "name": "Bride's family", "pledge": 1_000_000}]
    plan["line_items"][0]["payers"] = [{"person_id": "bride", "share_pct": 100}]

    html = _dashboard_client(settings).post(
        "/api/plan/recompute", json={"plan": plan}, headers=HTMX
    ).text

    assert "<th scope=\"row\">Bride&#39;s family</th>" in html
    assert "of pledge unused" in html
    assert "is not yet assigned to anyone." in html


def test_low_catering_warns_with_typical_range(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["event"]["total_budget"] = 300_000
    for item in plan["line_items"]:
        item["planned"] = item["planned"] * 300_000 // 2_500_000

    html = _dashboard_client(settings).post(
        "/api/plan/recompute", json={"plan": plan}, headers=HTMX
    ).text

    assert "Catering for Reception looks low for Jodhpur: usually" in html


def test_saved_plan_page_loads_from_the_browser(client: TestClient) -> None:
    html = client.get("/plan").text

    assert 'hx-post="/api/plan/recompute" hx-trigger="toran:load" data-shape="recompute"' in html
    assert "There is no plan saved in this browser yet." in html
    assert 'data-when-empty' in html
    _assert_csp_safe(html)


def test_home_links_to_saved_plan_when_one_exists(client: TestClient) -> None:
    html = client.get("/").text

    assert '<p class="card saved-plan" data-when-saved hidden>' in html
    assert '<div id="dashboard" data-open-plan="/plan" hidden></div>' in html


def test_state_js_handles_saving_versions_tabs_and_persistence(client: TestClient) -> None:
    script = client.get("/static/js/state.js").text

    assert "SCHEMA_VERSION = 1" in script
    assert "navigator.storage.persist()" in script
    assert 'window.addEventListener("storage"' in script
    assert 'fetch("/api/plan/recompute"' in script
    assert "htmx:afterSwap" in script
    assert "eval(" not in script
