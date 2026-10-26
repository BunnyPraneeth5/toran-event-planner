import re
from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.ai.client import get_ai_client
from app.config import Settings, get_settings
from app.main import create_app
from app.security import CSP, GENERIC_ERROR, SECURITY_HEADERS, TOO_LARGE, TOO_MANY
from tests.factories import make_allocated_plan


@pytest.fixture
def app_client(settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_ai_client] = lambda: None
    boom = APIRouter()

    @boom.get("/boom")
    def explode() -> None:
        raise RuntimeError("secret internal detail")

    app.include_router(boom)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _assert_security_headers(response: object) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    for name, value in SECURITY_HEADERS.items():
        assert headers.get(name) == value, name
    assert re.fullmatch(r"[0-9a-f]{12}", headers["x-request-id"])


# headers


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/", None),
        ("GET", "/plan", None),
        ("GET", "/healthz", None),
        ("GET", "/static/js/app.js", None),
        ("GET", "/no-such-page", None),
        ("POST", "/api/plan/intake", {"text": "x"}),
        ("POST", "/api/plan/recompute", {"plan": "not a plan"}),
    ],
)
def test_every_response_carries_security_headers(
    app_client: TestClient, method: str, path: str, body: object
) -> None:
    response = app_client.request(method, path, json=body)

    _assert_security_headers(response)


def test_csp_is_strict() -> None:
    assert "script-src 'self'" in CSP
    assert "unsafe-inline" not in CSP
    assert "unsafe-eval" not in CSP
    assert "frame-ancestors 'none'" in CSP
    assert "style-src 'self' https://fonts.googleapis.com" in CSP
    assert "font-src https://fonts.gstatic.com" in CSP


def test_geolocation_allowed_only_for_this_site() -> None:
    assert "geolocation=(self)" in SECURITY_HEADERS["Permissions-Policy"]
    assert "camera=()" in SECURITY_HEADERS["Permissions-Policy"]


def test_request_ids_differ(app_client: TestClient) -> None:
    first = app_client.get("/healthz").headers["x-request-id"]
    second = app_client.get("/healthz").headers["x-request-id"]

    assert first != second


@pytest.mark.parametrize("path", ["/", "/plan"])
def test_pages_only_load_what_the_csp_allows(app_client: TestClient, path: str) -> None:
    html = app_client.get(path).text

    for src in re.findall(r'<script[^>]*src="([^"]+)"', html):
        assert src.startswith("/static/"), src
    for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"', html):
        assert href.startswith(("/static/", "https://fonts.googleapis.com/")), href
    assert "<style" not in html
    assert "style=" not in html
    assert re.search(r"<script(?![^>]*src=)", html) is None


# body size


def test_large_body_rejected_with_413(app_client: TestClient) -> None:
    response = app_client.post("/api/plan/intake", json={"text": "x" * 300_000})

    assert response.status_code == 413
    assert response.json() == {"detail": TOO_LARGE}
    _assert_security_headers(response)


def test_large_streamed_body_without_length_rejected(app_client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(40):
            yield b"x" * 10_000

    response = app_client.post(
        "/api/plan/recompute", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413


def test_normal_body_passes_through(app_client: TestClient) -> None:
    response = app_client.post(
        "/api/plan/recompute", json={"plan": make_allocated_plan().model_dump(mode="json")}
    )

    assert response.status_code == 200


# rate limits


def test_llm_routes_rate_limited_per_client_ip(app_client: TestClient) -> None:
    ip = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
    statuses = [
        app_client.post("/api/plan/intake", json={"text": "A wedding"}, headers=ip).status_code
        for _ in range(11)
    ]

    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429
    blocked = app_client.post("/api/plan/intake", json={"text": "A wedding"}, headers=ip)
    assert blocked.json() == {"detail": TOO_MANY}
    _assert_security_headers(blocked)

    other = {"x-forwarded-for": "198.51.100.4"}
    response = app_client.post("/api/plan/intake", json={"text": "A wedding"}, headers=other)
    assert response.status_code == 200


def test_engine_only_routes_are_not_rate_limited(app_client: TestClient) -> None:
    plan = {"plan": make_allocated_plan().model_dump(mode="json")}

    statuses = {app_client.post("/api/plan/recompute", json=plan).status_code for _ in range(15)}

    assert statuses == {200}


# compression and caching


def test_pages_are_gzipped(app_client: TestClient) -> None:
    response = app_client.get("/", headers={"Accept-Encoding": "gzip"})

    assert response.headers["content-encoding"] == "gzip"


def test_static_files_have_cache_headers(app_client: TestClient) -> None:
    assert app_client.get("/static/css/app.css").headers["cache-control"] == "public, max-age=300"


# errors


def test_unexpected_errors_are_generic_with_request_id(app_client: TestClient) -> None:
    response = app_client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == GENERIC_ERROR
    assert body["request_id"] == response.headers["x-request-id"]
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    _assert_security_headers(response)
