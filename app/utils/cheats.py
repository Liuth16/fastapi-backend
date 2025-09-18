from typing import Optional
from app.models import Campaign, Character, Turn, CombatStateModel


async def cheat_set_player_health_to_one(campaign: Campaign, character: Character):
    """
    If combat is active, set character health to 1
    and update both the last turn's combat_state snapshot and the
    flat character_health field.
    """
    if not campaign.turns:
        return

    # Get the last turn
    last_turn: Optional[Turn] = await Turn.get(campaign.turns[-1])
    if not last_turn or not last_turn.active_combat:
        return

    # Update character
    character.current_health = 1
    await character.save()

    # Update combat_state snapshot
    cs = last_turn.combat_state
    if isinstance(cs, dict):
        if "player" in cs:
            cs["player"]["health"] = 1
    elif isinstance(cs, CombatStateModel):
        cs.player.health = 1

    # Update flat field
    last_turn.character_health = 1

    await last_turn.save()


async def cheat_set_enemy_health_to_one(campaign: Campaign):
    """
    If combat is active, set enemy health to 1
    and update both the last turn's combat_state snapshot and the
    flat enemy_health field.
    """
    if not campaign.turns:
        return

    # Get the last turn
    last_turn: Optional[Turn] = await Turn.get(campaign.turns[-1])
    if not last_turn or not last_turn.active_combat:
        return

    # Update combat_state snapshot
    cs = last_turn.combat_state
    if isinstance(cs, dict):
        if "enemy" in cs:
            cs["enemy"]["health"] = 1
    elif isinstance(cs, CombatStateModel):
        cs.enemy.health = 1

    # Update flat field
    last_turn.enemy_health = 1

    await last_turn.save()
