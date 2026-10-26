import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.api.deps import get_today
from app.config import Settings, get_settings
from app.main import create_app
from app.models import Plan
from tests.factories import DAY0, make_allocated_plan

HTMX = {"HX-Request": "true"}
STATIC = Path(__file__).parents[2] / "app" / "web" / "static" / "js"
SECTIONS = [
    ("overview", "Overview"),
    ("change", "Something changed?"),
    ("budget", "Budget"),
    ("what-if", "What if"),
    ("timeline", "Timeline"),
    ("functions", "Functions"),
    ("who-pays", "Who pays"),
    ("keep-plan", "Keep your plan"),
]


def _client(settings: Settings, today: date) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: None
    app.dependency_overrides[get_today] = lambda: today
    return TestClient(app)


def _dashboard(settings: Settings, plan: Plan, today: date) -> tuple[str, dict[str, Any]]:
    client = _client(settings, today)
    body = {"plan": plan.model_dump(mode="json")}
    html = client.post("/api/plan/recompute", json=body, headers=HTMX).text
    data = client.post("/api/plan/recompute", json=body).json()
    return html, data


def _nav(html: str) -> str:
    return re.search(r'<nav class="plan-nav".*?</nav>', html, re.S).group(0)  # type: ignore[union-attr]


def _nav_status(html: str, label: str) -> str:
    link = rf'<li><a href="#[\w-]+">{re.escape(label)}</a> '
    pattern = link + r'<span class="nav-status"[^>]*>([^<]*)</span>'
    return re.search(pattern, _nav(html)).group(1)  # type: ignore[union-attr]


def _section_ids(html: str) -> list[str]:
    return re.findall(r'<section id="([\w-]+)"', html)


def test_panel_links_match_section_ids_in_order(settings: Settings) -> None:
    html, _ = _dashboard(settings, make_allocated_plan(), DAY0 - timedelta(days=200))

    nav = _nav(html)
    assert '<nav class="plan-nav" aria-label="Plan sections">' in nav
    links = re.findall(r'<a href="#([\w-]+)">([^<]+)</a>', nav)
    assert links == SECTIONS
    assert _section_ids(html) == [section_id for section_id, _ in SECTIONS]


def test_statuses_match_engine_figures(settings: Settings) -> None:
    plan = make_allocated_plan()
    late_day = DAY0 - timedelta(days=30)
    html, data = _dashboard(settings, plan, late_day)

    view = data["view"]
    late = sum(1 for t in view["tasks"] if t["late"])
    assert late > 0
    assert _nav_status(html, "Timeline") == f"{late} late"
    assert _nav_status(html, "Overview") == f"{view['days_to_go']} days to go"
    assert view["days_to_go"] == (DAY0 - late_day).days
    assert _nav_status(html, "Budget") == "On budget"
    assert _nav_status(html, "Who pays") == "₹25 lakh unassigned"
    assert _nav_status(html, "Functions") == str(len(plan.functions))
    assert "₹25 lakh, on budget, " in _nav(html)


def test_over_budget_status_and_actions(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["line_items"][0]["status"] = "paid"
    plan["line_items"][0]["actual"] = plan["line_items"][0]["planned"] + 40_000
    html, data = _dashboard(settings, Plan.model_validate(plan), DAY0 - timedelta(days=30))

    assert data["view"]["budget"]["over_by"] == 40_000
    assert _nav_status(html, "Budget") == "Over by ₹40,000"
    assert "over by ₹40,000" in _nav(html)
    actions = re.search(r'<ul class="action-list".*?</ul>', html, re.S).group(0)  # type: ignore[union-attr]
    assert '<a href="#budget">The plan is over budget by ₹40,000</a>' in actions
    assert '<a href="#budget">1 booked line costs more than planned</a>' in actions
    assert re.search(r'<a href="#timeline">\d+ late tasks?</a>', actions)
    assert '<a href="#who-pays">' in actions


def test_overview_with_nothing_to_do(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["people"] = [{"id": "fam", "name": "Family"}]
    for item in plan["line_items"]:
        item["payers"] = [{"person_id": "fam", "share_pct": 100}]
    html, _ = _dashboard(settings, Plan.model_validate(plan), DAY0 - timedelta(days=400))

    assert "Nothing needs action right now." in html
    assert '<ul class="action-list"' not in html


def test_overview_has_countdown_bar_and_change_link(settings: Settings) -> None:
    html, _ = _dashboard(settings, make_allocated_plan(), DAY0 - timedelta(days=97))

    overview = re.search(r'<section id="overview".*?</section>', html, re.S).group(0)  # type: ignore[union-attr]
    assert '<p class="countdown">97 days to go</p>' in overview
    assert '<svg viewBox="0 0 100 6"' in overview
    assert 'aria-hidden="true"' in overview
    assert "₹25 lakh planned of ₹25 lakh, of which ₹0 is booked or paid." in overview
    assert '<a class="button-link" href="#change">Something changed? Get fixes</a>' in overview


@pytest.mark.parametrize(
    ("days", "text"), [(1, "1 day to go"), (0, "Starts today"), (-1, "Under way")]
)
def test_countdown_wording(settings: Settings, days: int, text: str) -> None:
    html, _ = _dashboard(settings, make_allocated_plan(), DAY0 - timedelta(days=days))

    assert f'<p class="countdown">{text}</p>' in html


def test_timeline_shows_urgent_and_next_five_and_folds_the_rest(settings: Settings) -> None:
    plan = make_allocated_plan()
    html, data = _dashboard(settings, plan, DAY0 - timedelta(days=400))

    assert not any(t["late"] or t["at_risk"] for t in data["view"]["tasks"])
    timeline = re.search(r'<section id="timeline".*?</section>', html, re.S).group(0)  # type: ignore[union-attr]
    first_table = timeline.split("<details")[0]
    assert first_table.count('<th scope="row">') == 5
    later = len(plan.tasks) - 5
    assert later > 0
    assert f"<summary>{later} later task" in timeline


def test_timeline_folds_done_tasks(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["tasks"][0]["status"] = "done"
    html, _ = _dashboard(settings, Plan.model_validate(plan), DAY0 - timedelta(days=400))

    assert '<details class="editor" id="done-tasks">' in html
    assert "<summary>1 done</summary>" in html


def test_functions_show_time_ranges_with_weekday_and_fold_ideas(settings: Settings) -> None:
    plan = make_allocated_plan().model_dump(mode="json")
    plan["ideas"] = [
        {"id": "i1", "function_id": plan["functions"][0]["id"], "text": "Marigold arch",
         "cost_band": "low"}
    ]
    html, _ = _dashboard(settings, Plan.model_validate(plan), DAY0 - timedelta(days=200))

    assert re.search(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{1,2} \w{3}, \d\d:\d\d to \d\d:\d\d", html)
    assert '<details class="ideas-fold"' in html
    assert "<summary>1 idea</summary>" in html


def test_save_status_and_undo_controls_present(settings: Settings) -> None:
    html, _ = _dashboard(settings, make_allocated_plan(), DAY0 - timedelta(days=200))

    assert html.count("data-save-status") == 2
    assert html.count('data-action="undo-plan" hidden') == 2


def test_undo_is_kept_in_state_js() -> None:
    state = (STATIC / "state.js").read_text(encoding="utf-8")

    assert 'var UNDO_KEY = "toran.plan.undo";' in state
    assert "write(UNDO_KEY, current)" in state
    assert "remove(UNDO_KEY)" in state
    assert 'button.dataset.action === "undo-plan"' in state


def test_home_hands_new_plans_to_the_plan_page(settings: Settings) -> None:
    client = _client(settings, DAY0 - timedelta(days=200))

    home = client.get("/").text

    assert '<div id="dashboard" data-open-plan="/plan" hidden></div>' in home
    state = (STATIC / "state.js").read_text(encoding="utf-8")
    assert "window.location.assign(root.dataset.openPlan)" in state
    for form in re.findall(r"<form[^>]*>", home):
        if 'data-shape="sample"' in form:
            assert 'hx-target="#dashboard"' in form


def test_generate_and_sample_responses_carry_the_plan(settings: Settings) -> None:
    client = _client(settings, DAY0 - timedelta(days=200))

    sample = client.post("/api/plan/sample", json={"city": "Mumbai"}, headers=HTMX).text

    assert '<div id="plan-state" hidden data-plan="' in sample
    brief = client.post(
        "/api/plan/intake", json={"text": "wedding in Jaipur"}, headers=HTMX
    ).text
    assert 'hx-target="#dashboard"' in brief
    assert 'data-step="check"' in brief


def test_step_marker_on_home_and_plan_pages(settings: Settings) -> None:
    client = _client(settings, DAY0 - timedelta(days=200))

    home = client.get("/").text
    plan_page = client.get("/plan").text

    assert '<ol class="steps" aria-label="Steps">' in home
    assert '<li data-step-marker="describe" aria-current="step">Describe</li>' in home
    assert '<li data-step-marker="plan" aria-current="step">Plan</li>' in plan_page
    assert 'class="wrap wide"' in plan_page


def test_brief_budget_shows_lakh_as_you_type(settings: Settings) -> None:
    client = _client(settings, DAY0 - timedelta(days=200))

    brief = client.post("/api/plan/intake", json={"text": "wedding in Jaipur"}, headers=HTMX).text

    assert 'data-live-amount="budget-hint"' in brief
    assert 'id="budget-hint"' in brief
    whatif = (STATIC / "whatif.js").read_text(encoding="utf-8")
    assert "input.dataset.liveAmount" in whatif


def test_nav_script_is_loaded_and_respects_reduced_motion(settings: Settings) -> None:
    client = _client(settings, DAY0 - timedelta(days=200))

    assert '<script src="/static/js/nav.js" defer></script>' in client.get("/plan").text
    css = (STATIC.parent / "css" / "app.css").read_text(encoding="utf-8")
    motion = "@media (prefers-reduced-motion: no-preference)"
    assert motion in css
    assert "scroll-behavior: smooth" in css.split(motion)[1]
