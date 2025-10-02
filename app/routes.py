from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from beanie import PydanticObjectId
from typing import List
from app.chromadb.insert import insert_turn
from app.services.gameplay_service import process_player_action, process_free_action
from app.services.llm_service import (
    generate_intro_narrative, generate_enemy_for_level, generate_free_narrative, generate_free_intro)

from .models import (
    DeleteCharacterOut, User, UserOut,
    Character, CharacterOut,
    Campaign, CampaignOut,
    Level, LevelOut,
    Turn, TurnOut,
    Effect, EffectType,
    AttributeSet,
    CampaignSummary,
    CampaignMode,
    FreeActionOut,
    EndCampaignOut,
    CampaignHistoryOut,
    ClearHistoryOut
)
from .auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter()


# ---------------------- AUTH ----------------------
@router.post("/api/auth/signup", response_model=UserOut)
async def signup(name: str, email: str, password: str):
    existing = await User.find_one(User.email == email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(name=name, email=email,
                hashed_password=hash_password(password))
    await user.insert()
    return UserOut.model_validate(user)


@router.post("/api/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await User.find_one(User.email == form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/api/auth/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


# ---------------------- CHARACTER ----------------------
@router.post("/api/personagem", response_model=CharacterOut)
async def create_character(
    name: str, race: str, char_class: str, description: str,
    strength: int, dexterity: int, intelligence: int, charisma: int,
    current_user: User = Depends(get_current_user),
):
    base_level = 1
    max_health = 20 * base_level

    character = Character(
        name=name,
        race=race,
        char_class=char_class,
        description=description,
        attributes=AttributeSet(
            strength=strength,
            dexterity=dexterity,
            intelligence=intelligence,
            charisma=charisma
        ),
        level=base_level,
        max_health=max_health,
        current_health=max_health,
        user_id=current_user.id
    )
    await character.insert()

    current_user.characters.append(character.id)
    await current_user.save()

    return CharacterOut.model_validate(character)


@router.delete("/api/personagem/{char_id}", response_model=DeleteCharacterOut)
async def delete_character(
    char_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
):
    character = await Character.get(char_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Character not found")

    # Collect all related campaigns (current + past)
    campaign_ids = []
    if character.current_campaign_id:
        campaign_ids.append(character.current_campaign_id)
    if character.past_campaign_ids:
        campaign_ids.extend(character.past_campaign_ids)

    # Delete all campaigns and their turns/levels
    for camp_id in campaign_ids:
        campaign = await Campaign.get(camp_id)
        if not campaign:
            continue

        # --- STANDARD MODE ---
        if campaign.mode == CampaignMode.STANDARD:
            for level_id in campaign.levels:
                level = await Level.get(level_id)
                if not level:
                    continue
                if level.turns:
                    await Turn.find({"_id": {"$in": level.turns}}).delete()
                await level.delete()

        # --- FREE MODE ---
        elif campaign.mode == CampaignMode.FREE:
            if campaign.turns:
                await Turn.find({"_id": {"$in": campaign.turns}}).delete()

        await campaign.delete()

    # Remove character from user
    if char_id in current_user.characters:
        current_user.characters.remove(char_id)
        await current_user.save()

    # Finally delete the character itself
    await character.delete()

    return DeleteCharacterOut(message="Character and all related campaigns have been deleted")


@router.get("/api/personagem", response_model=List[CharacterOut])
async def list_characters(current_user: User = Depends(get_current_user)):
    characters = await Character.find(Character.user_id == current_user.id).to_list()

    result = []
    for c in characters:
        # Expand current campaign
        current_campaign = None
        if c.current_campaign_id:
            camp = await Campaign.get(c.current_campaign_id)
            if camp:
                current_campaign = CampaignSummary.model_validate(camp)

        # Expand past campaigns
        past_campaigns = []
        if c.past_campaign_ids:
            past = await Campaign.find({"_id": {"$in": c.past_campaign_ids}}).to_list()
            past_campaigns = [
                CampaignSummary.model_validate(pc) for pc in past]

        char_out = CharacterOut(
            **c.dict(),
            current_campaign=current_campaign,
            past_campaigns=past_campaigns,
        )
        result.append(char_out)

    return result


@router.get("/api/personagem/{char_id}", response_model=CharacterOut)
async def get_character(char_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    character = await Character.get(char_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Character not found")

    # Expand current campaign
    current_campaign = None
    if character.current_campaign_id:
        camp = await Campaign.get(character.current_campaign_id)
        if camp:
            current_campaign = CampaignSummary.model_validate(camp)

    # Expand past campaigns
    past_campaigns = []
    if character.past_campaign_ids:
        past = await Campaign.find({"_id": {"$in": character.past_campaign_ids}}).to_list()
        past_campaigns = [CampaignSummary.model_validate(pc) for pc in past]

    return CharacterOut(
        **character.dict(),
        current_campaign=current_campaign,
        past_campaigns=past_campaigns,
    )


# ---------------------- CAMPAIGN ----------------------

@router.post("/api/campanha", response_model=CampaignOut)
async def create_campaign(
    character_id: PydanticObjectId,
    name: str,
    description: str,
    mode: CampaignMode = CampaignMode.STANDARD,
    current_user: User = Depends(get_current_user),
):
    character = await Character.get(character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Character not found")

    # Reset character health
    character.max_health = 20 * character.level
    character.current_health = character.max_health
    await character.save()

    # === STANDARD MODE ===
    if mode == CampaignMode.STANDARD:
        # 1. Generate enemy
        enemy_init = await generate_enemy_for_level(name, description)

        # 2. Create campaign
        campaign = Campaign(
            campaign_name=name,
            campaign_description=description,
            mode=CampaignMode.STANDARD,
            character_id=character.id,
            current_level=1,
        )
        await campaign.insert()

        # 3. Create first level
        level1 = Level(
            level_number=1,
            enemy_name=enemy_init.enemy_name,
            enemy_description=enemy_init.enemy_description,
            enemy_health=enemy_init.enemy_health,
            enemy_max_health=enemy_init.enemy_health,
        )
        await level1.insert()
        campaign.levels.append(level1.id)
        await campaign.save()

        # 4. Generate intro narrative (Turn 1)
        intro = await generate_intro_narrative(
            description,
            enemy_init.enemy_name,
            enemy_init.enemy_description,
        )
        turn1 = Turn(
            turn_number=1,
            user_input=description,  # campaign description acts as "player input"
            narrative=intro.narrative,
            effects=[],
            character_health=character.current_health,
            enemy_health=level1.enemy_health,
        )
        await turn1.insert()
        level1.turns.append(turn1.id)
        await level1.save()

        character.current_campaign_id = campaign.id
        await character.save()

        return CampaignOut.model_validate(campaign)

    # === FREE MODE ===
    else:
        campaign = Campaign(
            campaign_name=name,
            campaign_description=description,
            mode=CampaignMode.FREE,
            character_id=character.id,
            turns=[],
        )
        await campaign.insert()

        # Generate free intro (Turn 1)
        intro = await generate_free_intro(description, character.name)
        turn1 = Turn(
            turn_number=1,
            user_input=description,
            narrative=intro.narrative,
            effects=[],
            character_health=character.current_health,
            enemy_health=0,  # no enemy in free mode
        )
        await turn1.insert()

        await insert_turn(
            str(campaign.id),
            str(turn1.id),
            turn1.user_input,
            turn1.narrative
        )

        # In free mode, turns belong directly to campaign
        campaign.turns.append(turn1.id)
        await campaign.save()

        character.current_campaign_id = campaign.id
        await character.save()

        return CampaignOut.model_validate(campaign)


@router.get("/api/campanha/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    return CampaignOut.model_validate(campaign)


@router.post("/api/campanha/{campaign_id}/acao", response_model=FreeActionOut)
async def campaign_action(
    campaign_id: PydanticObjectId,
    action: str,
    current_user=Depends(get_current_user),
):
    campaign = await Campaign.get(campaign_id)
    if not campaign or not campaign.is_active:
        raise HTTPException(status_code=400, detail="Campaign not active")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    try:
        if campaign.mode == CampaignMode.STANDARD:
            result = await process_player_action(campaign, action, character)
        else:
            result = await process_free_action(campaign, action, character)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.delete("/api/campanha/{campaign_id}", response_model=EndCampaignOut)
async def end_campaign(campaign_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    # Mark campaign inactive
    campaign.is_active = False
    await campaign.save()

    # Track campaign in character
    if campaign.id not in character.past_campaign_ids:
        character.past_campaign_ids.append(campaign.id)
    character.current_campaign_id = None
    await character.save()

    return EndCampaignOut(message="Campaign ended")

# ---------------------- HISTORY ----------------------


@router.get("/api/historico/{campaign_id}", response_model=CampaignHistoryOut)
async def get_history(
    campaign_id: PydanticObjectId,
    current_user: User = Depends(get_current_user)
) -> dict:
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    history = []

    # === STANDARD MODE ===
    if campaign.mode == CampaignMode.STANDARD:
        for level_id in campaign.levels:
            level = await Level.get(level_id)
            if not level:
                continue

            turns = await Turn.find({"_id": {"$in": level.turns}}).to_list()
            history.append({
                "level_number": level.level_number,
                "enemy_name": level.enemy_name,
                "enemy_description": level.enemy_description,
                "enemy_health": level.enemy_health,
                "enemy_max_health": level.enemy_max_health,
                "is_completed": level.is_completed,
                "turns": [TurnOut.model_validate(t) for t in turns],
            })

        return {
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.campaign_name,
            "mode": campaign.mode,
            "character_health": character.current_health,
            "character_max_health": character.max_health,
            "levels": history,
        }

    # === FREE MODE ===
    elif campaign.mode == CampaignMode.FREE:
        turns = await Turn.find({"_id": {"$in": campaign.turns}}).to_list()

        return CampaignHistoryOut(
            campaign_id=str(campaign.id),
            campaign_name=campaign.campaign_name,
            mode=campaign.mode,
            character_health=character.current_health,
            character_max_health=character.max_health,
            turns=[TurnOut.model_validate(t) for t in turns],
        )
    else:
        raise HTTPException(status_code=400, detail="Unknown campaign mode")


@router.delete("/api/historico/{campaign_id}", response_model=ClearHistoryOut)
async def clear_history(
    campaign_id: PydanticObjectId,
    current_user: User = Depends(get_current_user)
):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    # Do not allow deletion if campaign is still active
    if campaign.is_active:
        raise HTTPException(
            status_code=400, detail="Cannot delete an active campaign. End it first."
        )

    # === STANDARD MODE ===
    if campaign.mode == CampaignMode.STANDARD:
        for level_id in campaign.levels:
            level = await Level.get(level_id)
            if not level:
                continue

            if level.turns:
                await Turn.find({"_id": {"$in": level.turns}}).delete()

            await level.delete()

    # === FREE MODE ===
    elif campaign.mode == CampaignMode.FREE:
        if campaign.turns:
            await Turn.find({"_id": {"$in": campaign.turns}}).delete()

    # Remove from character's past campaigns
    if campaign.id in character.past_campaign_ids:
        character.past_campaign_ids.remove(campaign.id)
        await character.save()

    # Finally delete the campaign
    await campaign.delete()

    return ClearHistoryOut(message="Campaign and its history have been permanently deleted")
