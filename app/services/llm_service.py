import json
import logging
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from google import genai
from google.genai import errors as genai_errors
from app.config import settings  # centralized config
from app.models import Effect, CombatStateModel, EnemyDefeatedReward, LLMEffect


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


class LLMFreeOutcome(BaseModel):
    narrative: str
    effects: List[LLMEffect] = Field(default_factory=list)
    enemy_health: Optional[int] = None  # null/None if no enemy
    combat_state: Optional[CombatStateModel] = None  # {} -> None in schema
    enemy_defeated_reward: EnemyDefeatedReward = Field(
        default_factory=lambda: EnemyDefeatedReward(
            gainedExperience=None, loot=[]),
        alias="enemyDefeatedReward"
    )

    # Combat state flag
    active_combat: Optional[bool] = Field(default=False)

    # Suggestions
    suggested_actions: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True


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

Rules for combat resolution:

### Combat handling
1. **Combat flow order** (always follow these steps in this order):
   - Detect a physical aggression or hostile action.
   - Pick the relevant attribute for the aggressive action (must be the same attribute for both sides).
   - Check the rolls to determine the outcome:
     - Example: player_total = player.roll + player.dexterity
     - Example: enemy_total = enemy.roll + enemy.strength
   - Generate the effect based on who won the roll comparison.
- Generate the narrative in a coherent way with the result and history.  
     *You have creative freedom here, especially with magic attacks: failures may fizzle, be deflected, or countered by enemy magic; successes may manifest in varied and flavorful ways. And the same logic for physical attacks*

2. If **no combat occurs this turn**: set "combat_state": {{}} and "active_combat": false.

3. If **combat occurs or continues**:
   - Use the provided combat_state as the base.
   - **Always recalculate rolls each turn.** The "roll" values inside combat_state are re-generated every turn by the backend, and must be used fresh each turn.
   - **Recompute player_total and enemy_total each turn** with the new rolls and chosen attribute. Never reuse totals from previous turns.
   - Compare totals:
     - The side with the higher total (player_total vs enemy_total) succeeds.
     - The side with the lower total suffers the consequence.
     - Ties can be narrated as stalemates (no effect or both minor scratches).
   - Update "combat_state" with the chosen attribute and the *newly calculated* totals for this turn.
   - Do NOT invent damage values; only return the effect type ("damage" or "heal").

4. Effects must use ONLY this format:
   - {{ "type": "damage" | "heal" }}
   - Do NOT include "target" or "value". Backend will calculate those.
   - Do not change numeric health values in combat_state. Only narrate effects and provide effects objects. The backend will compute and update health.

### Narrative Guidelines
5a. **Combat Narratives**
   - Keep them short, direct, and action-focused (1–3 sentences).
   - Clearly describe the outcome of the clash (attack hits, misses, block, wound, etc.).
   - Emphasize tension, speed, and consequences rather than scenery or world-building.
   - Be especially imaginative with magical outcomes: failed spells can fizzle, backfire, or be deflected by the opponent’s powers; successful spells may erupt in unique, vivid effects.


5b. **Non-Combat Narratives**
   - Be more detailed, rich, and immersive (3–6 sentences).
   - Focus on world-building, dialogue, exploration, atmosphere, and social interactions.
   - Incentivize curiosity, roleplay, and interaction with the environment or NPCs.
   - Encourage dialogue opportunities and new directions the player might explore.

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

_PLAYER_KO_PROMPT = """You are the narrator for a freeform RPG.

The player has reached 0 health and has been knocked out.

Context:
- Past turns so far:
{previous_turns}

Rules:
- Do NOT kill the player.
- Narrate how the player survives through outside intervention (rescue, unconsciousness, someone finds them, or being spared).
- Keep it immersive and consistent with the tone of the past turns.
- Your narration must feel like the natural continuation of the story.
- The backend will handle combat state and health resets, so you only need to provide narrative and suggestions.

"""


_ENEMY_KO_PROMPT = """You are the narrator for a freeform RPG.

The enemy has reached 0 health and has been defeated.

Context:
- Past turns so far:
{previous_turns}

Rules:
- Narrate the enemy’s fall or defeat in a vivid way.
- Ensure the description matches the tone and events of the past turns.
- Provide a meaningful "enemy_defeated_reward" (loot, XP, or both) that makes sense with the context.
- The backend will handle combat state and health updates, so you only need to provide narrative, rewards, and suggestions.

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
The narrative should set the scene, introduce the character, and hint at potential adventures ahead.
Keep the introductory narrative in the same language of the campaign description (Either English or Portuguese Brazil).
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
        combat_state=json.dumps(combat_state, indent=2, ensure_ascii=False),
        previous=_format_previous(previous_turns),
    )

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
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # ✅ Normalize reward
        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=None, loot=[])

        # ✅ Force active_combat to a real bool, even if missing/None
        out.active_combat = bool(
            out.active_combat) if out.active_combat is not None else False

        # ✅ Ensure combat_state and enemy_health consistency
        if not out.active_combat:
            out.combat_state = None
            out.enemy_health = None

        # ✅ Ensure effects omit "value" (if your Effect model still has it floating around)
        for e in out.effects:
            if hasattr(e, "value"):
                e.value = None

        # ✅ Ensure suggestions list
        if out.suggested_actions is None:
            out.suggested_actions = []

        return out

    except Exception as e:
        logging.error(f"Error in generate_free_narrative: {e}")
        return LLMFreeOutcome(
            narrative="You act, but nothing conclusive happens.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=None,
            enemy_defeated_reward=EnemyDefeatedReward(
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


async def player_knocked_out(previous_turns: list[str]) -> LLMFreeOutcome:
    """Generate narrative when the player is reduced to 0 HP."""
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=_PLAYER_KO_PROMPT.format(
                previous_turns="\n".join(previous_turns)),
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # Always enforce defaults
        out.active_combat = False
        out.combat_state = None
        out.enemy_health = None

        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            )

        return out

    except Exception as e:
        logging.error(f"Error in player_knocked_out: {e}")
        return LLMFreeOutcome(
            narrative="You collapse into darkness, but fate spares your life. Someone finds you before it is too late.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=None,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            suggested_actions=["Recover your strength", "Plan your next step"],
        )


async def enemy_knocked_out(previous_turns: list[str]) -> LLMFreeOutcome:
    """Generate narrative when the enemy is reduced to 0 HP."""
    try:
        resp = _client.models.generate_content(
            model=_MODEL,
            contents=_ENEMY_KO_PROMPT.format(
                previous_turns="\n".join(previous_turns)),
            config={
                "response_mime_type": "application/json",
                "response_schema": LLMFreeOutcome,
            },
        )

        if getattr(resp, "parsed", None):
            out: LLMFreeOutcome = resp.parsed
        else:
            out = LLMFreeOutcome(**json.loads(resp.text))

        # Always enforce defaults
        out.active_combat = False
        out.combat_state = None

        if out.enemy_defeated_reward is None:
            out.enemy_defeated_reward = EnemyDefeatedReward(
                gainedExperience=10, loot=["Gold Coin"]
            )

        return out

    except Exception as e:
        logging.error(f"Error in enemy_knocked_out: {e}")
        return LLMFreeOutcome(
            narrative="The enemy crumples to the ground, defeated once and for all.",
            effects=[],
            combat_state=None,
            active_combat=False,
            enemy_health=0,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=10, loot=["Gold Coin"]
            ),
            suggested_actions=["Collect your reward", "Search the area"],
        )
