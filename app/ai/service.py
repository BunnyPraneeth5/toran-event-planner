"""One function per AI feature. Each makes exactly one structured Gemini call."""

from collections.abc import Sequence

from app.ai.client import GeminiClient
from app.ai.prompts import (
    GENERATE_SYSTEM,
    INTAKE_SYSTEM,
    build_generate_prompt,
    build_intake_prompt,
)
from app.ai.schemas import BriefDraft, PlanDraft
from app.data.loader import CategoryInfo, FunctionTemplate
from app.models.generate import CompleteBrief
from app.models.intake import Answer

INTAKE_MAX_TOKENS = 2048

GENERATE_MAX_TOKENS = 8192
"""Room for the largest plan the planner accepts (12 functions, every category, two ideas
per function, roughly 2,500 tokens of JSON) plus the model's thinking tokens, which count
against this limit on thinking models."""


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
