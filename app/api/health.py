"""Health check used by Render and by the keep-warm ping."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    ai_configured: bool


@router.get("/healthz")
def healthz(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    """Liveness probe. Reports whether Gemini is configured, never the key itself."""
    return Health(ai_configured=settings.ai_configured)
