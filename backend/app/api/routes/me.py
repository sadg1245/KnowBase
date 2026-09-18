"""当前用户的资料、头像与学习偏好端点。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.api.routes.auth import create_default_preferences, profile_payload
from app.config import Settings
from app.core.media import delete_media, public_image_url, store_image, validate_external_image_url
from app.models.user import LearningPreference, User
from app.schemas.account import (
    PreferenceResponse,
    PreferenceUpdate,
    UserProfileResponse,
    UserProfileUpdate,
)
from app.services import goal_service


router = APIRouter(tags=["account"])


def _preference_payload(preference: LearningPreference) -> dict:
    return {
        "daily_goal_minutes": preference.daily_goal_minutes,
        "daily_review_target": preference.daily_review_target,
        "weekly_goal_days": preference.weekly_goal_days,
        "timezone_name": preference.timezone_name,
        "preferred_mode": preference.preferred_mode,
        "reminder_time": preference.reminder_time,
    }


async def _preferences(db: AsyncSession, user: User) -> LearningPreference:
    preference = await db.get(LearningPreference, user.id)
    if preference is None:
        preference = await create_default_preferences(db, user)
    return preference


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> dict:
    return profile_payload(current_user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """修改昵称与头像外链；清除头像时同时清理旧本地文件。"""
    previous_upload = (
        current_user.avatar_value if current_user.avatar_kind == "upload" else None
    )
    if payload.display_name is not None:
        current_user.display_name = payload.display_name.strip()
    if payload.clear_avatar:
        current_user.avatar_kind = "none"
        current_user.avatar_value = None
    elif payload.avatar_url is not None:
        url = validate_external_image_url(payload.avatar_url, settings)
        current_user.avatar_kind = "url"
        current_user.avatar_value = url
    current_user.updated_at = datetime.now(timezone.utc)
    if current_user.avatar_kind != "upload" and previous_upload:
        delete_media(previous_upload, settings)
    return profile_payload(current_user)


@router.post("/me/avatar", response_model=UserProfileResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """上传头像：校验大小/格式/文件头后写入受控目录，再更新数据库。"""
    previous_upload = (
        current_user.avatar_value if current_user.avatar_kind == "upload" else None
    )
    stored = await store_image(file, "avatar", settings=settings)
    current_user.avatar_kind = "upload"
    current_user.avatar_value = stored.relative_path
    current_user.updated_at = datetime.now(timezone.utc)
    if previous_upload and previous_upload != stored.relative_path:
        delete_media(previous_upload, settings)
    return profile_payload(current_user)


@router.delete("/me/avatar", response_model=UserProfileResponse)
async def clear_avatar(
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    previous_upload = (
        current_user.avatar_value if current_user.avatar_kind == "upload" else None
    )
    current_user.avatar_kind = "none"
    current_user.avatar_value = None
    current_user.updated_at = datetime.now(timezone.utc)
    delete_media(previous_upload, settings)
    return profile_payload(current_user)


@router.get("/me/preferences", response_model=PreferenceResponse)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return _preference_payload(await _preferences(db, current_user))


@router.put("/me/preferences", response_model=PreferenceResponse)
async def update_preferences(
    payload: PreferenceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    values = payload.model_dump(exclude_none=True)
    if not values:
        return _preference_payload(await _preferences(db, current_user))
    goal_fields = {
        key: value
        for key, value in values.items()
        if key in {"daily_goal_minutes", "daily_review_target", "weekly_goal_days", "timezone_name"}
    }
    try:
        preference = await goal_service.sync_profile_preferences(
            db, current_user, goal_fields, now=datetime.now(timezone.utc)
        )
    except goal_service.GoalValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    for key, value in values.items():
        if key in goal_fields:
            continue
        setattr(preference, key, value)
    preference.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _preference_payload(preference)
