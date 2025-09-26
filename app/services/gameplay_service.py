# app/services/gameplay_service.py
import random
from app.models import Campaign, Character, Turn, Effect, EffectType, EnemyDefeatedReward, CombatStateModel, Level, FreeActionOut, CombatStateOut
from app.services.llm_service import generate_narrative_with_schema, generate_free_narrative, player_knocked_out, enemy_knocked_out
from app.utils.combat import build_combat_state, resolve_effect, refresh_rolls
from app.utils.cheats import cheat_set_player_health_to_one, cheat_set_enemy_health_to_one


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

    if action.strip().lower() == "reducemylife":
        await cheat_set_player_health_to_one(campaign, character)
    # Safely read enemy health from the last turn (prefer combat_state, fallback to flat field)
        enemy_health = 0
        if campaign.turns:
            lt = await Turn.get(campaign.turns[-1])
            if lt:
                if lt.combat_state:
                    if isinstance(lt.combat_state, dict):
                        enemy_health = int(lt.combat_state.get(
                            "enemy", {}).get("health", lt.enemy_health or 0))
                    else:  # CombatStateModel
                        enemy_health = int(lt.combat_state.enemy.health)
                else:
                    enemy_health = int(lt.enemy_health or 0)

        return FreeActionOut(
            narrative="Cheat activated: player health set to 1.",
            effects=[],
            character_health=1,
            enemy_health=enemy_health,  # <- preserve enemy HP
            combat_state=None,
            active_combat=False,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]),
            turn_number=len(campaign.turns),
            suggested_actions=[],
        )

    if action.strip().lower() == "reduceenemylife":
        await cheat_set_enemy_health_to_one(campaign)
        return FreeActionOut(
            narrative="Cheat activated: enemy health set to 1.",
            effects=[],
            character_health=character.current_health,
            enemy_health=1,
            combat_state=None,
            active_combat=False,
            enemy_defeated_reward=EnemyDefeatedReward(
                gainedExperience=None, loot=[]
            ),
            turn_number=len(campaign.turns),
            suggested_actions=[],
        )

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

    print("Combat State Sent to LLM:", combat_state)

    # --- Send to LLM
    llm_outcome = await generate_free_narrative(
        action=action,
        character_name=character.name,
        combat_state=combat_state.model_dump(),
        previous_turns=previous_turns,
    )

    print("LLM Outcome:", llm_outcome.combat_state)

    # Helper: read fresh totals from the LLM output (fallback to rolls if missing)
    def _fresh_totals(cs) -> tuple[int, int]:
        if not cs:
            return (0, 0)
        pt = cs.player_total if cs.player_total is not None else cs.player.roll
        et = cs.enemy_total if cs.enemy_total is not None else cs.enemy.roll
        return (int(pt), int(et))

    cs_out = llm_outcome.combat_state  # the LLM-updated combat state
    p_total, e_total = _fresh_totals(cs_out)

    # --- Apply effects using backend as source of truth
    computed_effects = []
    player_hp = character.current_health
    enemy_hp = combat_state.enemy.health  # <- baseline from backend

    for effect in llm_outcome.effects:
        resolved = resolve_effect(
            effect_type=effect.type,
            attacker=combat_state.player,
            defender=combat_state.enemy,
            player_total=p_total,
            enemy_total=e_total,
        )

        if resolved.target == "none" or (resolved.value or 0) <= 0:
            continue

        if resolved.target == "self":
            player_hp = max(
                0,
                min(
                    character.max_health,
                    player_hp + (resolved.value if resolved.type ==
                                 EffectType.HEAL else -resolved.value),
                ),
            )
        elif resolved.target == "enemy":
            if resolved.type == EffectType.HEAL:
                enemy_hp = min(combat_state.enemy.max_health,
                               enemy_hp + resolved.value)
            elif resolved.type == EffectType.DAMAGE:
                enemy_hp = max(0, enemy_hp - resolved.value)

        computed_effects.append(resolved)

 # --- Commit updates back (source of truth = computed player_hp/enemy_hp)
    character.current_health = player_hp
    await character.save()

    # Sync into the backend combat_state we sent to the LLM
    combat_state.player.health = player_hp
    combat_state.enemy.health = enemy_hp

    # And sync into the LLM-returned combat state we'll persist on the Turn
    if cs_out:
        cs_out.player.health = player_hp
        cs_out.enemy.health = enemy_hp

    # --- Clamp both sides in the final state we'll store
    if cs_out:
        if cs_out.player.max_health is not None:
            cs_out.player.health = max(
                0, min(cs_out.player.max_health, cs_out.player.health))
        if cs_out.enemy.max_health is not None:
            cs_out.enemy.health = max(
                0, min(cs_out.enemy.max_health, cs_out.enemy.health))

    # --- Check for knockouts
    if character.current_health <= 0:
        character.current_health = character.max_health
        await character.save()
        llm_outcome = await player_knocked_out(previous_turns)
        cs_out = llm_outcome.combat_state  # may be None after KO
    elif cs_out and cs_out.enemy.health <= 0:
        llm_outcome = await enemy_knocked_out(previous_turns)
        cs_out = llm_outcome.combat_state

    # --- Normalize reward
    if isinstance(llm_outcome.enemy_defeated_reward, EnemyDefeatedReward):
        reward = llm_outcome.enemy_defeated_reward
    elif isinstance(llm_outcome.enemy_defeated_reward, dict):
        reward = EnemyDefeatedReward(**llm_outcome.enemy_defeated_reward)
    else:
        reward = EnemyDefeatedReward(gainedExperience=None, loot=[])

    # Compute active_combat AFTER applying effects
    active_combat = bool(
        cs_out and character.current_health > 0 and cs_out.enemy.health > 0
    )

    # --- Save turn (use the post-application enemy health)
    turn = Turn(
        turn_number=len(campaign.turns) + 1,
        user_input=action,
        narrative=llm_outcome.narrative,
        effects=computed_effects,
        character_health=character.current_health,
        enemy_health=(cs_out.enemy.health if cs_out else 0),
        combat_state=cs_out,
        active_combat=active_combat,
        enemy_defeated_reward=reward,
        suggested_actions=llm_outcome.suggested_actions,
    )
    await turn.insert()

    # ✅ Attach turn to campaign
    campaign.turns.append(turn.id)
    await campaign.save()

    return FreeActionOut(
        narrative=turn.narrative,
        effects=turn.effects,
        character_health=turn.character_health,
        enemy_health=turn.enemy_health,
        combat_state=CombatStateOut.model_validate(
            turn.combat_state.model_dump()
        ) if turn.combat_state else None,
        active_combat=turn.active_combat,
        enemy_defeated_reward=turn.enemy_defeated_reward,
        turn_number=turn.turn_number,
        suggested_actions=turn.suggested_actions,
    )
