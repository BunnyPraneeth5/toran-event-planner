"""Calendar export. Engine only, never the LLM."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.clock import now_utc
from app.engines.calendar import plan_to_ics
from app.models.view import PlanRequest

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.post("/ics", response_class=Response)
def ics(body: PlanRequest) -> Response:
    """The plan as an .ics file: tasks as all-day events, functions at their times."""
    return Response(
        content=plan_to_ics(body.plan, stamp=now_utc()),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="toran-plan.ics"'},
    )
