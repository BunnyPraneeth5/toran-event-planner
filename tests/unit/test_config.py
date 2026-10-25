import logging

import pytest
from pydantic import ValidationError

from app.config import Settings

ENV_VARS = (
    "ENVIRONMENT",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_LITE_MODEL",
    "GEMINI_FALLBACK_MODELS",
    "AI_DEADLINE_SECONDS",
    "RATE_LIMIT_LLM",
    "MAX_BODY_BYTES",
    "AI_DAILY_CALL_LIMIT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.ai_configured is False
    assert settings.ai_deadline_seconds == 25.0
    assert settings.max_body_bytes == 262_144
    assert settings.is_production is False


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    monkeypatch.setenv("ENVIRONMENT", "production")

    settings = Settings(_env_file=None)

    assert settings.ai_configured is True
    assert settings.is_production is True


def test_blank_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "   ")

    assert Settings(_env_file=None).ai_configured is False


def test_secret_not_in_repr(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-123")
    settings = Settings(_env_file=None)

    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("settings: %s", settings)

    assert "test-key-123" not in repr(settings)
    assert "test-key-123" not in str(settings)
    assert "test-key-123" not in settings.model_dump_json()
    assert "test-key-123" not in caplog.text


def test_fallback_models_parsed_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).fallback_models == ("gemini-3.6-flash", "gemini-3.5-flash-lite")

    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "")
    assert Settings(_env_file=None).fallback_models == ()

    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "model-a")
    assert Settings(_env_file=None).fallback_models == ("model-a",)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AI_DEADLINE_SECONDS", "0"),
        ("AI_DEADLINE_SECONDS", "120"),
        ("MAX_BODY_BYTES", "10"),
        ("RATE_LIMIT_LLM", "lots"),
        ("ENVIRONMENT", "staging"),
        ("GEMINI_FALLBACK_MODELS", "model a, model b"),
    ],
)
def test_invalid_values_rejected(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
