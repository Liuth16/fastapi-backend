import json
from typing import List
from pydantic import BaseModel, Field
from google import genai
from google.genai import errors as genai_errors
from app.config import settings  # Use centralized config
import logging

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
- Enemy description: {enemy_description}
- Level: {level_number}
- Campaign intro: {intro_narrative}

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
    enemy_description: str,     # NEW
    enemy_health: int,
    level_number: int,
    intro_narrative: str,       # NEW
    previous_turns: List[str],
) -> LLMActionOutcome:
    outcome = "SUCCESS" if outcome_success else "FAILURE"

    contents = PROMPT_TEMPLATE.format(
        action=action,
        outcome=outcome,
        character_name=character_name,
        enemy_name=enemy_name,
        enemy_description=enemy_description,
        enemy_health=enemy_health,
        level_number=level_number,
        intro_narrative=intro_narrative,
        previous=_format_previous(previous_turns),
    )

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMActionOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            return resp.parsed

        data = json.loads(resp.text)
        return LLMActionOutcome(**data)

    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        # Provide a graceful fallback narrative
        return LLMActionOutcome(
            narrative="The battle is chaotic, and the outcome is unclear for now.",
            enemy_health_change=0,
            character_health_change=0,
            status_effects=[],
        )

    except Exception as e:
        logging.error(f"Unexpected LLM error: {e}")
        return LLMActionOutcome(
            narrative="You act, but nothing seems to happen.",
            enemy_health_change=0,
            character_health_change=0,
            status_effects=[],
        )


class CampaignInit(BaseModel):
    intro_narrative: str
    enemy_name: str
    enemy_description: str
    enemy_health: int


_CAMPAIGN_PROMPT = """You are the dungeon master for a text RPG.

User provided campaign description:
"{campaign_description}"

Instructions:
- Write a vivid short introduction narrative for the campaign.
- Create the first enemy (name, description, and starting health as an integer).
- Health should be balanced for a level 1 character (20-50 HP).
- Output strictly in JSON that matches the schema.
"""


async def generate_campaign_intro(campaign_description: str) -> CampaignInit:
    """Generate the intro narrative and first enemy using Gemini."""
    contents = _CAMPAIGN_PROMPT.format(
        campaign_description=campaign_description
    )

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": CampaignInit,
            },
        )

        if getattr(resp, "parsed", None):
            return resp.parsed

        # Fallback parse
        data = json.loads(resp.text)
        return CampaignInit(**data)

    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        # Fallback safe default
        return CampaignInit(
            intro_narrative="Your journey begins in a mysterious land.",
            enemy_name="Goblin",
            enemy_description="A small but vicious goblin blocks your path.",
            enemy_health=30,
        )

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        # Fallback safe default
        return CampaignInit(
            intro_narrative="Your adventure starts quietly, but danger lurks nearby.",
            enemy_name="Orc",
            enemy_description="A brutish orc snarls at you from the shadows.",
            enemy_health=40,
        )
