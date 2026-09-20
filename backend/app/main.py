"""KnowBase FastAPI 应用入口。"""

import hmac
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.models.base import Base, async_session_factory, engine
from app.core.app_settings_store import apply_persisted
from app.core.auth import decode_token
from app.core.chroma import initialize_chroma_client
from app.core.db_bootstrap import ensure_database_ready
from app.core.media import resolve_media_path
from app.core.migrations import ensure_memory_index, ensure_search_index
from app.core.secrets_store import resolve_jwt_secret
from app.services.hybrid_retrieval import backfill_keyword_index
import app.models  # noqa: F401 - register every ORM model before create_all


async def _backfill_search_index(chroma_client) -> None:
    """把已有向量片段补进 SQLite 关键词索引；检索不可用时静默跳过。"""
    if chroma_client is None:
        return
    async with async_session_factory() as session:
        inserted = await backfill_keyword_index(session, chroma_client)
        await session.commit()
    if inserted:
        logger.info("Backfilled {} existing chunks into the keyword index.", inserted)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动/关闭生命周期钩子。"""
    logger.info("KnowBase backend starting up...")

    # 应用主目录：所有用户数据（数据库、上传、媒体、向量库、密钥、备份）都在这里
    os.makedirs(settings.DATA_ROOT, exist_ok=True)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_DIR, "avatars"), exist_ok=True)
    os.makedirs(os.path.join(settings.MEDIA_DIR, "covers"), exist_ok=True)
    database_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    if database_path != settings.DATABASE_URL:
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
    logger.info("数据目录：{}", settings.DATA_ROOT)

    # 令牌签名密钥由程序自管：未配置或不安全时自动生成并持久化，用户不需要关心
    secret = resolve_jwt_secret(settings)
    settings.JWT_SECRET = secret.value

    # 用户自己的模型配置（含 API Key）从本机读取，重启后依然生效
    if apply_persisted(settings):
        logger.info("已载入本机保存的模型配置。")

    # 数据库结构由 Alembic 管理：旧库先经受控引导，再升级到 head。
    # 升级前自动备份，用户不需要手动操作；迁移失败时直接抛出，API 不会带着旧结构启动。
    report = await ensure_database_ready(
        settings.DATABASE_URL, backup_dir=settings.BACKUPS_DIR
    )
    logger.info("Database bootstrap action='{}' revision='{}'.", report.action, report.revision)
    async with engine.begin() as conn:
        await ensure_search_index(conn)
        await ensure_memory_index(conn)

    # 向量库：默认嵌入模式，不依赖外部服务；不可用时不阻断启动
    chroma_client = initialize_chroma_client(settings)
    try:
        await _backfill_search_index(chroma_client)
    except Exception as exc:
        logger.warning("关键词索引补齐失败（{}），检索会在下次启动时重试。", exc)

    logger.info("KnowBase backend is ready.")
    yield
    await engine.dispose()
    logger.info("KnowBase backend shutting down.")


# ---------------------------------------------------------------------------
# 应用工厂
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KnowBase API",
    description="Personal knowledge database with RAG-powered search and chat.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — 开发环境允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
from app.api.routes import (  # noqa: E402
    assessments,
    auth,
    chat_sessions,
    documents,
    learning,
    learning_domains,
    learning_insights,
    me,
    rag,
    search,
    workspaces,
)
from app.api.routes import settings as settings_route  # noqa: E402

app.include_router(workspaces.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(settings_route.router, prefix="/api")
app.include_router(learning_insights.router, prefix="/api")
app.include_router(learning.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(chat_sessions.router, prefix="/api")
app.include_router(assessments.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(learning_domains.router, prefix="/api")
app.include_router(rag.router, prefix="/api")


def _public_path(path: str) -> bool:
    if path in settings.PUBLIC_API_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in settings.PUBLIC_API_PREFIXES)


def _auth_is_overridden(request: Request) -> bool:
    """显式的测试依赖覆盖可以绕过令牌解析，生产环境不会设置它。"""
    from app.api.deps import get_current_user

    return get_current_user in request.app.dependency_overrides


def _session_factory(request: Request):
    """测试可注入会话工厂；生产使用应用自身的引擎。"""
    return getattr(request.app.state, "session_factory", async_session_factory)


@app.middleware("http")
async def protect_private_api(request: Request, call_next):
    """认证保护默认覆盖私人 `/api` 路由。

    公开路由只有健康检查、认证状态、首次设置、登录，以及受控媒体读取。
    认证开关不能静默关闭数据隔离；服务令牌必须映射到明确用户。
    """
    path = request.url.path
    if not path.startswith("/api/") or _public_path(path):
        return await call_next(request)
    if _auth_is_overridden(request):
        return await call_next(request)

    from app.models.user import User

    service_token = request.headers.get("X-KnowBase-Service-Token", "")
    user: Optional[User] = None
    if settings.SERVICE_TOKEN and service_token and hmac.compare_digest(service_token, settings.SERVICE_TOKEN):
        async with _session_factory(request)() as session:
            user = (await session.execute(
                select(User).order_by(User.created_at).limit(1)
            )).scalar_one_or_none()
        if user is None:
            # 单账号部署默认绑定唯一用户；没有可绑定用户时不能退化为全库查询。
            return JSONResponse({"detail": "服务身份尚未绑定账号"}, status_code=503)
    else:
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        payload = decode_token(token) if token else None
        if payload is not None:
            async with _session_factory(request)() as session:
                user = await session.get(User, payload["sub"])

    if user is None or not user.is_active:
        return JSONResponse({"detail": "请先解锁私人知识库"}, status_code=401)
    request.state.current_user_id = user.id
    return await call_next(request)


# ---------------------------------------------------------------------------
# 受控媒体（头像与知识库封面）
# ---------------------------------------------------------------------------

_MEDIA_FOLDERS = {"avatars", "covers"}


@app.get("/api/media/{folder}/{filename}", tags=["media"])
async def read_media(folder: str, filename: str) -> FileResponse:
    """只提供受控目录中、由随机文件名标识的图片，不暴露任意目录。"""
    if folder not in _MEDIA_FOLDERS:
        raise HTTPException(status_code=404, detail="Media not found")
    path = resolve_media_path(f"{folder}/{filename}")
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(path)

# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/", tags=["health"])
async def health_check() -> dict:
    """简单的存活探针。"""
    return {"status": "ok", "service": "KnowBase API", "version": "0.1.0"}
