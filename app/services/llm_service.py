import json
import logging
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from google import genai
from google.genai import errors as genai_errors
from app.config import settings  # centralized config
from app.models import Effect


# Initialize Gemini client using settings
_client = genai.Client(api_key=settings.gemini_api_key)
_MODEL = "gemini-2.5-flash-lite"


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


class CombatAttributes(BaseModel):
    strength: int
    dexterity: int
    intelligence: int
    charisma: int


class CombatSide(BaseModel):
    health: int
    # player has max_health; enemy may omit -> make it optional
    max_health: Optional[int] = None
    attributes: CombatAttributes
    roll: int


class CombatStateModel(BaseModel):
    player: CombatSide
    enemy: CombatSide
    # optional, LLM can include when it actually resolves combat
    chosen_attribute: Optional[str] = None
    player_total: Optional[int] = None
    enemy_total: Optional[int] = None


class EnemyDefeatedReward(BaseModel):
    gainedExperience: Optional[int] = None
    loot: List[str] = Field(default_factory=list)


class LLMFreeOutcome(BaseModel):
    narrative: str
    effects: List[Effect] = Field(default_factory=list)
    enemy_health: Optional[int] = None  # null/None if no enemy
    combat_state: Optional[CombatStateModel] = None  # {} -> None in schema
    enemyDefeatedReward: EnemyDefeatedReward = Field(
        default_factory=lambda: EnemyDefeatedReward(
            gainedExperience=None, loot=[]
        )
    )

    # Combat state flag
    active_combat: bool = False

    # Suggestions
    suggested_actions: List[str] = Field(default_factory=list)


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

### Combat handling
1. Always include the field "combat_state".
   - If **no combat occurs this turn**: set "combat_state": {{}} (empty object).
   - If **combat occurs or continues**: 
     - Use the provided combat_state as the base.
     - Choose ONE relevant attribute for each side.
       - Example: player_total = roll + dexterity if dodging, roll + intelligence if casting.
       - Example: enemy_total = roll + strength
       - Always pick the same relevant attribute for both enemy and player. Example: if the player used dexterity, the enemy will also use dexterity.
     - Apply the chosen action outcome based on the roll of both player and enemy, highest roll + bonus succeed, and update health values accordingly.
     - Return the updated "combat_state" object.

2. Effects must use ONLY this format:
   - {{ "type": "damage" | "heal", "target": "enemy" | "self", "value": <int> }}

3. YOU track enemy health. Return updated integer "enemy_health" when combat is present this turn. If no enemy is present, set "enemy_health" to null.

4. Deliver rich, immersive narrative responses...

5. Always include "enemyDefeatedReward":
   - If no enemy was defeated: return {{ "gainedExperience": null, "loot": [] }}.
   - If an enemy was defeated: populate with meaningful values.

### Action Suggestions
At the end of your response, ALWAYS provide a field "suggested_actions".
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
    combat_state: dict,          # <-- we stringify for the prompt only
    previous_turns: List[str],
) -> LLMFreeOutcome:
    contents = FREE_PROMPT_TEMPLATE.format(
        action=action,
        character_name=character_name,
        combat_state=json.dumps(combat_state, indent=2, ensure_ascii=False),
        previous=_format_previous(previous_turns),
    )

    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,  # our strict schema
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        print(f"LLM Free Outcome: {out}\n")

        # ✅ Always normalize enemyDefeatedReward
        if out.enemyDefeatedReward is None:
            out.enemyDefeatedReward = EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            )

        # ✅ Ensure combat_state and active_combat consistency
        if not out.active_combat:
            out.combat_state = None
            out.enemy_health = None

        # ✅ Ensure suggested_actions is always a list
        if out.suggested_actions is None:
            out.suggested_actions = []

        return out

    except genai_errors.ServerError as e:
        logging.error(f"Gemini server error: {e}")
        return LLMFreeOutcome(
            narrative="The scene pauses; tension hangs in the air.",
            effects=[],
            combat_state={},
            active_combat=False,
            enemy_health=None,
            enemyDefeatedReward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            suggested_actions=[],
        )
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return LLMFreeOutcome(
            narrative="You act, but nothing conclusive happens.",
            effects=[],
            combat_state={},
            active_combat=False,
            enemy_health=None,
            enemyDefeatedReward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            suggested_actions=[],
        )


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
