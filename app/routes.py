from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from beanie import PydanticObjectId
from typing import List

from .models import (
    User, UserOut,
    Character, CharacterOut,
    Campaign, CampaignOut,
    Turn, TurnOut,
    AttributeSet
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
        user_id=current_user.id
    )
    await character.insert()

    current_user.characters.append(character.id)
    await current_user.save()

    return CharacterOut.model_validate(character)


@router.get("/api/personagem", response_model=List[CharacterOut])
async def list_characters(current_user: User = Depends(get_current_user)):
    characters = await Character.find(Character.user_id == current_user.id).to_list()
    return [CharacterOut.model_validate(c) for c in characters]


@router.get("/api/personagem/{char_id}", response_model=CharacterOut)
async def get_character(char_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    character = await Character.get(char_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterOut.model_validate(character)


# ---------------------- CAMPAIGN ----------------------
@router.post("/api/campanha", response_model=CampaignOut)
async def create_campaign(
    character_id: PydanticObjectId,
    name: str,
    description: str,
    current_user: User = Depends(get_current_user),
):
    character = await Character.get(character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Character not found")

    campaign = Campaign(
        campaign_name=name,
        campaign_description=description,
        character_id=character.id
    )
    await campaign.insert()

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


@router.post("/api/campanha/{campaign_id}/acao", response_model=TurnOut)
async def campaign_action(
    campaign_id: PydanticObjectId,
    action: str,
    current_user: User = Depends(get_current_user),
):
    campaign = await Campaign.get(campaign_id)
    if not campaign or not campaign.is_active:
        raise HTTPException(status_code=400, detail="Campaign not active")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    narrative = f"You performed: {action}"

    turn = Turn(
        turn_number=len(campaign.turns) + 1,
        user_input=action,
        narrative=narrative,
        effects=[],
    )
    await turn.insert()

    campaign.turns.append(turn.id)
    await campaign.save()

    return TurnOut.model_validate(turn)


@router.delete("/api/campanha/{campaign_id}")
async def end_campaign(campaign_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    campaign.is_active = False
    await campaign.save()

    character.past_campaign_ids.append(campaign.id)
    character.current_campaign_id = None
    await character.save()

    return {"message": "Campaign ended"}


# ---------------------- HISTORY ----------------------
@router.get("/api/historico/{campaign_id}", response_model=List[TurnOut])
async def get_history(campaign_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    turns = await Turn.find({"_id": {"$in": campaign.turns}}).to_list()

    return [TurnOut.model_validate(t) for t in turns]


@router.delete("/api/historico/{campaign_id}")
async def clear_history(campaign_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    campaign = await Campaign.get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    character = await Character.get(campaign.character_id)
    if not character or str(character.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not your campaign")

    # delete all turns in this campaign
    await Turn.find({"_id": {"$in": campaign.turns}}).delete()

    campaign.turns = []
    await campaign.save()

    return {"message": "History cleared"}
