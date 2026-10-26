"""One response helper for every route: JSON by default, an HTML partial for HTMX.

Both come from the same validated model, so the two never disagree.
"""

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.web.formatting import format_date, format_datetime, format_inr, format_short
from app.web.links import google_calendar_url

TEMPLATES = Jinja2Templates(directory=Path(__file__).parents[1] / "web" / "templates")
TEMPLATES.env.filters["inr"] = format_inr
TEMPLATES.env.filters["short_inr"] = format_short
TEMPLATES.env.filters["nice_date"] = format_date
TEMPLATES.env.filters["nice_datetime"] = format_datetime
TEMPLATES.env.globals["google_calendar_url"] = google_calendar_url


def wants_html(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def respond(request: Request, data: BaseModel, template: str, **context: Any) -> Response:
    """`data` as JSON, or rendered into `template` when the request comes from HTMX."""
    if wants_html(request):
        return TEMPLATES.TemplateResponse(request, template, {"data": data, **context})
    return JSONResponse(data.model_dump(mode="json"))
