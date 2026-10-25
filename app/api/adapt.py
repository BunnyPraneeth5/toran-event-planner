"""Something changed: options to fix it, and applying the chosen one."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app import planner
from app.api.deps import AIDep, ReferenceDep, SettingsDep, TodayDep
from app.api.render import respond
from app.models.adapt import AdaptRequest, AdaptResult, ApplyRequest
from app.models.view import PlanResponse

router = APIRouter(prefix="/api/adapt", tags=["adapt"])


@router.post("/options", response_model=AdaptResult)
async def options(
    body: AdaptRequest,
    request: Request,
    ai: AIDep,
    settings: SettingsDep,
    ref: ReferenceDep,
    today: TodayDep,
) -> Response:
    """The change's impact and up to three fixes, each verified by the engines."""
    try:
        result = await planner.adapt_options(
            body, ai, model=settings.gemini_model, ref=ref, today=today
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return respond(request, result, "partials/options.html")


@router.post("/apply", response_model=PlanResponse)
def apply(body: ApplyRequest, request: Request, ref: ReferenceDep, today: TodayDep) -> Response:
    """Re-apply the change and the chosen option on the server and re-verify them.

    The request carries the original plan, never a result computed by the client.
    """
    try:
        plan = planner.apply_option(body, ref=ref, today=today)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    view = planner.recompute(plan, ref=ref, today=today)
    return respond(request, PlanResponse(view=view), "partials/plan.html")
