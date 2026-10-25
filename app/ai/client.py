"""The single async wrapper around the Gemini API.

Every call sets a system instruction, a response schema, explicit safety settings and an
output token cap; runs under one overall deadline; retries once only when the reply does
not match the schema; maps every failure to an AIError; and logs one line per attempt
with no user text.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Protocol

import httpx
from fastapi import Depends
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.ai.limits import DailyCallCounter
from app.config import Settings, get_settings

logger = logging.getLogger("toran.ai")

MIN_RETRY_SECONDS = 3.0
"""A retry is only attempted if at least this much of the deadline is left."""

FALLBACK_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
"""Statuses where the backup model may succeed: overload, quota or a server error."""


class AIErrorKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    TRUNCATED = "truncated"
    INVALID = "invalid"
    DAILY_LIMIT = "daily_limit"


BANNER_TEXT: dict[AIErrorKind, str] = {
    AIErrorKind.TIMEOUT: "The AI took too long, so this uses rule-based defaults.",
    AIErrorKind.RATE_LIMITED: "The AI is busy right now. Please try again in a minute.",
    AIErrorKind.UNAVAILABLE: "The AI is unavailable, so this uses rule-based defaults.",
    AIErrorKind.BLOCKED: "The AI declined this request, so this uses rule-based defaults.",
    AIErrorKind.TRUNCATED: "The AI reply was cut short, so this uses rule-based defaults.",
    AIErrorKind.INVALID: "The AI reply could not be used, so this uses rule-based defaults.",
    AIErrorKind.DAILY_LIMIT: (
        "Today's AI limit has been reached, so this uses rule-based defaults. "
        "It resets at midnight IST."
    ),
}


class AIError(Exception):
    """A Gemini call that produced nothing usable. Carries no user text."""

    def __init__(self, kind: AIErrorKind) -> None:
        super().__init__(kind.value)
        self.kind = kind

    @property
    def banner(self) -> str:
        return BANNER_TEXT[self.kind]


class ContentGenerator(Protocol):
    """The slice of google-genai's `client.aio.models` this wrapper uses."""

    async def generate_content(
        self, *, model: str, contents: str, config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse: ...


SAFETY_SETTINGS = [
    types.SafetySetting(
        category=category, threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
    )
    for category in (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    )
]

BLOCKED_FINISH_REASONS = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.SPII,
        types.FinishReason.RECITATION,
    }
)


class GeminiClient:
    def __init__(
        self,
        models: ContentGenerator,
        *,
        deadline_seconds: float,
        fallback_model: str | None = None,
        min_retry_seconds: float = MIN_RETRY_SECONDS,
        daily_counter: DailyCallCounter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._models = models
        self._deadline = deadline_seconds
        self._fallback_model = fallback_model
        self._min_retry = min_retry_seconds
        self._daily_counter = daily_counter
        self._clock = clock

    async def generate[SchemaT: BaseModel](
        self,
        *,
        endpoint: str,
        model: str,
        system_instruction: str,
        prompt: str,
        schema: type[SchemaT],
        max_output_tokens: int,
    ) -> SchemaT:
        """One structured call. Returns a validated `schema` instance or raises AIError.

        Within one overall deadline: invalid output is retried once, and an overloaded,
        rate-limited or hung model is swapped once for the fallback model. While a fallback
        is available, the first model gets at most half the deadline so a hang leaves time
        to switch. The same model is never retried after a timeout.
        """
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            safety_settings=SAFETY_SETTINGS,
            max_output_tokens=max_output_tokens,
        )
        started = self._clock()
        attempt = 0
        retried_invalid = False
        while True:
            attempt += 1
            attempt_started = self._clock()
            response: types.GenerateContentResponse | None = None
            if self._daily_counter is not None and not self._daily_counter.try_acquire():
                kind = AIErrorKind.DAILY_LIMIT
                self._log(endpoint, model, attempt, attempt_started, kind, None)
                raise AIError(kind)
            budget = self._remaining(started)
            if self._fallback_for(model, started) is not None:
                budget = min(budget, self._deadline / 2)
            try:
                async with asyncio.timeout(budget):
                    response = await self._models.generate_content(
                        model=model, contents=prompt, config=config
                    )
                result = _parse(response, schema)
            except AIError as exc:
                self._log(endpoint, model, attempt, attempt_started, exc.kind, response)
                retry = (
                    exc.kind is AIErrorKind.INVALID
                    and not retried_invalid
                    and self._remaining(started) >= self._min_retry
                )
                if retry:
                    retried_invalid = True
                    continue
                raise
            except TimeoutError:
                self._log(endpoint, model, attempt, attempt_started, AIErrorKind.TIMEOUT, None)
                fallback = self._fallback_for(model, started)
                if fallback is not None:
                    model = fallback
                    continue
                raise AIError(AIErrorKind.TIMEOUT) from None
            except errors.APIError as exc:
                kind = AIErrorKind.RATE_LIMITED if exc.code == 429 else AIErrorKind.UNAVAILABLE
                outcome = f"{kind} status={exc.code}"
                self._log(endpoint, model, attempt, attempt_started, outcome, None)
                fallback = self._fallback_for(model, started)
                if fallback is not None and exc.code in FALLBACK_STATUS_CODES:
                    model = fallback
                    continue
                raise AIError(kind) from None
            except (httpx.HTTPError, OSError):
                kind = AIErrorKind.UNAVAILABLE
                self._log(endpoint, model, attempt, attempt_started, kind, None)
                raise AIError(kind) from None
            self._log(endpoint, model, attempt, attempt_started, "ok", response)
            return result

    def _remaining(self, started: float) -> float:
        return self._deadline - (self._clock() - started)

    def _fallback_for(self, model: str, started: float) -> str | None:
        """The fallback model, if it differs from `model` and enough time is left for it."""
        fallback = self._fallback_model
        if fallback is None or fallback == model or self._remaining(started) < self._min_retry:
            return None
        return fallback

    def _log(
        self,
        endpoint: str,
        model: str,
        attempt: int,
        attempt_started: float,
        outcome: str,
        response: types.GenerateContentResponse | None,
    ) -> None:
        usage = response.usage_metadata if response is not None else None
        logger.info(
            "ai_call endpoint=%s model=%s attempt=%d latency_ms=%d "
            "input_tokens=%s output_tokens=%s outcome=%s",
            endpoint,
            model,
            attempt,
            int((self._clock() - attempt_started) * 1000),
            usage.prompt_token_count if usage else None,
            usage.candidates_token_count if usage else None,
            outcome,
        )


def _parse[SchemaT: BaseModel](
    response: types.GenerateContentResponse, schema: type[SchemaT]
) -> SchemaT:
    """Check why generation stopped before trusting the text, then validate it."""
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise AIError(AIErrorKind.BLOCKED)
    if not response.candidates:
        raise AIError(AIErrorKind.BLOCKED)
    reason = response.candidates[0].finish_reason
    if reason == types.FinishReason.MAX_TOKENS:
        raise AIError(AIErrorKind.TRUNCATED)
    if reason in BLOCKED_FINISH_REASONS:
        raise AIError(AIErrorKind.BLOCKED)
    if reason not in (None, types.FinishReason.STOP):
        raise AIError(AIErrorKind.INVALID)
    text = response.text
    if not text:
        raise AIError(AIErrorKind.INVALID)
    try:
        return schema.model_validate_json(text)
    except ValidationError:
        raise AIError(AIErrorKind.INVALID) from None


def build_client(settings: Settings) -> GeminiClient | None:
    """A client when a key is configured, otherwise None (callers use fallbacks)."""
    if settings.gemini_api_key is None or not settings.ai_configured:
        return None
    return _cached_client(
        settings.gemini_api_key.get_secret_value(),
        settings.ai_deadline_seconds,
        settings.gemini_fallback_model,
        settings.ai_daily_call_limit,
    )


@lru_cache(maxsize=2)
def _cached_client(
    api_key: str, deadline_seconds: float, fallback_model: str | None, daily_limit: int
) -> GeminiClient:
    """One client per configuration, so the daily counter is shared by every request."""
    return GeminiClient(
        _sdk_client(api_key, int(deadline_seconds * 1000)).aio.models,
        deadline_seconds=deadline_seconds,
        fallback_model=fallback_model,
        daily_counter=DailyCallCounter(daily_limit),
    )


@lru_cache(maxsize=2)
def _sdk_client(api_key: str, timeout_ms: int) -> genai.Client:
    """Cached so the SDK client stays alive: when it is garbage collected it closes
    the HTTP connection that its `aio.models` still uses. SDK retries are off so the
    overall deadline and the fallback model stay under this module's control."""
    http_options = types.HttpOptions(
        timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)
    )
    return genai.Client(api_key=api_key, http_options=http_options)


def get_ai_client(settings: Annotated[Settings, Depends(get_settings)]) -> GeminiClient | None:
    """FastAPI dependency. Tests override it with a client built on tests/fakes.py."""
    return build_client(settings)
