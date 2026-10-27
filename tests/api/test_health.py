import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings, get_settings
from app.main import create_app


def test_healthz_ok(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_healthz_reports_ai_configured(client: TestClient, settings: Settings) -> None:
    assert client.get("/healthz").json()["ai_configured"] is False

    app = create_app()
    keyed = settings.model_copy(update={"gemini_api_key": SecretStr("test-key-abc")})
    app.dependency_overrides[get_settings] = lambda: keyed
    with TestClient(app) as keyed_client:
        body = keyed_client.get("/healthz").json()

    assert body["ai_configured"] is True
    assert "test-key-abc" not in str(body)


def test_docs_hidden_on_vercel_production(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = settings.model_copy(update={"vercel_env": "production"})
    monkeypatch.setattr("app.main.get_settings", lambda: production)

    with TestClient(create_app()) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_healthz_reports_the_deployed_commit(settings: Settings) -> None:
    sha = "22e6102b0c4f3e1a9d8c7b6a5f4e3d2c1b0a9f8e"
    app = create_app()
    deployed = settings.model_copy(update={"vercel_git_commit_sha": sha})
    app.dependency_overrides[get_settings] = lambda: deployed
    with TestClient(app) as deployed_client:
        assert deployed_client.get("/healthz").json()["commit"] == "22e6102"


def test_healthz_commit_is_none_locally(client: TestClient) -> None:
    assert client.get("/healthz").json()["commit"] is None


@pytest.mark.parametrize("value", ["", "not-a-sha", "<script>", "ABCDEF1234567"])
def test_healthz_ignores_an_unexpected_commit_value(settings: Settings, value: str) -> None:
    app = create_app()
    odd = settings.model_copy(update={"vercel_git_commit_sha": value})
    app.dependency_overrides[get_settings] = lambda: odd
    with TestClient(app) as odd_client:
        response = odd_client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["commit"] is None
