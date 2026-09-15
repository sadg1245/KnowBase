"""KnowBase FastAPI 应用入口。"""

import os
import socket
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.models.base import Base, async_session_factory, engine
from app.core.migrations import run_compat_migrations
from app.services.hybrid_retrieval import backfill_keyword_index
import app.models  # noqa: F401 - register every ORM model before create_all


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动/关闭生命周期钩子。"""
    logger.info("KnowBase backend starting up...")

    # 确保数据目录存在
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")), exist_ok=True)

    # 创建所有数据库表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_compat_migrations(conn)
    logger.info("Database tables created / verified.")

    # 尝试连接 ChromaDB（不可用时不阻断启动）
    try:
        with socket.create_connection((settings.CHROMA_HOST, settings.CHROMA_PORT), timeout=1):
            pass
        logger.info(
            "ChromaDB connected at {}:{}",
            settings.CHROMA_HOST,
            settings.CHROMA_PORT,
        )
        import chromadb
        chroma_client = chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT)
        async with async_session_factory() as session:
            inserted = await backfill_keyword_index(session, chroma_client)
            await session.commit()
        if inserted:
            logger.info("Backfilled {} existing chunks into the keyword index.", inserted)
    except Exception as exc:
        logger.warning(
            "ChromaDB not available ({}). Vector search will fail until ChromaDB is running.",
            exc,
        )

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
from app.api.routes import workspaces, documents, search, settings as settings_route, learning, learning_insights, auth, chat_sessions, assessments  # noqa: E402

app.include_router(workspaces.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(settings_route.router, prefix="/api")
app.include_router(learning_insights.router, prefix="/api")
app.include_router(learning.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(chat_sessions.router, prefix="/api")
app.include_router(assessments.router, prefix="/api")


@app.middleware("http")
async def protect_private_api(request: Request, call_next):
    """Protect the whole private vault when AUTH_ENABLED is turned on."""
    if not settings.AUTH_ENABLED or not request.url.path.startswith("/api/") or request.url.path.startswith("/api/auth/"):
        return await call_next(request)
    from app.core.auth import verify_token
    service_token = request.headers.get("X-KnowBase-Service-Token", "")
    if settings.SERVICE_TOKEN and service_token == settings.SERVICE_TOKEN:
        return await call_next(request)
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    if not token or not verify_token(token):
        return JSONResponse({"detail": "请先解锁私人知识库"}, status_code=401)
    return await call_next(request)

# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


@app.get("/", tags=["health"])
async def health_check() -> dict:
    """简单的存活探针。"""
    return {"status": "ok", "service": "KnowBase API", "version": "0.1.0"}
