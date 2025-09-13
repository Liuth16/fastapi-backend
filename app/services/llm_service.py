import json
import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import errors as genai_errors
from app.config import settings  # centralized config
from app.models import Effect


# Initialize Gemini client using settings
_client = genai.Client(api_key=settings.gemini_api_key)
_MODEL = "gemini-2.5-flash"


# =======================
# MODELS
# =======================

class LLMActionOutcome(BaseModel):
    narrative: str
    enemy_health_change: int = 0
    character_health_change: int = 0
    status_effects: List[str] = Field(default_factory=list)


class IntroInit(BaseModel):
    narrative: str


class LLMFreeOutcome(BaseModel):
    narrative: str
    # uses your simplified Effect(type, target, value)
    effects: List[Effect] = Field(default_factory=list)
    enemy_health: Optional[int] = None  # LLM-managed; None if no enemy present


class EnemyInit(BaseModel):
    enemy_name: str
    enemy_description: str
    enemy_health: int


# =======================
# PROMPTS
# =======================

ACTION_PROMPT = """You are the game narrator for a text-based RPG.

Player action: "{action}"
Outcome decided by game engine: {outcome}  # do NOT override this outcome

Game state:
- Character: {character_name}
- Enemy: {enemy_name} (health: {enemy_health})
- Enemy description: {enemy_description}
- Level: {level_number}

Previous turns (most recent first):
{previous}

Instructions:
- Write a short, vivid narrative (1–3 sentences) describing the outcome consistent with {outcome}.
- Do not mention dice rolls, random numbers, or the word "success"/"failure".
- Update health deltas accordingly (negative = damage taken, positive = healing).
- Return only JSON that matches the provided schema.
"""

_INTRO_PROMPT = """You are the narrator.
Context:
Campaign description: {campaign_description}
Enemy: {enemy_name} - {enemy_description}

Write an engaging introductory narrative (2–3 sentences).
Output JSON with field "narrative".
"""

FREE_PROMPT_TEMPLATE = """You are the game narrator for a freeform text-based RPG.

Player action: "{action}"

Game state:
- Character: {character_name}

Combat state (always provided — ignore unless hostility occurs):
{combat_state}

Previous turns:
{previous}

Rules for combat resolution (ONLY if hostility occurs this turn, or you introduce it):
1) Choose ONE most relevant attribute for the player from: strength, dexterity, intelligence, charisma,
   based on the semantics of the action (e.g., dodging -> dexterity, persuasion -> charisma, spell -> intelligence, strike -> strength).
2) Choose ONE relevant attribute for the enemy’s response.
3) Compute totals: player_total = player.roll + player.attributes[chosen]; enemy_total = enemy.roll + enemy.attributes[chosen].
4) The higher total succeeds. Apply one or more effects using ONLY:
   - {{ "type": "damage" | "heal", "target": "enemy" | "self", "value": <int> }}
5) YOU track enemy health. Return updated integer "enemy_health" when combat is present this turn. If no enemy is present, set "enemy_health" to null.
6) Deliver rich, immersive narrative responses. Include vivid descriptions, character reactions, short dialogues, and atmospheric details. Show events through the characters’ experiences—use tone, mood, and sensory language. Avoid meta-game language like “dice rolls” or “attributes.”

If no hostility: ignore the combat state and continue the story without combat effects.

Return ONLY valid JSON matching the schema.
"""

_ENEMY_PROMPT = """You are the dungeon master.
Campaign context:
Name: {campaign_name}
Description: {campaign_description}

Generate the first enemy (name, description, and health 20–50).
Output JSON strictly matching the schema.
"""


# =======================
# HELPERS
# =======================

def _format_previous(previous_turns: List[str]) -> str:
    if not previous_turns:
        return "- (no prior turns)"
    return "\n".join(f"- {p}" for p in previous_turns[::-1])


# =======================
# FUNCTIONS
# =======================

async def generate_narrative_with_schema(
    *,
    action: str,
    outcome_success: bool,
    character_name: str,
    enemy_name: str,
    enemy_description: str,
    enemy_health: int,
    level_number: int,
    previous_turns: List[str],
) -> LLMActionOutcome:
    outcome = "SUCCESS" if outcome_success else "FAILURE"

    contents = ACTION_PROMPT.format(
        action=action,
        outcome=outcome,
        character_name=character_name,
        enemy_name=enemy_name,
        enemy_description=enemy_description,
        enemy_health=enemy_health,
        level_number=level_number,
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
        return resp.parsed if getattr(resp, "parsed", None) else LLMActionOutcome(
            narrative="You act, but the outcome is unclear.",
        )
    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        return LLMActionOutcome(
            narrative="The battle is chaotic, and the outcome is unclear.",
        )
    except Exception as e:
        logging.error(f"Unexpected LLM error: {e}")
        return LLMActionOutcome(
            narrative="You act, but nothing seems to happen.",
        )


async def generate_intro_narrative(campaign_description: str, enemy_name: str, enemy_description: str) -> IntroInit:
    contents = _INTRO_PROMPT.format(
        campaign_description=campaign_description,
        enemy_name=enemy_name,
        enemy_description=enemy_description,
    )
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": IntroInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else IntroInit(
            narrative="Your adventure begins as you face your first foe."
        )
    except Exception as e:
        logging.error(f"Intro generation error: {e}")
        return IntroInit(narrative="Your journey begins in a mysterious land.")


async def generate_free_intro(campaign_description: str, character_name: str) -> IntroInit:
    """Generates the intro narrative for free mode (Turn 1)."""
    contents = f"""You are the narrator.
Context:
Campaign description: {campaign_description}
Character: {character_name}

Write an engaging introductory narrative (2–3 sentences).
Output JSON with field "narrative".
"""
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": IntroInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else IntroInit(
            narrative="A new adventure begins, full of possibilities."
        )
    except Exception as e:
        logging.error(f"Free intro generation error: {e}")
        return IntroInit(narrative="The story begins, waiting for your choices.")


async def generate_free_narrative(
    *,
    action: str,
    character_name: str,
    combat_state: dict,
    previous_turns: List[str],
) -> LLMFreeOutcome:
    contents = FREE_PROMPT_TEMPLATE.format(
        action=action,
        character_name=character_name,
        combat_state=json.dumps(combat_state, indent=2),
        previous=_format_previous(previous_turns),
    )

    # debug
    print(
        f"Combat state: {combat_state} \n \n Previous turns: {previous_turns} \n \n")

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )
        if getattr(resp, "parsed", None):
            return resp.parsed
        data = json.loads(resp.text)
        return LLMFreeOutcome(**data)
    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        return LLMFreeOutcome(narrative="The scene pauses; tension hangs in the air.", effects=[], enemy_health=None)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return LLMFreeOutcome(narrative="You act, but nothing conclusive happens.", effects=[], enemy_health=None)


async def generate_enemy_for_level(campaign_name: str, campaign_description: str) -> EnemyInit:
    contents = _ENEMY_PROMPT.format(
        campaign_name=campaign_name,
        campaign_description=campaign_description,
    )
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={"response_mime_type": "application/json",
                    "response_schema": EnemyInit},
        )
        return resp.parsed if getattr(resp, "parsed", None) else EnemyInit(
            enemy_name="Goblin",
            enemy_description="A nasty little goblin snarls at you.",
            enemy_health=30,
        )
    except Exception as e:
        logging.error(f"Enemy generation error: {e}")
        return EnemyInit(
            enemy_name="Orc",
            enemy_description="A brutish orc stares you down.",
            enemy_health=40,
        )
