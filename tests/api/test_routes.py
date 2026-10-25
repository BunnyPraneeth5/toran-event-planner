import json
import re
from datetime import timedelta
from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import BANNER_TEXT, AIErrorKind, GeminiClient, get_ai_client
from app.api.deps import get_today
from app.config import Settings, get_settings
from app.main import create_app
from app.models import Plan
from tests.factories import DAY0, make_allocated_plan
from tests.fakes import FakeModels, api_error, fake_client, response

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ai"
TODAY = DAY0 - timedelta(days=365)
HTMX = {"HX-Request": "true"}


def _fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class App:
    """A test app whose Gemini client plays back scripted responses."""

    def __init__(self, steps: list[Any] | None, settings: Settings) -> None:
        self.models: FakeModels | None = None
        ai: GeminiClient | None = None
        if steps is not None:
            ai, self.models = fake_client(*steps)
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_ai_client] = lambda: ai
        app.dependency_overrides[get_today] = lambda: TODAY
        self.client = TestClient(app)

    @property
    def models_used(self) -> list[str]:
        return [c["model"] for c in self.models.calls] if self.models else []


@pytest.fixture
def make_app(settings: Settings) -> Any:
    tuned = settings.model_copy(
        update={"gemini_model": "main-model", "gemini_lite_model": "lite-model"}
    )
    return lambda steps=None: App(steps, tuned)


def _plan_json(plan: Plan | None = None) -> dict[str, Any]:
    data: dict[str, Any] = (plan or make_allocated_plan()).model_dump(mode="json")
    return data


BRIEF = {
    "event_type": "wedding",
    "title": "Sister's wedding",
    "city": "Jaipur",
    "start_date": "2027-02-14",
    "guests": 400,
    "total_budget": 2500000,
}


# intake


def test_intake_uses_the_lite_model(make_app: Any) -> None:
    app = make_app([response(json.dumps(json.loads(_fixture_text("intake_valid"))["response"]))])

    body = app.client.post("/api/plan/intake", json={"text": "Sister's wedding in Jaipur"}).json()

    assert body["status"] == "ready"
    assert body["brief"]["total_budget"] == 2_500_000
    assert app.models_used == ["lite-model"]


def test_intake_without_ai_shows_banner(make_app: Any) -> None:
    body = make_app(None).client.post("/api/plan/intake", json={"text": "A wedding"}).json()

    assert body["source"] == "fallback"
    assert body["banner"] == BANNER_TEXT[AIErrorKind.UNAVAILABLE]


def test_intake_rejects_oversized_text(make_app: Any) -> None:
    response_ = make_app(None).client.post("/api/plan/intake", json={"text": "x" * 1001})

    assert response_.status_code == 422


# generate and recompute


def test_generate_uses_the_main_model_and_returns_views(make_app: Any) -> None:
    draft = json.loads(_fixture_text("generate_valid"))["response"]
    app = make_app([response(json.dumps(draft))])

    body = app.client.post("/api/plan/generate", json={"brief": BRIEF}).json()

    view = body["view"]
    assert app.models_used == ["main-model"]
    assert view["budget"]["committed"] == 2_500_000
    assert view["budget"]["over_by"] == 0
    assert len(view["tasks"]) == len(view["plan"]["tasks"])
    assert view["ledger"]["total_planned"] == 2_500_000
    assert Plan.model_validate(view["plan"]).sources.plan == "ai"


def test_generate_fallback_carries_banner(make_app: Any) -> None:
    body = make_app([api_error(503)]).client.post(
        "/api/plan/generate", json={"brief": BRIEF}
    ).json()

    assert body["banner"] == BANNER_TEXT[AIErrorKind.UNAVAILABLE]
    assert body["view"]["plan"]["sources"]["plan"] == "fallback"


def test_generate_rejects_incomplete_brief(make_app: Any) -> None:
    brief = {k: v for k, v in BRIEF.items() if k != "city"}

    response_ = make_app(None).client.post("/api/plan/generate", json={"brief": brief})

    assert response_.status_code == 422


def test_recompute_derives_views_without_ai(make_app: Any) -> None:
    app = make_app([])

    body = app.client.post("/api/plan/recompute", json={"plan": _plan_json()}).json()

    view = body["view"]
    assert view["budget"]["by_category"][0]["category"] == "catering"
    assert {t["task_id"] for t in view["tasks"]} == {t["id"] for t in view["plan"]["tasks"]}
    assert app.models_used == []


# validation of incoming plans


def _broken_plans() -> list[tuple[str, dict[str, Any]]]:
    floats = _plan_json()
    floats["line_items"][0]["planned"] = 1000.5
    dangling = _plan_json()
    dangling["line_items"][0]["function_id"] = "ghost"
    oversized = _plan_json()
    oversized["functions"] = [dict(oversized["functions"][0], id=f"f{i}") for i in range(13)]
    extra = _plan_json()
    extra["event"]["is_admin"] = True
    return [("float money", floats), ("dangling", dangling), ("13 functions", oversized),
            ("unknown field", extra)]


@pytest.mark.parametrize(("label", "plan"), _broken_plans(), ids=lambda x: str(x)[:20])
def test_invalid_plans_rejected_with_422(make_app: Any, label: str, plan: dict[str, Any]) -> None:
    response_ = make_app(None).client.post("/api/plan/recompute", json={"plan": plan})

    assert response_.status_code == 422, label


# what-if


def test_whatif_rebalances_to_the_new_total(make_app: Any) -> None:
    app = make_app([])
    changes = [{"change": "set_total", "total": 2_000_000}]

    body = app.client.post(
        "/api/budget/whatif", json={"plan": _plan_json(), "changes": changes}
    ).json()

    assert body["view"]["budget"]["committed"] == 2_000_000
    assert body["view"]["plan"]["event"]["total_budget"] == 2_000_000
    assert app.models_used == []


def test_whatif_unknown_function_is_422(make_app: Any) -> None:
    changes = [{"change": "set_tier", "function_id": "ghost", "tier": "budget"}]

    response_ = make_app(None).client.post(
        "/api/budget/whatif", json={"plan": _plan_json(), "changes": changes}
    )

    assert response_.status_code == 422
    assert "unknown function" in response_.json()["detail"]


def test_whatif_limits_number_of_changes(make_app: Any) -> None:
    changes = [{"change": "set_total", "total": 2_000_000}] * 21

    response_ = make_app(None).client.post(
        "/api/budget/whatif", json={"plan": _plan_json(), "changes": changes}
    )

    assert response_.status_code == 422


# adapt

CUT = {"kind": "budget_cut", "new_total": 2_000_000}


def test_adapt_options_use_main_model_and_are_verified(make_app: Any) -> None:
    app = make_app([response(_fixture_text("adapt_valid"))])

    body = app.client.post("/api/adapt/options", json={"plan": _plan_json(), "change": CUT}).json()

    assert app.models_used == ["main-model"]
    assert body["impact"]["over_by"] == 500_000
    assert body["source"] == "ai"
    assert all(o["result"]["over_by"] == 0 for o in body["options"])


def test_adapt_unknown_line_is_422(make_app: Any) -> None:
    change = {"kind": "vendor_cancelled", "line_item_id": "ghost"}

    response_ = make_app(None).client.post(
        "/api/adapt/options", json={"plan": _plan_json(), "change": change}
    )

    assert response_.status_code == 422


def test_apply_recomputes_the_chosen_option(make_app: Any) -> None:
    app = make_app([response(_fixture_text("adapt_valid"))])
    plan = _plan_json()
    option = app.client.post(
        "/api/adapt/options", json={"plan": plan, "change": CUT}
    ).json()["options"][0]

    body = app.client.post(
        "/api/adapt/apply", json={"plan": plan, "change": CUT, "option": option}
    ).json()

    assert body["view"]["plan"]["event"]["total_budget"] == 2_000_000
    assert body["view"]["budget"]["over_by"] == 0


def test_apply_refuses_an_option_that_does_not_fix_the_problem(make_app: Any) -> None:
    weak = {"id": "x", "rationale": "Tiny trim",
            "ops": [{"op": "scale_category", "category": "decor", "percent": -1}]}

    response_ = make_app(None).client.post(
        "/api/adapt/apply", json={"plan": _plan_json(), "change": CUT, "option": weak}
    )

    assert response_.status_code == 422
    assert "no longer fixes" in response_.json()["detail"]


def test_apply_never_accepts_a_client_computed_plan(make_app: Any) -> None:
    option = {"id": "x", "rationale": "Simpler reception",
              "ops": [{"op": "change_tier", "function_id": "reception", "tier": "standard"}]}
    body = {"plan": _plan_json(), "change": CUT, "option": option, "result_plan": _plan_json()}

    assert make_app(None).client.post("/api/adapt/apply", json=body).status_code == 422


# HTMX partials


def test_htmx_request_gets_html_with_plan_state(make_app: Any) -> None:
    app = make_app([])

    response_ = app.client.post(
        "/api/plan/recompute", json={"plan": _plan_json()}, headers=HTMX
    )

    assert response_.headers["content-type"].startswith("text/html")
    html = response_.text
    state = re.search(r'<div id="plan-state" hidden data-plan="([^"]*)"></div>', html)
    assert state is not None
    assert Plan.model_validate_json(unescape(state.group(1))) == make_allocated_plan()
    assert "₹25,00,000" in html
    assert "style=" not in html
    assert "<script" not in html


def test_htmx_partials_escape_user_text(make_app: Any) -> None:
    plan = _plan_json()
    plan["event"]["title"] = "<img src=x onerror=alert(1)></script>"

    html = make_app([]).client.post(
        "/api/plan/recompute", json={"plan": plan}, headers=HTMX
    ).text

    assert "<img" not in html
    assert "&lt;img" in html
    assert "</script>" not in html
    state = re.search(r'data-plan="([^"]*)"', html)
    assert state is not None
    assert Plan.model_validate_json(unescape(state.group(1))).event.title == plan["event"]["title"]


def test_htmx_fallback_shows_banner(make_app: Any) -> None:
    html = make_app(None).client.post(
        "/api/plan/generate", json={"brief": BRIEF}, headers=HTMX
    ).text

    assert BANNER_TEXT[AIErrorKind.UNAVAILABLE] in html
    assert 'role="status"' in html


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/plan/intake", {"text": "Write a poem"}),
        ("/api/adapt/options", {"plan": None, "change": CUT}),
    ],
)
def test_other_partials_render(make_app: Any, path: str, payload: dict[str, Any]) -> None:
    if payload.get("plan", 1) is None:
        payload = {**payload, "plan": _plan_json()}
    response_ = make_app(None).client.post(path, json=payload, headers=HTMX)

    assert response_.status_code == 200
    assert response_.headers["content-type"].startswith("text/html")
    assert response_.text.lstrip().startswith("<")
    assert "style=" not in response_.text
