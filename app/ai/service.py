"""One function per AI feature. Each makes exactly one structured Gemini call."""

from collections.abc import Sequence

from app.ai.client import GeminiClient
from app.ai.prompts import INTAKE_SYSTEM, build_intake_prompt
from app.ai.schemas import BriefDraft
from app.models.intake import Answer

INTAKE_MAX_TOKENS = 2048


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
