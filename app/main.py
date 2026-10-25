"""Application factory."""

from fastapi import FastAPI

from app.api.adapt import router as adapt_router
from app.api.budget import router as budget_router
from app.api.health import router as health_router
from app.api.plan import router as plan_router
from app.config import get_settings


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
    for router in (health_router, plan_router, budget_router, adapt_router):
        app.include_router(router)
    return app


app = create_app()
