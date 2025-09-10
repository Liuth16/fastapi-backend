from app.models import Campaign, Level, Turn, Effect, EffectType
import random


async def process_player_action(campaign: Campaign, action: str):
    """Process a player action inside the current campaign level."""
    if campaign.current_level > len(campaign.levels):
        raise ValueError("No active level")

    # Get current level
    level_id = campaign.levels[campaign.current_level - 1]
    level = await Level.get(level_id)
    if not level:
        raise ValueError("Level not found")

    # Case 1: Next level
    if action.lower() in ["advance", "next level"]:
        if not level.is_completed:
            raise ValueError("Enemy not defeated yet")

        new_enemy = {
            "enemy_name": "Generated Orc",
            "enemy_description": "A fierce orc blocks your path.",
            "enemy_health": 50,
        }

        new_level = Level(
            level_number=campaign.current_level + 1,
            enemy_name=new_enemy["enemy_name"],
            enemy_description=new_enemy["enemy_description"],
            enemy_health=new_enemy["enemy_health"],
        )
        await new_level.insert()

        campaign.levels.append(new_level.id)
        campaign.current_level += 1
        await campaign.save()

        return {
            "narrative": f"A new foe appears: {new_enemy['enemy_name']}!",
            "level": new_level.level_number,
            "enemy_health": new_level.enemy_health,
        }

    # Case 2: Normal action
    narrative = f"You performed: {action}"
    damage = 10  # TODO: LLM or attribute system
    level.enemy_health -= damage

    if level.enemy_health <= 0:
        level.enemy_health = 0
        level.is_completed = True
        narrative += f" The {level.enemy_name} is defeated!"

    turn = Turn(
        turn_number=len(level.turns) + 1,
        user_input=action,
        narrative=narrative,
        effects=[Effect(type=EffectType.DAMAGE, target="enemy", value=damage)],
    )
    await turn.insert()

    level.turns.append(turn.id)
    await level.save()

    return {
        "narrative": narrative,
        "enemy_health": level.enemy_health,
        "enemy_defeated": level.is_completed,
        "turn_number": turn.turn_number,
    }
