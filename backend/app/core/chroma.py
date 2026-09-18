"""ChromaDB 客户端工厂。

本地优先：默认以**嵌入模式**运行在应用进程内，数据放在 `<应用主目录>/chroma`，
用户不需要部署任何向量数据库服务。
自托管/容器部署仍可通过 `CHROMA_HOST` / `CHROMA_PORT` 指向远程服务。
"""

from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.config import Settings, settings as global_settings
from app.core.app_paths import ensure_directory


_client: Optional[Any] = None


def describe_backend(config: Settings | None = None) -> str:
    target = config or global_settings
    if target.local_chroma_enabled:
        return f"embedded({target.CHROMA_DIR})"
    return f"http({target.CHROMA_HOST}:{target.CHROMA_PORT})"


def _build_client(config: Settings):
    import chromadb

    if config.local_chroma_enabled:
        ensure_directory(config.CHROMA_DIR)
        try:
            client_settings = chromadb.Settings(anonymized_telemetry=False)
            return chromadb.PersistentClient(path=config.CHROMA_DIR, settings=client_settings)
        except TypeError:  # pragma: no cover - 兼容不同版本的 chromadb
            return chromadb.PersistentClient(path=config.CHROMA_DIR)

    client = chromadb.HttpClient(host=config.CHROMA_HOST, port=config.CHROMA_PORT)
    client.heartbeat()
    return client


def get_chroma_client(config: Settings | None = None):
    """返回进程内共享的 ChromaDB 客户端；嵌入模式首次调用时创建本地目录。"""
    global _client
    target = config or global_settings
    if config is None and _client is not None:
        return _client
    client = _build_client(target)
    if config is None:
        _client = client
    return client


def reset_chroma_client() -> None:
    """测试或切换配置时清理单例。"""
    global _client
    _client = None


def initialize_chroma_client(config: Settings | None = None) -> Optional[Any]:
    """启动时预热客户端；失败只记录告警，不阻断 API 启动。"""
    target = config or global_settings
    try:
        client = get_chroma_client(config)
    except Exception as exc:
        logger.warning(
            "向量检索暂不可用（{}）：{}。上传与学习功能仍可使用，检索会在恢复后自动生效。",
            describe_backend(target),
            exc,
        )
        return None
    logger.info("向量库已就绪：{}", describe_backend(target))
    return client
