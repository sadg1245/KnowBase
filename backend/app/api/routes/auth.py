"""First-run setup and unlock endpoints for a single-user private vault."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.core.auth import create_token, hash_password, verify_password
from app.models.learning import UserProfile

router = APIRouter(prefix="/auth", tags=["auth"])


class PasswordPayload(BaseModel):
    password: str = Field(..., min_length=8, max_length=200)
    display_name: str | None = Field(None, min_length=1, max_length=80)


async def _current(db: AsyncSession) -> UserProfile | None:
    return (await db.execute(select(UserProfile).limit(1))).scalar_one_or_none()


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)) -> dict:
    profile = await _current(db)
    return {"enabled": settings.AUTH_ENABLED, "configured": bool(profile and profile.password_hash)}


@router.post("/setup")
async def setup(payload: PasswordPayload, db: AsyncSession = Depends(get_db)) -> dict:
    profile = await _current(db)
    if profile and profile.password_hash:
        raise HTTPException(409, "私人空间已经设置过密码")
    if profile is None:
        profile = UserProfile(display_name=payload.display_name or "学习者")
        db.add(profile)
    elif payload.display_name:
        profile.display_name = payload.display_name
    profile.password_hash = hash_password(payload.password)
    await db.flush()
    return {"token": create_token(profile.id), "display_name": profile.display_name}


@router.post("/login")
async def login(payload: PasswordPayload, db: AsyncSession = Depends(get_db)) -> dict:
    profile = await _current(db)
    if not profile or not profile.password_hash or not verify_password(payload.password, profile.password_hash):
        raise HTTPException(401, "密码不正确")
    return {"token": create_token(profile.id), "display_name": profile.display_name}
