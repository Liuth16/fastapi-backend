from fastapi import FastAPI
from core.config import settings
from beanie import init_beanie
from pymongo import AsyncMongoClient
from models.user_model import User


app = FastAPI(title=settings.PROJECT_NAME,
              openapi_url=f"{settings.API_V1_STR}/openapi.json")


@app.on_event("startup")
async def on_startup():
    client = AsyncMongoClient(settings.MONGO_CONNECTION_STRING)
    await init_beanie(database=client.rpg_game, document_models=[User])
