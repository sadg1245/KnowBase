"""FastAPI 路由的依赖注入辅助函数。"""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.core.auth import decode_token
from app.models.base import get_db as _get_db
from app.models.user import User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """生成异步 SQLAlchemy 会话（从 models.base 重新导出）。"""
    async for session in _get_db():
        yield session


def get_settings() -> Settings:
    """返回全局应用配置单例。"""
    return settings


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """从认证状态识别用户；令牌无效、过期、用户不存在或停用统一 401。

    客户端提交的任何 `user_id` 都不会进入这里——归属只由令牌 `sub` 决定。
    认证中间件已完成令牌或服务令牌到用户 ID 的解析；这里在请求自身的会话中
    加载该用户，使路由对资料字段的修改随本次请求一起提交。
    """
    user_id = getattr(request.state, "current_user_id", None)
    if not user_id:
        token = bearer_token(request)
        payload = decode_token(token) if token else None
        user_id = payload["sub"] if payload else None
    if not user_id:
        raise HTTPException(401, "请先登录私人知识库")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "登录状态已失效，请重新登录")
    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    user_id = getattr(request.state, "current_user_id", None)
    if not user_id:
        token = bearer_token(request)
        payload = decode_token(token) if token else None
        user_id = payload["sub"] if payload else None
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def log_owner_scope(route: str, user: User) -> None:
    logger.debug("Scoped '{}' to user '{}'", route, user.id)
