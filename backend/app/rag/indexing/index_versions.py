"""索引指纹（设计文档 §15.2）。

collection metadata 记录 `embedding_model / embedding_dimension / chunk_schema_version /
distance`；指纹不一致时该知识库标记 `index_stale`，检索仍可用但会在证据事件里提示。
维度变化必须整 collection 重建，因此指纹比较把维度单独列为 gap。
"""

from __future__ import annotations

import json
from typing import Any

CHUNK_SCHEMA_VERSION = 2

# ChromaDB 的 collection metadata 不接受嵌套 dict，因此指纹按键前缀摊平存储。
# 早期实现直接写入 `knowbase_index: {...}`，写入必然失败（只有告警），这里保留读取兼容。
FINGERPRINT_PREFIX = "knowbase_index_"


def index_fingerprint(
    *, embedding_model: str, embedding_dimension: int | None, distance: str = "cosine"
) -> dict[str, Any]:
    return {
        "embedding_model": embedding_model,
        "embedding_dimension": int(embedding_dimension or 0),
        "chunk_schema_version": CHUNK_SCHEMA_VERSION,
        "distance": distance,
    }


def current_fingerprint(settings, embedding_service=None) -> dict[str, Any]:
    model = (
        getattr(settings, "DEFAULT_EMBEDDING", "")
        or getattr(settings, "DEFAULT_EMBEDDING_MODEL", "")
        or "unknown"
    )
    dimension = None
    if embedding_service is not None and hasattr(embedding_service, "get_dimension"):
        try:
            dimension = embedding_service.get_dimension()
        except Exception:  # 模型未加载时维度未知，指纹按 0 处理
            dimension = None
    return index_fingerprint(embedding_model=model, embedding_dimension=dimension)


def read_fingerprint(collection) -> dict[str, Any]:
    metadata = getattr(collection, "metadata", None) or {}
    stored: dict[str, Any] = {
        str(key)[len(FINGERPRINT_PREFIX):]: value
        for key, value in metadata.items()
        if isinstance(key, str) and key.startswith(FINGERPRINT_PREFIX)
    }
    legacy = metadata.get("knowbase_index")
    if isinstance(legacy, dict):
        return {**legacy, **stored}
    return stored


def write_fingerprint(collection, fingerprint: dict[str, Any]) -> None:
    """把指纹摊平成标量键写进 collection metadata。

    两个实测约束（ChromaDB）：

    - metadata 不接受嵌套 dict，因此指纹按键前缀摊平；
    - `modify` 会整体替换 metadata，而带上 `hnsw:space` 又会被拒绝
      （"Changing the distance function ... is not supported"），
      所以这里保留其它既有键、但不再回写 `hnsw:space`。
      距离本身是不可变的，读侧改用指纹里的 `distance` 兜底。
    """
    metadata = {
        key: value
        for key, value in (getattr(collection, "metadata", None) or {}).items()
        if not (isinstance(key, str) and key.startswith(FINGERPRINT_PREFIX))
        and key != "hnsw:space"
    }
    for key, value in fingerprint.items():
        metadata[f"{FINGERPRINT_PREFIX}{key}"] = (
            value if isinstance(value, (str, int, float, bool)) else json.dumps(value, ensure_ascii=False)
        )
    collection.modify(metadata=metadata)


def fingerprint_gap(stored: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """返回不一致项的人类可读原因；空列表表示指纹一致或尚未写入指纹。"""
    if not stored:
        return ["index_stale:missing_fingerprint"]
    gaps: list[str] = []
    if stored.get("embedding_model") != current.get("embedding_model"):
        gaps.append(
            f"index_stale:embedding_model {stored.get('embedding_model')} → {current.get('embedding_model')}"
        )
    if int(stored.get("embedding_dimension") or 0) != int(current.get("embedding_dimension") or 0):
        gaps.append("index_stale:embedding_dimension")
    if int(stored.get("chunk_schema_version") or 0) != int(current.get("chunk_schema_version") or 0):
        gaps.append("index_stale:chunk_schema_version")
    if (stored.get("distance") or "cosine") != (current.get("distance") or "cosine"):
        gaps.append("index_stale:distance")
    return gaps


def collection_is_stale(collection, current: dict[str, Any]) -> bool:
    return bool(fingerprint_gap(read_fingerprint(collection), current))
