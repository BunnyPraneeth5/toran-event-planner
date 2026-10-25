import asyncio
import logging
from typing import Any

import httpx
import pytest
from google.genai import types
from pydantic import BaseModel, SecretStr

from app.ai.client import (
    BANNER_TEXT,
    AIError,
    AIErrorKind,
    GeminiClient,
    build_client,
    get_ai_client,
)
from app.config import Settings
from tests.fakes import (
    Delay,
    FakeClock,
    api_error,
    blocked_prompt,
    fake_client,
    no_candidates,
    response,
)

USER_TEXT = "Sister's wedding in Jodhpur, private detail 98765"
VALID = '{"answer": "ok", "count": 3}'
INVALID = '{"answer": "ok"}'


class Echo(BaseModel):
    answer: str
    count: int


def _call(client: GeminiClient) -> Echo:
    return asyncio.run(
        client.generate(
            endpoint="test",
            model="gemini-test",
            system_instruction="Return JSON.",
            prompt=USER_TEXT,
            schema=Echo,
            max_output_tokens=256,
        )
    )


def _error(client: GeminiClient) -> AIErrorKind:
    with pytest.raises(AIError) as caught:
        _call(client)
    return caught.value.kind


def test_success_returns_validated_model() -> None:
    client, models = fake_client(response(VALID))

    assert _call(client) == Echo(answer="ok", count=3)
    assert len(models.calls) == 1


def test_every_call_sets_instruction_schema_safety_and_token_cap() -> None:
    client, models = fake_client(response(VALID))

    _call(client)

    config: types.GenerateContentConfig = models.calls[0]["config"]
    assert config.system_instruction == "Return JSON."
    assert config.response_schema is Echo
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 256
    assert config.safety_settings is not None
    assert len(config.safety_settings) == 4
    assert models.calls[0]["model"] == "gemini-test"


def test_invalid_output_retried_once_then_succeeds() -> None:
    client, models = fake_client(response(INVALID), response(VALID))

    assert _call(client).count == 3
    assert len(models.calls) == 2


def test_invalid_output_twice_raises_invalid() -> None:
    client, models = fake_client(response(INVALID), response("not json"))

    assert _error(client) is AIErrorKind.INVALID
    assert len(models.calls) == 2


def test_no_retry_when_deadline_nearly_spent() -> None:
    clock = FakeClock()

    def slow_invalid() -> types.GenerateContentResponse:
        clock.advance(23.0)
        return response(INVALID)

    client, models = fake_client(slow_invalid, response(VALID), clock=clock)

    assert _error(client) is AIErrorKind.INVALID
    assert len(models.calls) == 1


def test_timeout_is_never_retried() -> None:
    client, models = fake_client(
        Delay(1.0, response(VALID)), response(VALID), deadline_seconds=0.05
    )

    assert _error(client) is AIErrorKind.TIMEOUT
    assert len(models.calls) == 1


@pytest.mark.parametrize(
    ("step", "kind"),
    [
        (api_error(429), AIErrorKind.RATE_LIMITED),
        (api_error(500), AIErrorKind.UNAVAILABLE),
        (api_error(503), AIErrorKind.UNAVAILABLE),
        (api_error(400), AIErrorKind.UNAVAILABLE),
        (httpx.ConnectError("no route"), AIErrorKind.UNAVAILABLE),
        (blocked_prompt(), AIErrorKind.BLOCKED),
        (no_candidates(), AIErrorKind.BLOCKED),
        (response(VALID, finish=types.FinishReason.SAFETY), AIErrorKind.BLOCKED),
        (response('{"answer": "o', finish=types.FinishReason.MAX_TOKENS), AIErrorKind.TRUNCATED),
    ],
)
def test_failures_map_to_ai_error(step: Any, kind: AIErrorKind) -> None:
    client, models = fake_client(step, response(VALID))

    assert _error(client) is kind
    assert len(models.calls) == 1


@pytest.mark.parametrize("code", [429, 503, 500])
def test_overloaded_model_falls_back_once(code: int) -> None:
    client, models = fake_client(api_error(code), response(VALID), fallback_model="backup")

    assert _call(client).count == 3
    assert [c["model"] for c in models.calls] == ["gemini-test", "backup"]


def test_fallback_model_failing_too_raises() -> None:
    client, models = fake_client(api_error(503), api_error(503), fallback_model="backup")

    assert _error(client) is AIErrorKind.UNAVAILABLE
    assert len(models.calls) == 2


def test_no_fallback_for_bad_requests() -> None:
    client, models = fake_client(api_error(400), response(VALID), fallback_model="backup")

    assert _error(client) is AIErrorKind.UNAVAILABLE
    assert len(models.calls) == 1


def test_no_fallback_when_deadline_nearly_spent() -> None:
    clock = FakeClock()

    def slow_overload() -> types.GenerateContentResponse:
        clock.advance(23.0)
        raise api_error(503)

    client, models = fake_client(
        slow_overload, response(VALID), fallback_model="backup", clock=clock
    )

    assert _error(client) is AIErrorKind.UNAVAILABLE
    assert len(models.calls) == 1


def test_fallback_then_invalid_still_gets_one_retry() -> None:
    client, models = fake_client(
        api_error(503), response(INVALID), response(VALID), fallback_model="backup"
    )

    assert _call(client).count == 3
    assert [c["model"] for c in models.calls] == ["gemini-test", "backup", "backup"]


def test_status_code_logged(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = fake_client(api_error(503))

    with caplog.at_level(logging.INFO, logger="toran.ai"):
        _error(client)

    assert "outcome=unavailable status=503" in caplog.text


def test_unexpected_finish_reason_counts_as_invalid_and_is_retried() -> None:
    other = types.FinishReason.OTHER
    client, models = fake_client(response(VALID, finish=other), response(VALID, finish=other))

    assert _error(client) is AIErrorKind.INVALID
    assert len(models.calls) == 2


def test_logs_carry_metrics_but_never_user_text(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = fake_client(response(INVALID), response(VALID, prompt_tokens=321))

    with caplog.at_level(logging.INFO, logger="toran.ai"):
        _call(client)

    messages = [r.getMessage() for r in caplog.records if r.name == "toran.ai"]
    assert len(messages) == 2
    assert "outcome=invalid" in messages[0]
    assert "outcome=ok" in messages[1]
    assert "input_tokens=321" in messages[1]
    assert "endpoint=test" in messages[1]
    for text in ("Jodhpur", "98765", "Sister", "answer"):
        assert text not in caplog.text


def test_every_error_kind_has_banner_copy() -> None:
    assert set(BANNER_TEXT) == set(AIErrorKind)
    for kind, text in BANNER_TEXT.items():
        assert "—" not in text
        assert AIError(kind).banner == text


def test_no_client_without_key() -> None:
    settings = Settings(_env_file=None, gemini_api_key=None)

    assert build_client(settings) is None
    assert get_ai_client(settings) is None
    assert build_client(settings.model_copy(update={"gemini_api_key": SecretStr("  ")})) is None


def test_client_built_with_key_without_network() -> None:
    settings = Settings(_env_file=None, gemini_api_key=SecretStr("test-key-not-real"))

    client = build_client(settings)

    assert isinstance(client, GeminiClient)
    assert build_client(settings) is client
