# app/services/gameplay_service.py
from app.models import Campaign, Character, Level, Turn, Effect, EffectType


async def process_player_action(campaign: Campaign, action: str, character: Character):
    """Process a player action inside the current campaign level and create a Turn entry."""

    # Validate campaign state
    if campaign.current_level > len(campaign.levels):
        raise ValueError("No active level")

    # Get current level
    level_id = campaign.levels[campaign.current_level - 1]
    level = await Level.get(level_id)
    if not level:
        raise ValueError("Level not found")

    # --- Mock resolution logic (replace later with LLM integration) ---
    narrative = f"You performed: {action}"
    damage = 10  # Fixed damage for now
    level.enemy_health = max(0, level.enemy_health - damage)

    if level.enemy_health <= 0:
        level.is_completed = True
        narrative += f" The {level.enemy_name} has been defeated!"

    # (Optional) you could also apply damage to the character here if needed
    # e.g. character.current_health = max(0, character.current_health - 3)
    await character.save()

    # --- Create Turn with health snapshots ---
    turn = Turn(
        turn_number=len(level.turns) + 1,
        user_input=action,
        narrative=narrative,
        effects=[Effect(type=EffectType.DAMAGE, target="enemy", value=damage)],
        character_health=character.current_health,
        enemy_health=level.enemy_health,
    )
    await turn.insert()

    # Link turn to level
    level.turns.append(turn.id)
    await level.save()

    # --- Return structured response ---
    return {
        "narrative": narrative,
        "enemy_health": level.enemy_health,
        "character_health": character.current_health,
        "enemy_defeated": level.is_completed,
        "turn_number": turn.turn_number,
    }
