"""Application factory."""

from pathlib import Path

from fastapi import FastAPI

from app.api.adapt import router as adapt_router
from app.api.budget import router as budget_router
from app.api.calendar import router as calendar_router
from app.api.health import router as health_router
from app.api.pages import router as pages_router
from app.api.plan import router as plan_router
from app.config import get_settings
from app.security import CachedStaticFiles, install

STATIC_DIR = Path(__file__).parent / "web" / "static"


def create_app() -> FastAPI:
    """Build the FastAPI app with all routers attached. API docs are off in production."""
    settings = get_settings()
    show_docs = not settings.is_production
    app = FastAPI(
        title="Toran",
        version="0.1.0",
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    routers = (
        pages_router,
        health_router,
        plan_router,
        budget_router,
        adapt_router,
        calendar_router,
    )
    for router in routers:
        app.include_router(router)
    app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")
    install(app)
    return app


app = create_app()
