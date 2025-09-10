from fastapi import FastAPI
from beanie import init_beanie
import motor.motor_asyncio
from app.models import (
    User,
    Character,
    Campaign,
    Turn,
    Level
)
from app.routes import router
from app.config import settings

app = FastAPI(title="Text RPG API")
app.include_router(router)


@app.on_event("startup")
async def app_init():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.db_name]
    await init_beanie(database=db, document_models=[User, Character, Campaign, Turn, Level])
