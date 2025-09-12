from typing import List, Optional
from beanie import Document, PydanticObjectId
from pydantic import BaseModel, EmailStr
from enum import Enum
from datetime import datetime


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

    # NEW: health snapshots after this turn
    character_health: int
    enemy_health: int

    class Settings:
        name = "turns"


class TurnOut(BaseModel):
    id: PydanticObjectId
    turn_number: int
    user_input: str
    narrative: str
    effects: List[Effect]
    created_at: datetime

    # NEW
    character_health: int
    enemy_health: int

    class Config:
        from_attributes = True


# ---------- LEVEL ----------
class Level(Document):
    level_number: int
    enemy_name: str
    enemy_description: str
    enemy_health: int
    enemy_max_health: int          # NEW
    is_completed: bool = False
    turns: List[PydanticObjectId] = []

    class Settings:
        name = "levels"


class LevelOut(BaseModel):
    id: PydanticObjectId
    level_number: int
    enemy_name: str
    enemy_description: str
    enemy_health: int
    enemy_max_health: int          # NEW
    is_completed: bool

    class Config:
        from_attributes = True


# ---------- CAMPAIGN ----------

class CampaignSummary(BaseModel):
    id: PydanticObjectId
    campaign_name: str
    intro_narrative: str

    class Config:
        from_attributes = True


class Campaign(Document):
    campaign_name: str
    campaign_description: str
    intro_narrative: str                     # NEW
    is_active: bool = True
    character_id: PydanticObjectId
    current_level: int = 1
    levels: List[PydanticObjectId] = []  # references to Level docs

    class Settings:
        name = "campaigns"


class CampaignOut(BaseModel):
    id: PydanticObjectId
    campaign_name: str
    campaign_description: str
    intro_narrative: str             # NEW
    is_active: bool
    current_level: int

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

    max_health: int               # NEW
    current_health: int           # NEW

    current_campaign_id: Optional[PydanticObjectId] = None
    past_campaign_ids: List[PydanticObjectId] = []
    user_id: PydanticObjectId

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

    # NEW
    max_health: int
    current_health: int

    current_campaign: Optional[CampaignSummary] = None
    past_campaigns: List[CampaignSummary] = []

    class Config:
        from_attributes = True


# ---------- USER ----------
class User(Document):
    name: str
    email: EmailStr
    hashed_password: str
    characters: List[PydanticObjectId] = []

    class Settings:
        name = "users"


class UserOut(BaseModel):
    id: PydanticObjectId
    name: str
    email: EmailStr

    class Config:
        from_attributes = True
