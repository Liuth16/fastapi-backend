from copy import deepcopy
from typing import Optional
from app.models import Campaign, Character, Turn, CombatStateModel


async def cheat_set_player_health_to_one(campaign: Campaign, character: Character):
    """
    If combat is active, set ONLY the player's health to 1
    in BOTH the Character doc and the last Turn snapshots
    (character_health + combat_state.player.health).
    """
    if not campaign.turns:
        return

    last_turn: Optional[Turn] = await Turn.get(campaign.turns[-1])
    if not last_turn or not last_turn.active_combat or not last_turn.combat_state:
        return

    # 1) Update Character doc
    if character.current_health != 1:
        character.current_health = 1
        await character.save()

    # 2) Update Turn snapshots
    cs = last_turn.combat_state
    if isinstance(cs, dict):
        cs = CombatStateModel(**deepcopy(cs))

    cs.player.health = 1
    last_turn.combat_state = cs
    last_turn.character_health = 1
    await last_turn.save()


async def cheat_set_enemy_health_to_one(campaign: Campaign):
    """
    If combat is active, set ONLY the enemy's health to 1
    in the last Turn snapshots (enemy_health + combat_state.enemy.health).
    """
    if not campaign.turns:
        return

    last_turn: Optional[Turn] = await Turn.get(campaign.turns[-1])
    if not last_turn or not last_turn.active_combat or not last_turn.combat_state:
        return

    cs = last_turn.combat_state
    if isinstance(cs, dict):
        cs = CombatStateModel(**deepcopy(cs))

    cs.enemy.health = 1
    last_turn.combat_state = cs
    last_turn.enemy_health = 1
    await last_turn.save()
