from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
from tests.factories import make_allocated_plan
from tests.fakes import fake_client


def test_ics_download_is_a_calendar_attachment(settings: Settings) -> None:
    ai, models = fake_client()
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: ai
    client = TestClient(app)

    response = client.post(
        "/api/calendar/ics", json={"plan": make_allocated_plan().model_dump(mode="json")}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.headers["content-disposition"] == 'attachment; filename="toran-plan.ics"'
    assert response.text.startswith("BEGIN:VCALENDAR")
    assert models.calls == []


def test_ics_rejects_an_invalid_plan(client: TestClient) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["line_items"][0]["function_id"] = "ghost"

    assert client.post("/api/calendar/ics", json={"plan": plan}).status_code == 422


def test_timeline_offers_download_and_google_links(client: TestClient) -> None:
    plan = make_allocated_plan()

    html = client.post(
        "/api/plan/recompute",
        json={"plan": plan.model_dump(mode="json")},
        headers={"HX-Request": "true"},
    ).text

    assert 'data-action="download-ics"' in html
    assert html.count('href="https://calendar.google.com/calendar/render?action=TEMPLATE') == len(
        plan.tasks
    )
    assert 'target="_blank" rel="noopener noreferrer"' in html
    assert "(opens in a new tab)" in html


def test_calendar_script_downloads_with_fetch_and_blob(client: TestClient) -> None:
    script = client.get("/static/js/calendar.js").text

    assert 'fetch("/api/calendar/ics"' in script
    assert "response.blob()" in script
    assert 'link.download = "toran-plan.ics"' in script
