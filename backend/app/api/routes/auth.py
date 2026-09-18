"""首次建号、登录与退出端点（单账号部署，多用户数据结构）。

公开路由只有：认证状态、首次设置、登录。其余 `/api` 路由都需要有效令牌，
并且服务端只从认证状态识别用户。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.auth import create_token, hash_password, verify_password
from app.core.media import public_image_url
from app.models.user import LearningPreference, User
from app.schemas.account import AuthStatus, LoginRequest, SessionResponse, SetupRequest


router = APIRouter(prefix="/auth", tags=["auth"])

PLACEHOLDER_USERNAME = "__pending_setup__"


def profile_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar_kind": user.avatar_kind or "none",
        "avatar_url": public_image_url("avatar", user.avatar_kind, user.avatar_value),
        "created_at": user.created_at,
    }


async def count_users(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count(User.id))) or 0)


async def load_single_user(db: AsyncSession) -> User | None:
    return (await db.execute(select(User).order_by(User.created_at).limit(1))).scalar_one_or_none()


async def create_default_preferences(db: AsyncSession, user: User) -> LearningPreference:
    preference = await db.get(LearningPreference, user.id)
    if preference is None:
        preference = LearningPreference(user_id=user.id)
        db.add(preference)
        await db.flush()
    return preference


def _setup_allowed(users: int, user: User | None) -> bool:
    """是否允许首次建号。

    允许两种情况：
    - 还没有任何用户；
    - 只有一条"还没设过密码"的记录（旧库迁移出的 `owner`，或待设置的占位所有者），
      建号时把它补全，避免出现"既提示建号、建号又被拒绝"的死角。
    """
    if users == 0:
        return True
    return users == 1 and user is not None and not user.password_hash


@router.get("/status", response_model=AuthStatus)
async def auth_status(db: AsyncSession = Depends(get_db)) -> dict:
    """只返回是否已建号，不泄露任何账号信息。"""
    users = await count_users(db)
    user = await load_single_user(db) if users else None
    configured = bool(user and user.password_hash and user.username != PLACEHOLDER_USERNAME)
    return {"configured": configured, "setup_required": not configured, "login_required": True}


@router.post("/setup", response_model=SessionResponse, status_code=201)
async def setup(payload: SetupRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """首次建号：只在没有可用账号时成功，其余返回 409。"""
    username = payload.username.strip()
    display_name = (payload.display_name or "").strip() or "学习者"
    if not username:
        raise HTTPException(422, "用户名不能为空")

    users = await count_users(db)
    current = await load_single_user(db) if users else None
    if not _setup_allowed(users, current):
        raise HTTPException(409, "账号已存在，请直接登录")

    if current is not None:
        user = current
    else:
        user = User(username=username, display_name=display_name)
        db.add(user)
        await db.flush()

    user.username = username
    user.display_name = display_name
    user.password_hash = hash_password(payload.password)
    user.is_active = True
    await create_default_preferences(db, user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("Concurrent setup attempt rejected: {}", exc.orig)
        raise HTTPException(409, "账号已存在，请直接登录") from exc
    await db.refresh(user)
    logger.info("Created the single account '{}'", user.username)
    return {"token": create_token(user.id), "user": profile_payload(user)}


@router.post("/login", response_model=SessionResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """用户名 + 密码登录；失败信息统一，不暴露账号是否存在。"""
    user = (await db.execute(
        select(User).where(User.username == payload.username.strip())
    )).scalar_one_or_none()
    if (
        user is None
        or not user.password_hash
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(401, "用户名或密码错误")
    return {"token": create_token(user.id), "user": profile_payload(user)}


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)) -> dict:
    """第一阶段为统一客户端退出语义；客户端同时删除本地令牌。"""
    return {"detail": "已退出登录", "user_id": current_user.id}
