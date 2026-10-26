"""Shared pytest fixtures."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.security import limiter


@pytest.fixture
def settings() -> Settings:
    """Test settings that ignore .env and the real environment's key."""
    return Settings(_env_file=None, environment="test", gemini_api_key=None)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limits() -> Iterator[None]:
    """Rate limit counters are process-wide; start every test with a clean slate."""
    limiter.reset()
    yield
    limiter.reset()
