"""Bookings and actual costs. Engine only, never the LLM."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import planner
from app.api.deps import ReferenceDep, TodayDep
from app.api.render import respond
from app.models.lines import LineRequest
from app.models.view import PlanResponse

router = APIRouter(prefix="/api", tags=["lines"])


@router.post("/lines", response_model=PlanResponse)
def lines(body: LineRequest, request: Request, ref: ReferenceDep, today: TodayDep) -> Response:
    """Mark a line planned, booked or paid; booked lines lock and their task is done."""
    try:
        plan = planner.update_line(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    view = planner.recompute(plan, ref=ref, today=today)
    return respond(request, PlanResponse(view=view), "partials/plan.html")
