"""Parent Expansion（§11.3）：子块命中 → 父块整节；父块过大时退回子块 + 相邻子块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat import DocumentChunk
from app.rag.chunking.base import estimate_tokens

NEIGHBOR_LIMIT = 1


@dataclass
class ExpandedItem:
    chunk_id: str
    content: str
    source_file: str = ""
    page_num: int | None = None
    heading: str | None = None
    workspace_id: str | None = None
    document_id: str | None = None
    expanded_from: str | None = None
    parent_id: str | None = None
    citation_index: int | None = None
    neighbors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ExpansionOutcome:
    items: list[ExpandedItem]
    reasons: list[str] = field(default_factory=list)
    shared_parents: int = 0


def _view(row: DocumentChunk, *, expanded_from: str | None = None) -> ExpandedItem:
    return ExpandedItem(
        chunk_id=row.id,
        content=row.content or "",
        source_file=row.source_file or "",
        page_num=row.page_num,
        heading=row.heading,
        workspace_id=row.workspace_id,
        document_id=row.document_id,
        expanded_from=expanded_from,
        parent_id=row.parent_id,
    )


def _as_item(item) -> ExpandedItem:
    if isinstance(item, ExpandedItem):
        return item

    def field(name, default=None):
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    return ExpandedItem(
        chunk_id=str(field("chunk_id", "") or ""),
        content=str(field("content", "") or ""),
        source_file=str(field("source_file", "") or ""),
        page_num=field("page_num", None),
        heading=field("heading", None),
    )


async def expand_parents(
    db: AsyncSession,
    items: Sequence,
    *,
    max_parent_tokens: int | None = None,
) -> ExpansionOutcome:
    """把命中的 child 替换为父块正文；同一父块在结果中只保留一次。"""
    limit = max_parent_tokens or settings.RAG_PARENT_MAX_TOKENS
    child_ids = [str(getattr(item, "chunk_id", "") or "") for item in items]
    if not child_ids:
        return ExpansionOutcome(items=[])
    rows = {
        row.id: row
        for row in (
            await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(child_ids)))
        ).scalars().all()
    }
    parent_ids = {row.parent_id for row in rows.values() if row.parent_id}
    parents = {
        row.id: row
        for row in (
            await db.execute(select(DocumentChunk).where(DocumentChunk.id.in_(parent_ids)))
        ).scalars().all()
    } if parent_ids else {}

    outcome = ExpansionOutcome(items=[])
    seen_parents: set[str] = set()
    for position, item in enumerate(items, 1):
        child = rows.get(str(getattr(item, "chunk_id", "") or ""))
        if child is None:
            detached = _as_item(item)
            detached.citation_index = detached.citation_index or position
            outcome.items.append(detached)
            continue
        parent = parents.get(child.parent_id) if child.parent_id else None
        if parent is None:
            bare = _view(child)
            bare.citation_index = position
            outcome.items.append(bare)
            continue
        if child.parent_id in seen_parents:
            outcome.shared_parents += 1
            outcome.reasons.append(f"shared_parent:{child.parent_id}")
            continue
        if estimate_tokens(parent.content or "") <= limit:
            seen_parents.add(child.parent_id)
            outcome.items.append(_view(parent, expanded_from=child.id))
            outcome.items[-1].citation_index = position
            continue
        # 父块超预算：退回子块并附相邻子块各一条，避免单个来源挤占上下文
        neighbors = list((
            await db.execute(
                select(DocumentChunk)
                .where(
                    DocumentChunk.parent_id == child.parent_id,
                    DocumentChunk.chunk_level == "child",
                    DocumentChunk.id != child.id,
                )
                .order_by(DocumentChunk.chunk_index.asc())
                .limit(NEIGHBOR_LIMIT * 2)
            )
        ).scalars().all())
        fallback = _view(child)
        fallback.notes.append("parent_over_budget")
        fallback.neighbors = [row.id for row in neighbors]
        fallback.citation_index = position
        outcome.items.append(fallback)
        outcome.reasons.append(f"parent_over_budget:{child.parent_id}")
    return outcome
