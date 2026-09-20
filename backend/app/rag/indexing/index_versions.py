"""索引指纹（设计文档 §15.2）。

collection metadata 记录 `embedding_model / embedding_dimension / chunk_schema_version /
distance`；指纹不一致时该知识库标记 `index_stale`，检索仍可用但会在证据事件里提示。
维度变化必须整 collection 重建，因此指纹比较把维度单独列为 gap。
"""

from __future__ import annotations

from typing import Any

CHUNK_SCHEMA_VERSION = 2


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
    stored = metadata.get("knowbase_index")
    return dict(stored) if isinstance(stored, dict) else {}


def write_fingerprint(collection, fingerprint: dict[str, Any]) -> None:
    """把指纹写进 collection metadata（与 hnsw:space 等既有键合并）。"""
    metadata = dict(getattr(collection, "metadata", None) or {})
    metadata["knowbase_index"] = dict(fingerprint)
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

