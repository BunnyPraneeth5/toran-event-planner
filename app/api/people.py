"""People and payers. Engine only, never the LLM."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import planner
from app.api.deps import ReferenceDep, TodayDep
from app.api.render import respond
from app.models.people import PeopleRequest
from app.models.view import PlanResponse

router = APIRouter(prefix="/api", tags=["people"])


@router.post("/people", response_model=PlanResponse)
def people(body: PeopleRequest, request: Request, ref: ReferenceDep, today: TodayDep) -> Response:
    """Add, change or remove a person, or set who pays for a line."""
    try:
        plan, notices = planner.change_people(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    view = planner.recompute(plan, ref=ref, today=today)
    return respond(request, PlanResponse(view=view, notices=notices), "partials/plan.html")
