"""Health check used by Render and by the keep-warm ping."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/healthz")
def healthz() -> Health:
    """Liveness probe."""
    return Health()
