import re
from html import unescape
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
from app.models import Person, Plan
from app.models.plan import MAX_PEOPLE
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
    plan["people"] = [
        {"id": "bride_side", "name": "Bride's family", "side_or_role": "", "pledge": 1_200_000},
        {"id": "groom_side", "name": "Groom's family", "side_or_role": "", "pledge": 800_000},
    ]
    return plan


def _post(client: TestClient, plan: dict[str, Any], change: dict[str, Any], **headers: str) -> Any:
    return client.post("/api/people", json={"plan": plan, "change": change}, headers=headers)


def _state(html: str) -> Plan:
    raw = re.search(r'data-plan="([^"]*)"', html).group(1)  # type: ignore[union-attr]
    return Plan.model_validate_json(unescape(raw))


def test_add_person_assigns_server_id(client: TestClient) -> None:
    change = {"action": "add_person", "name": "Mama ji", "side_or_role": "uncle", "pledge": 75_000}

    response = _post(client, _plan(), change)

    assert response.status_code == 200
    people = response.json()["view"]["plan"]["people"]
    added = people[-1]
    assert (added["name"], added["side_or_role"], added["pledge"]) == ("Mama ji", "uncle", 75_000)
    assert re.fullmatch(r"[0-9a-f]{12}", added["id"])
    rows = response.json()["view"]["ledger"]["rows"]
    assert rows[-1]["pledged"] == 75_000


def test_add_person_refuses_an_id_from_the_client(client: TestClient) -> None:
    change = {"action": "add_person", "name": "Mama ji", "id": "chosen"}

    assert _post(client, _plan(), change).status_code == 422


def test_update_pledge(client: TestClient) -> None:
    change = {"action": "update_pledge", "person_id": "groom_side", "pledge": 950_000}

    response = _post(client, _plan(), change)

    people = {p["id"]: p["pledge"] for p in response.json()["view"]["plan"]["people"]}
    assert people["groom_side"] == 950_000


def test_remove_person_clears_payers_and_owners_with_notice(client: TestClient) -> None:
    plan = _plan()
    plan["line_items"][0]["payers"] = [{"person_id": "bride_side", "share_pct": 100}]
    plan["line_items"][1]["payers"] = [
        {"person_id": "bride_side", "share_pct": 50},
        {"person_id": "groom_side", "share_pct": 50},
    ]
    plan["tasks"][0]["owner_id"] = "bride_side"

    response = _post(client, plan, {"action": "remove_person", "person_id": "bride_side"})

    body = response.json()
    assert body["notices"] == ["Removed Bride's family. 2 lines now have no payer."]
    new_plan = body["view"]["plan"]
    assert [p["id"] for p in new_plan["people"]] == ["groom_side"]
    assert new_plan["line_items"][0]["payers"] == []
    assert new_plan["line_items"][1]["payers"] == []
    assert new_plan["tasks"][0]["owner_id"] is None


def test_remove_person_without_lines_has_short_notice(client: TestClient) -> None:
    response = _post(client, _plan(), {"action": "remove_person", "person_id": "groom_side"})

    assert response.json()["notices"] == ["Removed Groom's family."]


def test_single_payer(client: TestClient) -> None:
    plan = _plan()
    line = plan["line_items"][0]
    change = {
        "action": "set_payers",
        "line_item_id": line["id"],
        "mode": "single",
        "person_id": "groom_side",
    }

    body = _post(client, plan, change).json()

    assert body["view"]["plan"]["line_items"][0]["payers"] == [
        {"person_id": "groom_side", "share_pct": 100}
    ]
    groom = next(r for r in body["view"]["ledger"]["rows"] if r["person_id"] == "groom_side")
    assert groom["assigned"] == line["planned"]


def test_custom_split_ignores_zero_shares(client: TestClient) -> None:
    plan = _plan()
    change = {
        "action": "set_payers",
        "line_item_id": plan["line_items"][0]["id"],
        "mode": "custom",
        "shares": [
            {"person_id": "bride_side", "share_pct": 75},
            {"person_id": "groom_side", "share_pct": 25},
        ],
    }

    body = _post(client, plan, change).json()

    payers = body["view"]["plan"]["line_items"][0]["payers"]
    assert [(p["person_id"], p["share_pct"]) for p in payers] == [
        ("bride_side", 75),
        ("groom_side", 25),
    ]
    change["shares"] = [
        {"person_id": "bride_side", "share_pct": 100},
        {"person_id": "groom_side", "share_pct": 0},
    ]
    payers = _post(client, plan, change).json()["view"]["plan"]["line_items"][0]["payers"]
    assert payers == [{"person_id": "bride_side", "share_pct": 100}]


def test_split_equally_gives_exact_rupees(client: TestClient) -> None:
    plan = _plan()
    plan["people"].append(Person(id="mama", name="Mama ji").model_dump(mode="json"))
    plan["line_items"][0]["planned"] = 100_000
    change = {"action": "set_payers", "line_item_id": "li1", "mode": "everyone"}

    body = _post(client, plan, change).json()

    shares = [p["share_pct"] for p in body["view"]["plan"]["line_items"][0]["payers"]]
    assert sorted(shares) == [33, 33, 34]
    assigned = sorted(r["assigned"] for r in body["view"]["ledger"]["rows"])
    assert assigned == [33_000, 33_000, 34_000]


def test_unassign_a_line(client: TestClient) -> None:
    plan = _plan()
    plan["line_items"][0]["payers"] = [{"person_id": "bride_side", "share_pct": 100}]
    change = {"action": "set_payers", "line_item_id": plan["line_items"][0]["id"], "mode": "none"}

    body = _post(client, plan, change).json()

    assert body["view"]["plan"]["line_items"][0]["payers"] == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"action": "update_pledge", "person_id": "nobody", "pledge": 1}, "unknown person nobody"),
        ({"action": "remove_person", "person_id": "nobody"}, "unknown person nobody"),
        (
            {"action": "set_payers", "line_item_id": "missing", "mode": "single",
             "person_id": "bride_side"},
            "unknown line item missing",
        ),
        (
            {"action": "set_payers", "line_item_id": "li1", "mode": "custom",
             "shares": [{"person_id": "bride_side", "share_pct": 60},
                        {"person_id": "groom_side", "share_pct": 30}]},
            "payer shares must add up to 100",
        ),
        (
            {"action": "set_payers", "line_item_id": "li1", "mode": "custom",
             "shares": [{"person_id": "bride_side", "share_pct": 50},
                        {"person_id": "bride_side", "share_pct": 50}]},
            "a person appears twice in the split",
        ),
        (
            {"action": "set_payers", "line_item_id": "li1", "mode": "single"},
            "choose who pays for this line",
        ),
        (
            {"action": "set_payers", "line_item_id": "li1", "mode": "custom", "shares": []},
            "enter a percent for at least one person",
        ),
    ],
)
def test_bad_changes_return_clear_422(
    client: TestClient, change: dict[str, Any], message: str
) -> None:
    response = _post(client, _plan(), change)

    assert response.status_code == 422
    assert response.json() == {"detail": message}


def test_split_equally_with_no_people_is_refused(client: TestClient) -> None:
    plan = _plan()
    plan["people"] = []
    change = {"action": "set_payers", "line_item_id": "li1", "mode": "everyone"}

    response = _post(client, plan, change)

    assert response.json() == {"detail": "add a person before splitting a line"}


def test_more_than_fifty_people_is_refused(client: TestClient) -> None:
    plan = _plan()
    plan["people"] = [{"id": f"p{i}", "name": f"P{i}"} for i in range(MAX_PEOPLE)]

    response = _post(client, plan, {"action": "add_person", "name": "One more"})

    assert response.status_code == 422
    assert response.json() == {"detail": "a plan can have at most 50 people"}


def test_people_changes_make_no_ai_calls(app_and_models: tuple[TestClient, FakeModels]) -> None:
    client, models = app_and_models
    plan = _plan()

    _post(client, plan, {"action": "add_person", "name": "Aunt"})
    _post(client, plan, {"action": "set_payers", "line_item_id": "li1", "mode": "everyone"})
    _post(client, plan, {"action": "remove_person", "person_id": "bride_side"})

    assert models.calls == []


def test_partial_embeds_plan_state_and_editor(client: TestClient) -> None:
    change = {"action": "add_person", "name": "Mama ji", "pledge": 75_000}

    html = _post(client, _plan(), change, **HTMX).text

    saved = _state(html)
    assert saved.people[-1].name == "Mama ji"
    assert 'hx-post="/api/people"' in html
    assert 'data-keep-focus="ledger-heading"' in html
    assert '<label for="person-name">Name</label>' in html
    assert '<label for="payer-line">Budget line</label>' in html
    assert "Pledge for Mama ji, in rupees" in html
    assert 'aria-label="Remove Mama ji"' in html
    assert 'data-list="change.shares"' in html


def test_partial_shows_removal_notice(client: TestClient) -> None:
    html = _post(client, _plan(), {"action": "remove_person", "person_id": "groom_side"}, **HTMX)

    assert '<p class="notice">Removed Groom&#39;s family.</p>' in html.text


def test_no_people_opens_the_add_form(client: TestClient) -> None:
    plan = _plan()
    plan["people"] = []

    html = client.post("/api/plan/recompute", json={"plan": plan}, headers=HTMX).text

    assert '<details class="editor" id="add-person" open>' in html
    assert 'id="edit-payers"' not in html
