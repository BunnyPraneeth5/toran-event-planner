import asyncio
import json
from datetime import date, timedelta

import pytest
from pydantic import BaseModel, SecretStr

from app.ai.client import BANNER_TEXT, AIError, AIErrorKind, GeminiClient, build_client
from app.ai.limits import DailyCallCounter
from app.clock import today_ist
from app.config import Settings
from app.models.intake import IntakeRequest
from app.planner import intake
from tests.fakes import api_error, fake_client, response

DAY = date(2026, 10, 25)
VALID = '{"answer": "ok", "count": 3}'


class Echo(BaseModel):
    answer: str
    count: int


class Today:
    def __init__(self) -> None:
        self.value = DAY

    def __call__(self) -> date:
        return self.value


def _call(client: GeminiClient) -> Echo:
    return asyncio.run(
        client.generate(
            endpoint="test",
            model="gemini-test",
            system_instruction="Return JSON.",
            prompt="hello",
            schema=Echo,
            max_output_tokens=64,
        )
    )


def test_counter_allows_up_to_limit_then_stops() -> None:
    counter = DailyCallCounter(2, today=Today())

    assert [counter.try_acquire() for _ in range(3)] == [True, True, False]
    assert counter.used_today == 2


def test_counter_resets_on_a_new_ist_day() -> None:
    today = Today()
    counter = DailyCallCounter(1, today=today)
    counter.try_acquire()

    today.value = DAY + timedelta(days=1)

    assert counter.used_today == 0
    assert counter.try_acquire() is True


def test_limit_zero_allows_nothing() -> None:
    assert DailyCallCounter(0, today=Today()).try_acquire() is False


def test_client_stops_calling_gemini_at_the_limit() -> None:
    counter = DailyCallCounter(1, today=Today())
    client, models = fake_client(response(VALID), response(VALID), daily_counter=counter)

    assert _call(client).count == 3
    with pytest.raises(AIError) as caught:
        _call(client)

    assert caught.value.kind is AIErrorKind.DAILY_LIMIT
    assert len(models.calls) == 1


def test_retries_and_fallbacks_count_against_the_limit() -> None:
    counter = DailyCallCounter(1, today=Today())
    client, models = fake_client(
        api_error(503), response(VALID), fallback_model="backup", daily_counter=counter
    )

    with pytest.raises(AIError) as caught:
        _call(client)

    assert caught.value.kind is AIErrorKind.DAILY_LIMIT
    assert len(models.calls) == 1


def test_intake_shows_daily_limit_banner() -> None:
    counter = DailyCallCounter(0, today=Today())
    client, models = fake_client(response(json.dumps({})), daily_counter=counter)

    result = asyncio.run(
        intake(IntakeRequest(text="Wedding in Jaipur"), client, model="m", today=DAY)
    )

    assert result.source == "fallback"
    assert result.banner == BANNER_TEXT[AIErrorKind.DAILY_LIMIT]
    assert "resets at midnight IST" in (result.banner or "")
    assert models.calls == []


def test_build_client_applies_configured_limit_without_network() -> None:
    settings = Settings(
        _env_file=None, gemini_api_key=SecretStr("test-key-limit"), ai_daily_call_limit=0
    )
    client = build_client(settings)
    assert client is not None

    with pytest.raises(AIError) as caught:
        _call(client)

    assert caught.value.kind is AIErrorKind.DAILY_LIMIT


def test_setting_defaults_and_bounds() -> None:
    assert Settings(_env_file=None).ai_daily_call_limit == 500
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        Settings(_env_file=None, ai_daily_call_limit=-1)


def test_today_ist_is_a_date() -> None:
    assert isinstance(today_ist(), date)
