"""End-to-end fixtures: the real app served in-process, a fake Gemini, and a real browser.

The app runs under uvicorn in a background thread. Only the Gemini client and today's date
are swapped, through FastAPI dependency overrides, so every engine, template, script and
security header is the real one.

Browser: Playwright's own Chromium by default (CI installs it). Set E2E_BROWSER_CHANNEL to
"chrome" or "msedge" to use a browser that is already installed instead.
"""

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from google.genai import types
from playwright.sync_api import Browser, Page, sync_playwright

from app.ai.client import GeminiClient, get_ai_client
from app.ai.schemas import BriefDraft, OptionsDraft, PlanDraft
from app.api.deps import get_today
from app.config import get_settings
from app.main import create_app
from app.security import limiter

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "ai"
AXE = Path(__file__).with_name("axe.min.js")
TODAY = date(2026, 6, 1)
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 900}

# A budget-cut fix that names a category, not ids, so it fits any generated plan.
ADAPT_RESPONSE = {
    "options": [
        {
            "rationale": "Simplify the decor and keep every function.",
            "ops": [
                {
                    "op": "scale_category",
                    "function_id": None,
                    "tier": None,
                    "guests": None,
                    "category": "decor",
                    "percent": -40,
                    "line_item_id": None,
                }
            ],
        }
    ]
}


def _fixture_response(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["response"]


def _response(payload: Any) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=json.dumps(payload))]),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


@dataclass
class RoutedModels:
    """Answers by the schema asked for, so the flow can call Gemini in any order."""

    calls: list[str] = field(default_factory=list)

    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        schema = config.response_schema
        self.calls.append(getattr(schema, "__name__", str(schema)))
        if schema is BriefDraft:
            return _response(_fixture_response("intake_valid"))
        if schema is PlanDraft:
            return _response(_fixture_response("generate_valid"))
        if schema is OptionsDraft:
            return _response(ADAPT_RESPONSE)
        raise AssertionError(f"unexpected schema {schema}")


@dataclass
class LiveServer:
    url: str
    models: RoutedModels


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def live_server() -> Iterator[LiveServer]:
    # Security middleware reads settings directly, so the e2e limits go in the environment.
    os.environ["ENVIRONMENT"] = "test"
    os.environ["RATE_LIMIT_LLM"] = "1000/minute"
    get_settings.cache_clear()
    limiter.reset()

    models = RoutedModels()
    ai = GeminiClient(models, deadline_seconds=25.0)
    app = create_app()
    app.dependency_overrides[get_ai_client] = lambda: ai
    app.dependency_overrides[get_today] = lambda: TODAY

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("the e2e server did not start")
        time.sleep(0.05)
    yield LiveServer(url=f"http://127.0.0.1:{port}", models=models)
    server.should_exit = True
    thread.join(timeout=5)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    channel = os.environ.get("E2E_BROWSER_CHANNEL") or None
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(channel=channel)
        yield launched
        launched.close()


@dataclass
class Session:
    page: Page
    url: str
    errors: list[str]


def open_session(browser: Browser, server: LiveServer, viewport: dict[str, int]) -> Session:
    """A fresh browser context (empty localStorage) that records console and page errors."""
    context = browser.new_context(viewport=viewport, accept_downloads=True)
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_default_timeout(10_000)
    return Session(page=page, url=server.url, errors=errors)


def serious_axe_violations(page: Page) -> list[dict[str, Any]]:
    """Runs axe-core in the page and returns serious or critical violations only.

    `preload: false` stops axe fetching the Google Fonts stylesheet itself, which the
    page's CSP (connect-src 'self') rightly blocks.
    """
    if not page.evaluate("() => typeof window.axe !== 'undefined'"):
        page.evaluate(AXE.read_text(encoding="utf-8"))
    violations: list[dict[str, Any]] = page.evaluate(
        """async () => {
            const options = {resultTypes: ["violations"], preload: false};
            const result = await axe.run(document, options);
            return result.violations.map(v => ({
                id: v.id, impact: v.impact, nodes: v.nodes.map(n => n.target.join(" ")),
            }));
        }"""
    )
    return [v for v in violations if v["impact"] in {"serious", "critical"}]
