"""多向量展开（设计文档 §14）：单 collection + `vector_kind` 元数据。

- `content`：chunk 原文，必开；
- `summary`：富化摘要，仅白名单 content_type 生成；
- `question`：富化 questions（1–3 条），同样只覆盖白名单类型。

同一条 chunk 的多个 kind 共享逻辑 `chunk_id`，检索时按 `chunk_id` 归并。
"""

from __future__ import annotations

import json
from typing import Iterable

MULTIVECTOR_CONTENT_TYPES = frozenset({"concept", "definition", "formula", "question", "solution"})
SUPPORTED_VECTOR_KINDS = frozenset({"content", "summary", "question"})


def parse_vector_kinds(value: str | Iterable[str] | None) -> list[str]:
    """把配置（逗号分隔字符串或可迭代）解析成受支持的 kind 顺序列表。"""
    if value is None:
        return ["content"]
    raw = value.split(",") if isinstance(value, str) else list(value)
    kinds: list[str] = []
    for item in raw:
        kind = str(item).strip().lower()
        if kind in SUPPORTED_VECTOR_KINDS and kind not in kinds:
            kinds.append(kind)
    # content 向量是必开项，永远排在最前
    if "content" in kinds:
        kinds.remove("content")
    kinds.insert(0, "content")
    return kinds


def _scalar(value):
    """Chroma metadata 只接受标量：列表 / 字典转成 JSON 字符串。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False)


def expand_child_vectors(
    rows: list[dict], *, kinds: Iterable[str], include_content: bool = True
) -> tuple[list[str], list[str], list[dict]]:
    """把 child chunk 行展开成 (ids, texts, metadatas)。

    `rows` 是流水线的 chunk dict（`content` + `metadata`），metadata 至少包含
    `chunk_id`；`summary` / `questions` / `content_type` 由富化阶段填充。
    """
    active = set(parse_vector_kinds(list(kinds)))
    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    for index, row in enumerate(rows):
        meta = dict(row.get("metadata") or {})
        chunk_id = str(meta.get("chunk_id") or f"chunk_{index}")
        content = str(row.get("content") or "")
        content_type = str(meta.get("content_type") or "concept")
        base_meta = {
            **{key: _scalar(value) for key, value in meta.items()},
            "chunk_id": chunk_id,
            "vector_kind": "content",
            "content_type": content_type,
        }
        if include_content:
            ids.append(chunk_id)
            texts.append(content)
            metadatas.append(base_meta)

        if content_type not in MULTIVECTOR_CONTENT_TYPES:
            continue
        summary = str(meta.get("summary") or "").strip()
        if "summary" in active and summary:
            ids.append(f"{chunk_id}#summary")
            texts.append(summary)
            metadatas.append({**base_meta, "vector_kind": "summary"})
        if "question" in active:
            for question_index, question in enumerate(meta.get("questions") or []):
                text = str(question).strip()
                if not text:
                    continue
                ids.append(f"{chunk_id}#question{question_index}")
                texts.append(text)
                metadatas.append({**base_meta, "vector_kind": "question"})
    return ids, texts, metadatas


def logical_chunk_id(vector_id: str, metadata: dict | None = None) -> str:
    """从向量记录 id 还原逻辑 chunk id（去掉 `#summary` / `#questionN` 后缀）。"""
    meta = metadata or {}
    explicit = meta.get("chunk_id")
    if explicit:
        return str(explicit)
    return str(vector_id).split("#", 1)[0]
