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

from app.config import Settings, get_settings

logger = logging.getLogger("toran.ai")

MIN_RETRY_SECONDS = 3.0
"""A retry is only attempted if at least this much of the deadline is left."""


class AIErrorKind(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    TRUNCATED = "truncated"
    INVALID = "invalid"


BANNER_TEXT: dict[AIErrorKind, str] = {
    AIErrorKind.TIMEOUT: "The AI took too long, so this uses rule-based defaults.",
    AIErrorKind.RATE_LIMITED: "The AI is busy right now. Please try again in a minute.",
    AIErrorKind.UNAVAILABLE: "The AI is unavailable, so this uses rule-based defaults.",
    AIErrorKind.BLOCKED: "The AI declined this request, so this uses rule-based defaults.",
    AIErrorKind.TRUNCATED: "The AI reply was cut short, so this uses rule-based defaults.",
    AIErrorKind.INVALID: "The AI reply could not be used, so this uses rule-based defaults.",
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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._models = models
        self._deadline = deadline_seconds
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
        """One structured call. Returns a validated `schema` instance or raises AIError."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            safety_settings=SAFETY_SETTINGS,
            max_output_tokens=max_output_tokens,
        )
        started = self._clock()
        attempt = 0
        while True:
            attempt += 1
            attempt_started = self._clock()
            response: types.GenerateContentResponse | None = None
            try:
                async with asyncio.timeout(self._remaining(started)):
                    response = await self._models.generate_content(
                        model=model, contents=prompt, config=config
                    )
                result = _parse(response, schema)
            except AIError as exc:
                self._log(endpoint, model, attempt, attempt_started, exc.kind, response)
                retry = (
                    exc.kind is AIErrorKind.INVALID
                    and attempt == 1
                    and self._remaining(started) >= MIN_RETRY_SECONDS
                )
                if retry:
                    continue
                raise
            except TimeoutError:
                self._log(endpoint, model, attempt, attempt_started, AIErrorKind.TIMEOUT, None)
                raise AIError(AIErrorKind.TIMEOUT) from None
            except errors.APIError as exc:
                kind = AIErrorKind.RATE_LIMITED if exc.code == 429 else AIErrorKind.UNAVAILABLE
                self._log(endpoint, model, attempt, attempt_started, kind, None)
                raise AIError(kind) from None
            except (httpx.HTTPError, OSError):
                kind = AIErrorKind.UNAVAILABLE
                self._log(endpoint, model, attempt, attempt_started, kind, None)
                raise AIError(kind) from None
            self._log(endpoint, model, attempt, attempt_started, "ok", response)
            return result

    def _remaining(self, started: float) -> float:
        return self._deadline - (self._clock() - started)

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
    return _cached_client(settings.gemini_api_key.get_secret_value(), settings.ai_deadline_seconds)


@lru_cache(maxsize=2)
def _cached_client(api_key: str, deadline_seconds: float) -> GeminiClient:
    http_options = types.HttpOptions(timeout=int(deadline_seconds * 1000))
    sdk = genai.Client(api_key=api_key, http_options=http_options)
    return GeminiClient(sdk.aio.models, deadline_seconds=deadline_seconds)


def get_ai_client(settings: Annotated[Settings, Depends(get_settings)]) -> GeminiClient | None:
    """FastAPI dependency. Tests override it with a client built on tests/fakes.py."""
    return build_client(settings)
