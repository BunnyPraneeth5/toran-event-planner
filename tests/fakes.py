"""Test doubles for Gemini. Tests only: app code must never import this module.

FakeModels stands in for google-genai's `client.aio.models`, so the real GeminiClient
logic (deadline, retry, parsing, error mapping) runs unchanged in tests.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.genai import errors, types

from app.ai.client import GeminiClient


@dataclass
class Delay:
    """A step that takes this long before answering (used to trigger timeouts)."""

    seconds: float
    then: Any = None


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeModels:
    """Plays back scripted steps: a response, an exception, a Delay, or a callable."""

    steps: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        step = self.steps.pop(0)
        if isinstance(step, Delay):
            await asyncio.sleep(step.seconds)
            step = step.then
        if callable(step) and not isinstance(step, types.GenerateContentResponse):
            step = step()
        if isinstance(step, BaseException):
            raise step
        assert isinstance(step, types.GenerateContentResponse)
        return step


def response(
    text: str,
    finish: types.FinishReason = types.FinishReason.STOP,
    prompt_tokens: int = 120,
    output_tokens: int = 80,
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)]),
                finish_reason=finish,
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens, candidates_token_count=output_tokens
        ),
    )


def blocked_prompt() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason.SAFETY
        )
    )


def no_candidates() -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[])


def api_error(code: int) -> errors.APIError:
    error_class = errors.ClientError if code < 500 else errors.ServerError
    return error_class(code, {"error": {"code": code, "message": "fake", "status": "FAKE"}})


def fake_client(
    *steps: Any,
    deadline_seconds: float = 25.0,
    fallback_model: str | None = None,
    min_retry_seconds: float = 3.0,
    clock: Callable[[], float] | None = None,
) -> tuple[GeminiClient, FakeModels]:
    models = FakeModels(list(steps))
    client = GeminiClient(
        models,
        deadline_seconds=deadline_seconds,
        fallback_model=fallback_model,
        min_retry_seconds=min_retry_seconds,
        clock=clock if clock is not None else FakeClock(),
    )
    return client, models
