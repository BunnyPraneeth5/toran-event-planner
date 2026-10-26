"""Full HTML pages. Partials for HTMX come from the API routes themselves."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.api.render import TEMPLATES

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    """The intake page: one text box, then the brief form, then the plan."""
    return TEMPLATES.TemplateResponse(request, "intake.html")


@router.get("/plan", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    """The saved plan. The page is empty until the browser sends the plan it has stored."""
    return TEMPLATES.TemplateResponse(request, "dashboard.html")
