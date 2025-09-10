from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from beanie import PydanticObjectId
from typing import List

from .models import (
    User, UserOut,
    Character, CharacterOut,
    Campaign, CampaignOut,
    Turn, TurnOut,
    AttributeSet
)
from .auth import hash_password, verify_password, create_access_token

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


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
async def get_me(token: str = Depends(oauth2_scheme)):
    # TODO: decode JWT properly and fetch user
    # placeholder: just to show structure
    raise HTTPException(status_code=501, detail="Not implemented yet")


# ---------------------- CHARACTER ----------------------
@router.post("/api/personagem", response_model=CharacterOut)
async def create_character(
    name: str, race: str, char_class: str, description: str,
    strength: int, dexterity: int, intelligence: int, charisma: int,
    user_id: PydanticObjectId
):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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
        user=user
    )
    await character.insert()

    user.characters.append(character)
    await user.save()

    return CharacterOut.model_validate(character)


@router.get("/api/personagem", response_model=List[CharacterOut])
async def list_characters(user_id: PydanticObjectId):
    user = await User.get(user_id, fetch_links=False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    characters = await Character.find(Character.user.id == user.id).to_list()
    return [CharacterOut.model_validate(c) for c in characters]


@router.get("/api/personagem/{char_id}", response_model=CharacterOut)
async def get_character(char_id: PydanticObjectId):
    character = await Character.get(char_id, fetch_links=False)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return CharacterOut.model_validate(character)


# ---------------------- CAMPAIGN ----------------------
@router.post("/api/campanha", response_model=CampaignOut)
async def create_campaign(character_id: PydanticObjectId, name: str, description: str):
    character = await Character.get(character_id, fetch_links=False)
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    campaign = Campaign(
        campaign_name=name,
        campaign_description=description,
        character=character
    )
    await campaign.insert()

    saved_char = await Character.get(character.id)
    if not saved_char:
        raise HTTPException(status_code=500, detail="Character insert failed")
    print("Inserted Character:", saved_char.dict())

    character.current_campaign = campaign
    await character.save()

    return CampaignOut.model_validate(campaign)


@router.get("/api/campanha/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: PydanticObjectId):
    campaign = await Campaign.get(campaign_id, fetch_links=False)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignOut.model_validate(campaign)


@router.post("/api/campanha/{campaign_id}/acao", response_model=TurnOut)
async def campaign_action(campaign_id: PydanticObjectId, action: str):
    campaign = await Campaign.get(campaign_id, fetch_links=False)
    if not campaign or not campaign.is_active:
        raise HTTPException(status_code=400, detail="Campaign not active")

    # 1. Validate action (placeholder)
    # 2. Get narrative from LLM (placeholder)
    narrative = f"You performed: {action}"

    turn = Turn(
        turn_number=len(campaign.turns) + 1,
        user_input=action,
        narrative=narrative,
        effects=[],
    )
    await turn.insert()

    campaign.turns.append(turn)
    await campaign.save()

    return TurnOut.model_validate(turn)


@router.delete("/api/campanha/{campaign_id}")
async def end_campaign(campaign_id: PydanticObjectId):
    campaign = await Campaign.get(campaign_id, fetch_links=False)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign.is_active = False
    await campaign.save()

    character = await campaign.character.fetch()
    character.past_campaigns.append(campaign)
    character.current_campaign = None
    await character.save()

    return {"message": "Campaign ended"}


# ---------------------- HISTORY ----------------------
@router.get("/api/historico/{campaign_id}", response_model=List[TurnOut])
async def get_history(campaign_id: PydanticObjectId):
    campaign = await Campaign.get(campaign_id, fetch_links=True)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    turns = [await t.fetch() for t in campaign.turns]
    return [TurnOut.model_validate(t) for t in turns]


@router.delete("/api/historico/{campaign_id}")
async def clear_history(campaign_id: PydanticObjectId):
    campaign = await Campaign.get(campaign_id, fetch_links=True)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # delete all linked turns
    for turn in campaign.turns:
        await turn.delete()

    campaign.turns = []
    await campaign.save()
    return {"message": "History cleared"}
