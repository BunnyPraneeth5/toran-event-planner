"""Application settings, read from the environment (and .env in development)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Each field maps to the upper-case env var of the same name."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1, max_length=80)
    gemini_lite_model: str = Field(default="gemini-3.5-flash-lite", min_length=1, max_length=80)
    gemini_fallback_model: str | None = Field(
        default="gemini-3.5-flash", min_length=1, max_length=80
    )
    ai_deadline_seconds: float = Field(default=25.0, gt=0, le=60)
    rate_limit_llm: str = Field(default="10/minute", pattern=r"^\d{1,4}/(second|minute|hour|day)$")
    max_body_bytes: int = Field(default=262_144, ge=1_024, le=2_097_152)

    @property
    def ai_configured(self) -> bool:
        """True when a non-blank Gemini key is present. Without one, fallbacks are used."""
        if self.gemini_api_key is None:
            return False
        return bool(self.gemini_api_key.get_secret_value().strip())

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings singleton. Used as a FastAPI dependency so tests can override it."""
    return Settings()
