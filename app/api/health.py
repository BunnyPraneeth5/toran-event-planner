"""Health check, also used to confirm which commit is deployed."""

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])

COMMIT = re.compile(r"[0-9a-f]{7,40}")


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    ai_configured: bool
    commit: str | None = None
    """Short git commit of this deployment (from Vercel), or None when running locally."""


@router.get("/healthz")
def healthz(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    """Liveness probe. Reports whether Gemini is configured, never the key itself."""
    sha = settings.vercel_git_commit_sha or ""
    commit = sha[:7] if COMMIT.fullmatch(sha) else None
    return Health(ai_configured=settings.ai_configured, commit=commit)
