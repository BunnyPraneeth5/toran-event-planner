"""One function per AI feature. Each makes exactly one structured Gemini call."""

from collections.abc import Sequence

from app.ai.client import GeminiClient
from app.ai.prompts import (
    ADAPT_SYSTEM,
    GENERATE_SYSTEM,
    INTAKE_SYSTEM,
    build_adapt_prompt,
    build_generate_prompt,
    build_intake_prompt,
)
from app.ai.schemas import BriefDraft, OptionsDraft, PlanDraft
from app.data.loader import CategoryInfo, FunctionTemplate
from app.models.change import Change, Impact
from app.models.generate import CompleteBrief
from app.models.intake import Answer
from app.models.plan import Plan

INTAKE_MAX_TOKENS = 2048

GENERATE_MAX_TOKENS = 8192
"""Room for the largest plan the planner accepts (12 functions, every category, two ideas
per function, roughly 2,500 tokens of JSON) plus the model's thinking tokens, which count
against this limit on thinking models."""

ADAPT_MAX_TOKENS = 4096
"""Three options of up to five ops each is a few hundred tokens; the rest is thinking room."""


async def extract_brief(
    client: GeminiClient, *, model: str, text: str, answers: Sequence[Answer]
) -> BriefDraft:
    """Raw brief from free text. Values are as written; the planner converts them."""
    return await client.generate(
        endpoint="intake",
        model=model,
        system_instruction=INTAKE_SYSTEM,
        prompt=build_intake_prompt(text, answers),
        schema=BriefDraft,
        max_output_tokens=INTAKE_MAX_TOKENS,
    )


async def propose_plan(
    client: GeminiClient,
    *,
    model: str,
    brief: CompleteBrief,
    template: FunctionTemplate,
    categories: Sequence[CategoryInfo],
) -> PlanDraft:
    """Functions, category weights and ideas for a brief. No money, no dates."""
    return await client.generate(
        endpoint="generate",
        model=model,
        system_instruction=GENERATE_SYSTEM,
        prompt=build_generate_prompt(brief, template, categories),
        schema=PlanDraft,
        max_output_tokens=GENERATE_MAX_TOKENS,
    )


async def propose_options(
    client: GeminiClient,
    *,
    model: str,
    plan: Plan,
    change: Change,
    impact: Impact,
    flagged_titles: list[str],
) -> OptionsDraft:
    """Two or three candidate fixes as ops. The adapt engine verifies every one."""
    return await client.generate(
        endpoint="adapt",
        model=model,
        system_instruction=ADAPT_SYSTEM,
        prompt=build_adapt_prompt(plan, change, impact, flagged_titles),
        schema=OptionsDraft,
        max_output_tokens=ADAPT_MAX_TOKENS,
    )
