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

app = FastAPI(title="Text RPG API")
app.include_router(router)


@app.on_event("startup")
async def app_init():
    client = motor.motor_asyncio.AsyncIOMotorClient(
        "mongodb://host.docker.internal:27017")
    db = client["rpg_db"]
    await init_beanie(database=db, document_models=[User, Character, Campaign, Turn, Level])
