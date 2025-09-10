from fastapi import APIRouter

user_router = APIRouter()


@user_router.get("/users/me")
async def teste():
    return "Testing route"
