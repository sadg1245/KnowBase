"""系统设置与配置端点。"""

import os
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.config import Settings
from app.core.app_settings_store import has_llm_api_key
from app.core.app_settings_store import save as save_app_settings
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace
from app.services.llm_completion import call_completion, completion_kwargs, response_content
from app.schemas.schemas import (
    EmbeddingSettings,
    EmbeddingSettingsUpdate,
    FeishuSettings,
    LLMSettings,
    LLMSettingsUpdate,
    LLMTestRequest,
    LLMTestResponse,
    SettingsResponse,
    SystemInfoResponse,
)


router = APIRouter(prefix="/settings", tags=["settings"])
_START_TIME = time.monotonic()


def _mask_key(key: Optional[str]) -> Optional[str]:
    """对 API 密钥进行脱敏处理，仅显示前 4 位和后 4 位字符。"""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _human_readable_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的字符串。"""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


def _calculate_upload_size(upload_dir: str) -> int:
    """遍历上传目录并汇总所有文件大小。"""
    total = 0
    if not os.path.isdir(upload_dir):
        return 0
    for dirpath, dirnames, filenames in os.walk(upload_dir):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# GET /settings/llm — 获取 LLM 配置
# ---------------------------------------------------------------------------


@router.get("/llm", response_model=LLMSettings)
async def get_llm_settings(
    settings: Settings = Depends(get_settings),
) -> dict:
    """返回当前 LLM 配置，API 密钥已脱敏。"""
    # 根据 provider 确定当前使用的 API 密钥
    provider = settings.DEFAULT_LLM_PROVIDER.lower()
    active_key: Optional[str] = None
    if provider == "deepseek":
        active_key = settings.DEEPSEEK_API_KEY
    elif provider == "openai":
        active_key = settings.OPENAI_API_KEY
    elif provider == "dashscope":
        active_key = settings.DASHSCOPE_API_KEY
    elif provider == "zhipu":
        active_key = settings.ZHIPU_API_KEY

    return {
        "provider": settings.DEFAULT_LLM_PROVIDER,
        "model": settings.DEFAULT_LLM_MODEL,
        "api_key_masked": _mask_key(active_key),
        "base_url": settings.OLLAMA_BASE_URL,
        "configured": has_llm_api_key(settings),
    }


# ---------------------------------------------------------------------------
# PUT /settings/llm — 更新 LLM 配置
# ---------------------------------------------------------------------------


@router.put("/llm", response_model=LLMSettings)
async def update_llm_settings(
    payload: LLMSettingsUpdate,
    settings: Settings = Depends(get_settings),
) -> dict:
    """更新 LLM 提供商、模型，并可选择设置 API 密钥。

    修改会写入应用主目录下的本地配置文件，重启后依然生效。
    密钥只保存在本机，不会上传到任何服务器。
    """
    if payload.provider is not None:
        settings.DEFAULT_LLM_PROVIDER = payload.provider
    if payload.model is not None:
        settings.DEFAULT_LLM_MODEL = payload.model
    if payload.base_url is not None:
        settings.OLLAMA_BASE_URL = payload.base_url

    # 设置对应的 API 密钥
    if payload.api_key is not None:
        provider = settings.DEFAULT_LLM_PROVIDER.lower()
        if provider == "deepseek":
            settings.DEEPSEEK_API_KEY = payload.api_key
        elif provider == "openai":
            settings.OPENAI_API_KEY = payload.api_key
        elif provider == "dashscope":
            settings.DASHSCOPE_API_KEY = payload.api_key
        elif provider == "zhipu":
            settings.ZHIPU_API_KEY = payload.api_key

    logger.info(
        "LLM settings updated: provider={}, model={}",
        settings.DEFAULT_LLM_PROVIDER,
        settings.DEFAULT_LLM_MODEL,
    )
    save_app_settings(settings)

    active_key: Optional[str] = None
    provider = settings.DEFAULT_LLM_PROVIDER.lower()
    if provider == "deepseek":
        active_key = settings.DEEPSEEK_API_KEY
    elif provider == "openai":
        active_key = settings.OPENAI_API_KEY
    elif provider == "dashscope":
        active_key = settings.DASHSCOPE_API_KEY
    elif provider == "zhipu":
        active_key = settings.ZHIPU_API_KEY

    return {
        "provider": settings.DEFAULT_LLM_PROVIDER,
        "model": settings.DEFAULT_LLM_MODEL,
        "api_key_masked": _mask_key(active_key),
        "base_url": settings.OLLAMA_BASE_URL,
        "configured": has_llm_api_key(settings),
    }


# ---------------------------------------------------------------------------
# POST /settings/llm/test — 测试 LLM 连通性
# ---------------------------------------------------------------------------


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm_connectivity(
    payload: LLMTestRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    """通过发送简单提示词测试 LLM 连通性。

    使用提供的 provider/model/api_key，或回退到当前配置。
    """
    provider = (payload.provider or settings.DEFAULT_LLM_PROVIDER).lower()
    model = payload.model or settings.DEFAULT_LLM_MODEL
    api_key = payload.api_key

    if api_key is None:
        if provider == "deepseek":
            api_key = settings.DEEPSEEK_API_KEY
        elif provider == "openai":
            api_key = settings.OPENAI_API_KEY
        elif provider == "dashscope":
            api_key = settings.DASHSCOPE_API_KEY
        elif provider == "zhipu":
            api_key = settings.ZHIPU_API_KEY
        elif provider == "ollama":
            api_key = "ollama"

    if not api_key and provider != "ollama":
        raise HTTPException(
            status_code=400,
            detail=f"No API key configured for provider '{provider}'.",
        )

    try:
        import litellm

        # 与生成路径保持同一套映射：DeepSeek/通义/智谱都是 OpenAI 兼容端点，
        # 必须带上前缀与 base_url，否则请求会被发到错误的服务上。
        if provider == "ollama":
            litellm_model, api_base = f"ollama/{model}", settings.OLLAMA_BASE_URL
        elif provider == "deepseek":
            litellm_model, api_base = f"deepseek/{model}", "https://api.deepseek.com/v1"
        elif provider in {"dashscope", "qwen"}:
            litellm_model, api_base = f"openai/{model}", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        elif provider in {"zhipu", "glm"}:
            litellm_model, api_base = f"openai/{model}", "https://open.bigmodel.cn/api/paas/v4"
        else:
            litellm_model, api_base = model, None

        # 推理模型会先花掉一部分预算思考：预算只有 10 个 token 时正文一定是空的，
        # 这里按回答“一句话”给足余量，并把空正文当作失败上报。
        kwargs = completion_kwargs(
            model=litellm_model,
            api_key=api_key,
            api_base=api_base,
            prompt="Say 'hello' in one word.",
            provider=provider,
            max_tokens=512,
            temperature=0.2,
            timeout=60,
        )

        start = time.time()
        response = await call_completion(litellm.acompletion, kwargs)
        elapsed_ms = (time.time() - start) * 1000

        content = response_content(response)

        logger.info(
            "LLM test succeeded: provider={}, model={}, latency={:.0f}ms",
            provider,
            model,
            elapsed_ms,
        )
        return {
            "success": True,
            "message": f"LLM responded: '{content.strip()}'",
            "latency_ms": round(elapsed_ms, 2),
        }

    except Exception as exc:
        logger.error("LLM test failed: provider={}, model={}, error={}", provider, model, exc)
        return {
            "success": False,
            "message": f"Connection failed: {exc}",
            "latency_ms": None,
        }


# ---------------------------------------------------------------------------
# GET /settings/embedding — 获取嵌入模型配置
# ---------------------------------------------------------------------------


@router.get("/embedding", response_model=EmbeddingSettings)
async def get_embedding_settings(
    settings: Settings = Depends(get_settings),
) -> dict:
    """返回当前嵌入模型配置。"""
    return {
        "provider": settings.DEFAULT_EMBEDDING_PROVIDER,
        "model": settings.DEFAULT_EMBEDDING,
        "dimension": None,
    }


# ---------------------------------------------------------------------------
# PUT /settings/embedding — 更新嵌入模型配置
# ---------------------------------------------------------------------------


@router.put("/embedding", response_model=EmbeddingSettings)
async def update_embedding_settings(
    payload: EmbeddingSettingsUpdate,
    settings: Settings = Depends(get_settings),
) -> dict:
    """更新嵌入模型。

    注意：更换嵌入模型后需要对所有文档重新建立索引。
    修改会写入应用主目录下的本地配置文件，重启后依然生效。
    """
    if payload.provider is not None:
        settings.DEFAULT_EMBEDDING_PROVIDER = payload.provider
        if payload.model is None:
            from app.core.embedding import EmbeddingService

            settings.DEFAULT_EMBEDDING = EmbeddingService.DEFAULT_MODELS.get(
                payload.provider, settings.DEFAULT_EMBEDDING
            )
    if payload.model is not None:
        old_model = settings.DEFAULT_EMBEDDING
        settings.DEFAULT_EMBEDDING = payload.model
        logger.info(
            "Embedding model changed: {} -> {}. "
            "Existing vectors may need re-indexing.",
            old_model,
            payload.model,
        )
    save_app_settings(settings)

    return {
        "provider": settings.DEFAULT_EMBEDDING_PROVIDER,
        "model": settings.DEFAULT_EMBEDDING,
        "dimension": None,
    }


# ---------------------------------------------------------------------------
# GET /settings/system — 获取系统信息
# ---------------------------------------------------------------------------


@router.get("/system", response_model=SystemInfoResponse)
async def get_system_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """返回系统汇总信息。"""
    owned = select(Workspace.id).where(Workspace.owner_id == current_user.id)
    # 文档数量
    doc_count_stmt = select(func.count(Document.id)).where(Document.workspace_id.in_(owned))
    doc_count_result = await db.execute(doc_count_stmt)
    document_count = doc_count_result.scalar() or 0

    # 工作区数量
    ws_count_stmt = select(func.count(Workspace.id)).where(Workspace.owner_id == current_user.id)
    ws_count_result = await db.execute(ws_count_stmt)
    workspace_count = ws_count_result.scalar() or 0

    chunk_count_stmt = select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
        Document.workspace_id.in_(owned)
    )
    chunk_count_result = await db.execute(chunk_count_stmt)
    total_chunks = chunk_count_result.scalar() or 0

    # 已用存储空间
    storage_bytes = _calculate_upload_size(settings.UPLOAD_DIR)

    return {
        "version": "0.1.0",
        "document_count": document_count,
        "workspace_count": workspace_count,
        "total_chunks": total_chunks,
        "backend_uptime": int(time.monotonic() - _START_TIME),
        "storage_used_bytes": storage_bytes,
        "storage_used_human": _human_readable_size(storage_bytes),
    }
