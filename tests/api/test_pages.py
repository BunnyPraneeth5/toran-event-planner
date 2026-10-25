import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import BANNER_TEXT, AIErrorKind, get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
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
