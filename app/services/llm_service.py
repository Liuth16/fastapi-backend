import json
from typing import List
from pydantic import BaseModel, Field
from google import genai
from app.config import settings  # Use centralized config

# Initialize Gemini client using settings
_client = genai.Client(api_key=settings.gemini_api_key)

# Choose the model (make it configurable if you want later)
_MODEL = "gemini-2.5-flash"


class LLMActionOutcome(BaseModel):
    narrative: str
    enemy_health_change: int = 0
    character_health_change: int = 0
    status_effects: List[str] = Field(default_factory=list)


PROMPT_TEMPLATE = """You are the game narrator for a text-based RPG.

Player action: "{action}"
Outcome decided by game engine: {outcome}  # do NOT override this outcome

Game state:
- Character: {character_name}
- Enemy: {enemy_name} (health: {enemy_health})
- Level: {level_number}

Previous turns (most recent first):
{previous}

Instructions:
- Write a short, vivid narrative (1-3 sentences) describing the outcome consistent with {outcome}.
- Do not mention dice rolls, random numbers, or the word "success"/"failure" explicitly.
- Update health deltas accordingly (negative means damage taken, positive means healing).
- Return only JSON that matches the provided schema.
"""


def _format_previous(previous_turns: List[str]) -> str:
    if not previous_turns:
        return "- (no prior turns)"
    return "\n".join(f"- {p}" for p in previous_turns[::-1])


async def generate_narrative_with_schema(
    *,
    action: str,
    outcome_success: bool,
    character_name: str,
    enemy_name: str,
    enemy_health: int,
    level_number: int,
    previous_turns: List[str],
) -> LLMActionOutcome:
    """
    Calls Gemini with a response schema so it returns strict JSON.
    Falls back gracefully if parsing fails.
    """
    outcome = "SUCCESS" if outcome_success else "FAILURE"

    contents = PROMPT_TEMPLATE.format(
        action=action,
        outcome=outcome,
        character_name=character_name,
        enemy_name=enemy_name,
        enemy_health=enemy_health,
        level_number=level_number,
        previous=_format_previous(previous_turns),
    )

    resp = _client.models.generate_content(
        model=_MODEL,
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": LLMActionOutcome,
        },
    )

    # Prefer structured parse
    if getattr(resp, "parsed", None):
        return resp.parsed

    # Fallback: try manual parse
    try:
        data = json.loads(resp.text)
        return LLMActionOutcome(**data)
    except Exception:
        return LLMActionOutcome(
            narrative="You act, but the dust hasn’t settled enough to tell what happened.",
            enemy_health_change=0,
            character_health_change=0,
            status_effects=[],
        )
