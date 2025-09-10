from typing import List, Optional
from beanie import Document, Link
from pydantic import BaseModel, EmailStr
from enum import Enum
from datetime import datetime
from beanie import PydanticObjectId


# ---------- ENUMS ----------
class EffectType(str, Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    BUFF = "buff"
    DEBUFF = "debuff"


# ---------- SUPPORT MODELS ----------
class AttributeSet(BaseModel):
    strength: int
    dexterity: int
    intelligence: int
    charisma: int


class Effect(BaseModel):
    type: EffectType
    target: str   # "enemy" or "self"
    value: int
    attribute: Optional[str] = None


# ---------- TURN ----------
class Turn(Document):
    turn_number: int
    user_input: str
    narrative: str
    effects: List[Effect]
    created_at: datetime = datetime.utcnow()

    class Settings:
        name = "turns"


class TurnOut(BaseModel):
    id: str
    turn_number: int
    user_input: str
    narrative: str
    effects: List[Effect]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- CAMPAIGN ----------
class Campaign(Document):
    campaign_name: str
    campaign_description: str
    is_active: bool = True
    character: Optional[Link["Character"]]  # reference to character
    turns: List[Link[Turn]] = []

    class Settings:
        name = "campaigns"


class CampaignOut(BaseModel):
    id: str
    campaign_name: str
    campaign_description: str
    is_active: bool

    class Config:
        from_attributes = True


# ---------- CHARACTER ----------
class Character(Document):
    name: str
    race: str
    char_class: str
    description: Optional[str] = None
    attributes: AttributeSet
    level: int = 1
    skill_points: int = 0
    current_campaign: Optional[Link[Campaign]] = None
    past_campaigns: List[Link[Campaign]] = []
    user: Optional[Link["User"]] = None  # back-reference to owner

    class Settings:
        name = "characters"


class CharacterOut(BaseModel):
    id: PydanticObjectId
    name: str
    race: str
    char_class: str
    description: Optional[str]
    attributes: AttributeSet
    level: int
    skill_points: int

    class Config:
        from_attributes = True


# ---------- USER ----------
class User(Document):
    name: str
    email: EmailStr
    hashed_password: str
    characters: List[Link[Character]] = []

    class Settings:
        name = "users"


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr

    class Config:
        from_attributes = True
