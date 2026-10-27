"""One real-browser flow at phone and desktop size, a keyboard-only path, and axe scans.

Run with `pytest e2e`. Gemini is faked (see conftest.py); everything else is the real app.
With BASE_URL set, only the flows that need no AI run, against that deployed site.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page

from e2e.conftest import DESKTOP, PHONE, LiveServer, open_session, serious_axe_violations

EVENT = "Sister's wedding in Jaipur, Feb 14 2027, about 400 guests, 25 lakh budget."
SAVED_TOTAL = "() => JSON.parse(localStorage.getItem('toran.plan')).event.total_budget"


def _no_page_scroll(page: Page) -> bool:
    return bool(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"))


def _assert_accessible(page: Page, view: str) -> None:
    violations = serious_axe_violations(page)
    assert violations == [], (view, violations)


def _settled(page: Page) -> None:
    """Wait until htmx has finished swapping and settling new content, as a person would."""
    busy = ".htmx-request, .htmx-swapping, .htmx-settling, .htmx-added"
    page.wait_for_function(f"() => !document.querySelector('{busy}')")


def _tab_to(page: Page, test: str, limit: int = 80) -> None:
    """Press Tab until the focused element passes the JS test `el => boolean`."""
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate(f"() => ({test})(document.activeElement)"):
            return
    raise AssertionError(f"Tab never reached an element matching {test}")


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_full_flow(browser: Browser, live_server: LiveServer, viewport: dict[str, int]) -> None:
    live_server.require_fake_ai()
    session = open_session(browser, live_server, viewport)
    page = session.page

    # Describe
    page.goto(session.url + "/")
    _assert_accessible(page, "intake")
    page.fill("#intake-text", EVENT)
    page.get_by_role("button", name="Read my event").click()

    # Check: the brief with follow-up questions
    page.wait_for_selector("#brief-heading")
    assert page.get_attribute("[data-step-marker='check']", "aria-current") == "step"
    assert page.input_value("#f-budget") == "2500000"
    _assert_accessible(page, "brief")
    page.fill("#q-1", "Haldi, mehendi, sangeet and the wedding")
    page.get_by_role("button", name="Make my plan").click()

    # Plan: the new plan opens on /plan
    page.wait_for_url("**/plan")
    page.wait_for_selector("#plan-heading")
    assert "Sister's wedding" in page.inner_text("#plan-heading")
    assert page.evaluate(SAVED_TOTAL) == 2_500_000
    assert page.text_content("[data-save-status] >> nth=0") == "Saved in this browser."
    _assert_accessible(page, "dashboard")

    # What if: one step down on the total budget slider, recomputed by the engines
    page.focus("#wi-total")
    with page.expect_response(lambda r: r.url.endswith("/api/budget/whatif")):
        page.keyboard.press("ArrowLeft")
    page.wait_for_function(f"() => ({SAVED_TOTAL})() < 2500000")

    # Something changed: budget cut to 20 lakh, then pick the first verified option
    page.fill("#change-total", "2000000")
    page.get_by_role("button", name="See what this changes").click()
    page.wait_for_selector("#options-heading")
    _settled(page)
    _assert_accessible(page, "adapt")
    with page.expect_response(lambda r: r.url.endswith("/api/adapt/apply")):
        page.get_by_role("button", name="Use option 1").click()
    page.wait_for_function(f"() => ({SAVED_TOTAL})() === 2000000")
    assert "Over by" not in page.inner_text("#overview")

    # Export
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Download plan file").click()
    download = download_info.value
    assert download.suggested_filename == "toran-plan.json"
    exported = json.loads(Path(download.path()).read_text(encoding="utf-8"))
    assert exported["schema_version"] == 1
    assert exported["event"]["total_budget"] == 2_000_000

    # The plan survives a reload
    page.reload()
    page.wait_for_selector("#plan-heading")
    assert "Sister's wedding" in page.inner_text("#plan-heading")
    assert page.evaluate(SAVED_TOTAL) == 2_000_000

    assert _no_page_scroll(page)
    assert session.errors == []
    page.context.close()


def test_keyboard_only_through_intake_and_adapt(browser: Browser, live_server: LiveServer) -> None:
    live_server.require_fake_ai()
    session = open_session(browser, live_server, DESKTOP)
    page = session.page
    page.goto(session.url + "/")

    _tab_to(page, "el => el.id === 'intake-text'")
    page.keyboard.type(EVENT)
    _tab_to(page, "el => el.textContent.trim().startsWith('Read my event')")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.activeElement.id === 'brief-heading'")
    _settled(page)

    _tab_to(page, "el => el.textContent.trim().startsWith('Make my plan')")
    page.keyboard.press("Enter")
    page.wait_for_url("**/plan")
    page.wait_for_selector("#plan-heading")

    _tab_to(page, "el => el.textContent.trim() === 'Something changed? Get fixes'")
    page.keyboard.press("Enter")
    _tab_to(page, "el => el.textContent.trim().startsWith('See what this changes')")
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.activeElement.id === 'options-heading'")
    _settled(page)

    _tab_to(page, "el => el.textContent.trim() === 'Use option 1'")
    with page.expect_response(lambda r: r.url.endswith("/api/adapt/apply")):
        page.keyboard.press("Enter")
    page.wait_for_function("() => document.activeElement.id === 'plan-heading'")
    assert page.evaluate(SAVED_TOTAL) < 2_500_000
    assert session.errors == []
    page.context.close()


def test_gemini_was_only_called_through_the_fake(live_server: LiveServer) -> None:
    live_server.require_fake_ai()
    assert live_server.models is not None
    assert set(live_server.models.calls) <= {"BriefDraft", "PlanDraft", "OptionsDraft"}


@pytest.mark.parametrize("viewport", [PHONE, DESKTOP], ids=["phone", "desktop"])
def test_sample_flow_without_ai(
    browser: Browser, live_server: LiveServer, viewport: dict[str, int]
) -> None:
    """Engine-only routes, so it also runs against the production link (BASE_URL)."""
    session = open_session(browser, live_server, viewport)
    page = session.page

    home = page.goto(session.url + "/")
    assert home is not None
    assert "script-src 'self'" in home.headers["content-security-policy"]
    page.get_by_role("button", name="Try the sample").click()
    page.wait_for_url("**/plan")
    page.wait_for_selector("#plan-heading")
    _settled(page)
    assert page.text_content("[data-save-status] >> nth=0") == "Saved in this browser."
    _assert_accessible(page, "sample dashboard")
    people = page.evaluate("() => JSON.parse(localStorage.getItem('toran.plan')).people.length")

    # What if
    page.focus("#wi-total")
    with page.expect_response(lambda r: r.url.endswith("/api/budget/whatif")):
        page.keyboard.press("ArrowLeft")
    _settled(page)

    # Who pays: add a person
    page.click("#add-person > summary")
    page.fill("#person-name", "Mama ji")
    page.fill("#person-pledge", "75000")
    with page.expect_response(lambda r: r.url.endswith("/api/people")):
        page.get_by_role("button", name="Add person").click()
    page.wait_for_function(
        f"() => JSON.parse(localStorage.getItem('toran.plan')).people.length === {people + 1}"
    )
    _settled(page)

    # Bookings: mark the first line paid at its planned cost plus 20,000
    page.click("#edit-bookings > summary")
    page.select_option("#booking-status", "paid")
    planned = page.evaluate(
        "() => JSON.parse(localStorage.getItem('toran.plan')).line_items[0].planned"
    )
    page.fill("#booking-actual", str(planned + 20_000))
    with page.expect_response(lambda r: r.url.endswith("/api/lines")):
        page.get_by_role("button", name="Save booking").click()
    _settled(page)
    assert "₹20,000 over the plan for this line." in page.inner_text("#budget")

    # Survives a reload
    page.reload()
    page.wait_for_selector("#plan-heading")
    saved = page.evaluate("() => JSON.parse(localStorage.getItem('toran.plan'))")
    assert saved["line_items"][0]["status"] == "paid"
    assert saved["people"][-1]["name"] == "Mama ji"

    assert _no_page_scroll(page)
    assert session.errors == []
    page.context.close()
