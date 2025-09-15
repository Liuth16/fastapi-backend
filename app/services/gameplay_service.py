# app/services/gameplay_service.py
import random
from app.models import Campaign, Character, Level, Turn, Effect, EffectType
from app.services.llm_service import generate_narrative_with_schema, generate_free_narrative
from app.utils.combat import build_combat_state


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

    print("Previous turns:", previous_turns)

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
    # Collect previous turns
    previous_turns = []
    last_combat_state = None
    if campaign.turns:
        turns = await Turn.find({"_id": {"$in": campaign.turns}}).to_list()
        for t in turns:
            previous_turns.append(
                f"Player: {t.user_input} | Narrative: {t.narrative}")
        last_turn = turns[-1]
        if last_turn.combat_state and last_turn.combat_state != {}:
            if last_turn.combat_state["player"]["health"] > 0 and last_turn.combat_state["enemy"]["health"] > 0:
                last_combat_state = last_turn.combat_state

    # Decide which combat state to send
    if last_combat_state:
        combat_state = last_combat_state
    else:
        combat_state = build_combat_state(character)

    # print debug
    print(f"scaffold combat state/current combat state: {combat_state}")

    # Send to LLM
    llm_outcome = await generate_free_narrative(
        action=action,
        character_name=character.name,
        combat_state=combat_state,
        previous_turns=previous_turns,
    )

    # Apply effects to character
    for effect in llm_outcome.effects:
        if effect.target == "self":
            character.current_health = max(
                0, character.current_health + effect.value)
    await character.save()

    # Save turn with returned combat state
    turn = Turn(
        turn_number=len(campaign.turns) + 1,
        user_input=action,
        narrative=llm_outcome.narrative,
        effects=llm_outcome.effects,
        character_health=character.current_health,
        enemy_health=llm_outcome.enemy_health or 0,
        combat_state=(llm_outcome.combat_state.model_dump()
                      if llm_outcome.combat_state else {}),
        enemy_defeated_reward=(
            llm_outcome.enemyDefeatedReward.model_dump()
            if llm_outcome.enemyDefeatedReward else {"gainedExperience": None, "loot": []}
        ),
        suggested_actions=llm_outcome.suggested_actions or [],
    )
    await turn.insert()

    return {
        "narrative": turn.narrative,
        "effects": [e.dict() for e in turn.effects],
        "character_health": turn.character_health,
        "enemy_health": turn.enemy_health,
        "combat_state": turn.combat_state,
        "enemy_defeated_reward": turn.enemy_defeated_reward,
        "turn_number": turn.turn_number,
        "suggested_actions": getattr(llm_outcome, "suggested_actions", []),
    }
