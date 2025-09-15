# app/utils/combat.py
from __future__ import annotations
import random
from typing import Dict, Optional
from app.models import Character


def estimate_enemy_baseline(
    character: Character,
    last_enemy_health: Optional[int] = None,
    variance: float = 0.30,
) -> Dict:
    """
    Produce a plausible enemy baseline from the player’s stats.
    If last_enemy_health is provided, keep using it to maintain continuity.
    """
    def vary(base: int) -> int:
        low = max(1, int(base * (1 - variance)))
        high = max(low, int(base * (1 + variance)))
        return random.randint(low, high)

    attrs = character.attributes
    enemy_attrs = {
        "strength": vary(attrs.strength),
        "dexterity": vary(attrs.dexterity),
        "intelligence": vary(attrs.intelligence),
        "charisma": vary(attrs.charisma),
    }

    if last_enemy_health is not None:
        enemy_health = max(0, last_enemy_health)
    else:
        enemy_health = vary(character.max_health)

    return {
        "health": enemy_health,
        "attributes": enemy_attrs,
    }


def build_combat_state(
    character: Character,
    enemy_state: Optional[Dict] = None,
) -> Dict:
    """
    Returns a combat_state scaffold with rolls only.
    - If enemy_state is provided, use it.
    - Otherwise, generate an estimated baseline enemy from character stats.
    """
    if enemy_state is None:
        enemy_state = estimate_enemy_baseline(character)

    return {
        "player": {
            "health": character.current_health,
            "max_health": character.max_health,
            "attributes": {
                "strength": character.attributes.strength,
                "dexterity": character.attributes.dexterity,
                "intelligence": character.attributes.intelligence,
                "charisma": character.attributes.charisma,
            },
            "roll": random.randint(1, 20),
        },
        "enemy": {
            "health": int(enemy_state.get("health", 0)),
            "attributes": {
                "strength": int(enemy_state.get("attributes", {}).get("strength", 0)),
                "dexterity": int(enemy_state.get("attributes", {}).get("dexterity", 0)),
                "intelligence": int(enemy_state.get("attributes", {}).get("intelligence", 0)),
                "charisma": int(enemy_state.get("attributes", {}).get("charisma", 0)),
            },
            "roll": random.randint(1, 20),
        },
    }
