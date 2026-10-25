"""Budget what-if. Engine only, never the LLM."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import planner
from app.api.deps import ReferenceDep, TodayDep
from app.api.render import respond
from app.models.view import PlanResponse, WhatIfRequest

router = APIRouter(prefix="/api/budget", tags=["budget"])


@router.post("/whatif", response_model=PlanResponse)
def whatif(body: WhatIfRequest, request: Request, ref: ReferenceDep, today: TodayDep) -> Response:
    """Apply what-if changes; unlocked lines rebalance, locked lines never move."""
    try:
        view = planner.run_what_if(body, ref=ref, today=today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return respond(request, PlanResponse(view=view), "partials/plan.html")
