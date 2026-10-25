"""Intake, generate and recompute."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import planner
from app.api.deps import AIDep, ReferenceDep, SettingsDep, TodayDep
from app.api.render import respond
from app.models.generate import GenerateRequest
from app.models.intake import IntakeRequest, IntakeResult
from app.models.view import PlanRequest, PlanResponse

router = APIRouter(prefix="/api/plan", tags=["plan"])


@router.post("/intake", response_model=IntakeResult)
async def intake(
    body: IntakeRequest, request: Request, ai: AIDep, settings: SettingsDep, today: TodayDep
) -> Response:
    """Free text to a brief, with questions for whatever is missing. Uses the lite model."""
    result = await planner.intake(body, ai, model=settings.gemini_lite_model, today=today)
    return respond(request, result, "partials/brief.html")


@router.post("/generate", response_model=PlanResponse)
async def generate(
    body: GenerateRequest,
    request: Request,
    ai: AIDep,
    settings: SettingsDep,
    ref: ReferenceDep,
    today: TodayDep,
) -> Response:
    """A complete brief to a full plan, with every derived view."""
    result = await planner.generate(body, ai, model=settings.gemini_model, ref=ref, today=today)
    view = planner.recompute(result.plan, ref=ref, today=today)
    response = PlanResponse(view=view, notices=result.notices, banner=result.banner)
    return respond(request, response, "partials/plan.html")


@router.post("/recompute", response_model=PlanResponse)
def recompute(body: PlanRequest, request: Request, ref: ReferenceDep, today: TodayDep) -> Response:
    """Fresh budget, timeline and ledger views for a plan. Also validates imported plans."""
    view = planner.recompute(body.plan, ref=ref, today=today)
    return respond(request, PlanResponse(view=view), "partials/plan.html")
