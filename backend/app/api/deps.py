"""FastAPI 路由的依赖注入辅助函数。"""

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.models.base import get_db as _get_db


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """生成异步 SQLAlchemy 会话（从 models.base 重新导出）。"""
    async for session in _get_db():
        yield session


def get_settings() -> Settings:
    """返回全局应用配置单例。"""
    return settings
