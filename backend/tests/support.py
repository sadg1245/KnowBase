"""Shared fixtures for Phase-1 account and ownership tests."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password
from app.models.user import LearningPreference, User
from app.models.workspace import Workspace


TEST_PASSWORD = "correct-horse-battery"


async def create_user(
    db: AsyncSession,
    *,
    username: str | None = None,
    display_name: str = "学习者",
    password: str | None = TEST_PASSWORD,
    is_active: bool = True,
) -> User:
    """Create a real account row; two calls produce two isolated users."""
    user = User(
        username=username or f"user-{uuid.uuid4().hex[:8]}",
        display_name=display_name,
        password_hash=hash_password(password) if password else None,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


async def create_preferences(db: AsyncSession, user: User, **values) -> LearningPreference:
    preference = LearningPreference(user_id=user.id, **values)
    db.add(preference)
    await db.flush()
    return preference


async def create_workspace(
    db: AsyncSession,
    user: User,
    *,
    name: str = "Docs",
    slug: str | None = None,
    **values,
) -> Workspace:
    workspace = Workspace(
        owner_id=user.id,
        name=name,
        slug=slug or f"ws-{uuid.uuid4().hex[:8]}",
        **values,
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def single_owner(db: AsyncSession) -> User:
    """Return the only account, creating it when a test needs a bare owner."""
    existing = (await db.execute(select(User).order_by(User.created_at).limit(1))).scalar_one_or_none()
    if existing is not None:
        return existing
    return await create_user(db)


def wire_test_app(sessions, db):
    """把测试会话接到 ASGI 应用，并返回可直接发起请求的客户端。

    认证中间件会使用注入的会话工厂解析令牌，因此测试走真实的认证路径。
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_db
    from app.main import app

    async def database():
        yield db
        await db.commit()

    app.dependency_overrides[get_db] = database
    app.state.session_factory = sessions
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def login(client, username: str, password: str = TEST_PASSWORD) -> dict:
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
