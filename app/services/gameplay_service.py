# app/services/gameplay_service.py
import random
from app.models import Campaign, Character, Turn, Effect, EffectType, EnemyDefeatedReward, CombatStateModel, Level
from app.services.llm_service import generate_narrative_with_schema, generate_free_narrative, player_knocked_out, enemy_knocked_out
from app.utils.combat import build_combat_state, resolve_effect, refresh_rolls


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

    # Decide outcome randomly for now (50/50)
    outcome_success = random.choice([True, False])

    # Collect previous turn narratives for context
    previous_turns = []
    if level.turns:
        turns = await Turn.find({"_id": {"$in": level.turns}}).to_list()
        for t in turns:
            previous_turns.append(
                f"Player: {t.user_input} | Narrative: {t.narrative}")

    # Call Gemini for structured narrative
    llm_outcome = await generate_narrative_with_schema(
        action=action,
        outcome_success=outcome_success,
        character_name=character.name,
        enemy_name=level.enemy_name,
        enemy_description=level.enemy_description,     # NEW
        enemy_health=level.enemy_health,
        level_number=level.level_number,
        intro_narrative=campaign.intro_narrative,      # NEW
        previous_turns=previous_turns,
    )

    # Apply health changes
    level.enemy_health = max(0, level.enemy_health +
                             llm_outcome.enemy_health_change)
    character.current_health = max(
        0, character.current_health + llm_outcome.character_health_change)

    # Mark level complete if enemy died
    if level.enemy_health <= 0:
        level.is_completed = True

    # Persist character and level
    await character.save()
    await level.save()

    # Create Turn with health snapshots
    turn = Turn(
        turn_number=len(level.turns) + 1,
        user_input=action,
        narrative=llm_outcome.narrative,
        effects=[
            Effect(
                type=EffectType.DAMAGE if llm_outcome.enemy_health_change < 0 else EffectType.HEAL,
                target="enemy",
                value=abs(llm_outcome.enemy_health_change),
            ),
            Effect(
                type=EffectType.DAMAGE if llm_outcome.character_health_change < 0 else EffectType.HEAL,
                target="self",
                value=abs(llm_outcome.character_health_change),
            ),
        ],
        character_health=character.current_health,
        enemy_health=level.enemy_health,
    )
    await turn.insert()

    # Link turn to level
    level.turns.append(turn.id)
    await level.save()

    return {
        "narrative": llm_outcome.narrative,
        "enemy_health": level.enemy_health,
        "character_health": character.current_health,
        "enemy_defeated": level.is_completed,
        "turn_number": turn.turn_number,
    }


async def process_free_action(campaign: Campaign, action: str, character: Character):
    previous_turns = []
    last_combat_state = None

    if campaign.turns:
        turns = await Turn.find({"_id": {"$in": campaign.turns}}).to_list()
        for t in turns:
            previous_turns.append(
                f"Player: {t.user_input} | Narrative: {t.narrative}"
            )
        last_turn = turns[-1]

        # --- handle combat_state being dict (DB) or model (LLM)
        if last_turn.combat_state:
            if isinstance(last_turn.combat_state, dict):
                player_health = last_turn.combat_state.get(
                    "player", {}).get("health", 0)
                enemy_health = last_turn.combat_state.get(
                    "enemy", {}).get("health", 0)
            else:  # CombatStateModel
                player_health = last_turn.combat_state.player.health
                enemy_health = last_turn.combat_state.enemy.health

            if player_health > 0 and enemy_health > 0 and last_turn.active_combat:
                last_combat_state = last_turn.combat_state

    # --- scaffold or continue
    if last_combat_state:
        combat_state = (
            CombatStateModel(**last_combat_state)
            if isinstance(last_combat_state, dict)
            else last_combat_state
        )
    else:
        combat_state = CombatStateModel(**build_combat_state(character))

    combat_state = refresh_rolls(combat_state)

    # --- Send to LLM
    llm_outcome = await generate_free_narrative(
        action=action,
        character_name=character.name,
        combat_state=combat_state.model_dump(),
        previous_turns=previous_turns,
    )

    # --- Apply effects (compute + persist)
    computed_effects = []
    for effect in llm_outcome.effects:
        resolved = resolve_effect(
            effect_type=effect.type,
            attacker=combat_state.player,
            defender=combat_state.enemy,
            player_total=combat_state.player_total or 0,
            enemy_total=combat_state.enemy_total or 0,
        )
        # Apply to player
        if resolved.target == "self":
            character.current_health = max(
                0,
                min(
                    character.max_health,
                    character.current_health
                    + (resolved.value if resolved.type ==
                       EffectType.HEAL else -resolved.value),
                ),
            )
        # Apply to enemy
        elif resolved.target == "enemy" and llm_outcome.combat_state:
            enemy = llm_outcome.combat_state.enemy
            if resolved.type == EffectType.HEAL and enemy.max_health:
                enemy.health = min(
                    enemy.max_health, enemy.health + resolved.value)
            elif resolved.type == EffectType.DAMAGE:
                enemy.health = max(0, enemy.health - resolved.value)

        computed_effects.append(resolved)

    await character.save()

    # --- Clamp enemy health
    if llm_outcome.combat_state:
        enemy = llm_outcome.combat_state.enemy
        if enemy.max_health is not None:
            enemy.health = max(0, min(enemy.max_health, enemy.health))

    # --- Check for knockouts
    if character.current_health <= 0:
        # reset player and end combat
        character.current_health = character.max_health
        await character.save()
        llm_outcome = await player_knocked_out()

    elif llm_outcome.combat_state and llm_outcome.combat_state.enemy.health <= 0:
        llm_outcome = await enemy_knocked_out()

    # --- Normalize reward
    if isinstance(llm_outcome.enemyDefeatedReward, EnemyDefeatedReward):
        reward = llm_outcome.enemyDefeatedReward
    elif isinstance(llm_outcome.enemyDefeatedReward, dict):
        reward = EnemyDefeatedReward(**llm_outcome.enemyDefeatedReward)
    else:
        reward = EnemyDefeatedReward(gainedExperience=None, loot=[])

    # --- Save turn
    turn = Turn(
        turn_number=len(campaign.turns) + 1,
        user_input=action,
        narrative=llm_outcome.narrative,
        effects=computed_effects,
        character_health=character.current_health,
        enemy_health=llm_outcome.enemy_health or 0,
        combat_state=llm_outcome.combat_state,
        active_combat=bool(llm_outcome.active_combat),
        enemy_defeated_reward=reward,
        suggested_actions=llm_outcome.suggested_actions,
    )
    await turn.insert()

    # ✅ Attach turn to campaign
    campaign.turns.append(turn.id)
    await campaign.save()

    return {
        "narrative": turn.narrative,
        "effects": [e.dict() for e in turn.effects],
        "character_health": turn.character_health,
        "enemy_health": turn.enemy_health,
        "combat_state": turn.combat_state.model_dump() if turn.combat_state else None,
        "active_combat": turn.active_combat,
        "enemy_defeated_reward": turn.enemy_defeated_reward.model_dump(),
        "turn_number": turn.turn_number,
        "suggested_actions": turn.suggested_actions,
    }
