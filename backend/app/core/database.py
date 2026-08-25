"""为 Celery 任务和其他非 FastAPI 上下文提供数据库会话。"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import async_session_factory


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """获取异步数据库会话（非 FastAPI 依赖注入场景使用）。"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
