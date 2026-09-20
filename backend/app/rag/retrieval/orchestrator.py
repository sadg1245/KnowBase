"""查询侧编排（§21）：查询理解 → 路由计划 → 重排 → 父块扩展 → 上下文构建。

输出保持既有 SSE 契约：`sources` 仍是逐条命中的子块（引用编号不变），
而提示词上下文可以用父块整节替代（同一父块只出现一次，编号沿用首个命中的子块）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.query.analyzer import analyze_query
from app.rag.query.router import EXPLAIN_MODE, QueryPlan, plan_query
from app.rag.retrieval.context import (
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    build_context_blocks,
    render_context,
)
from app.rag.retrieval.parent import expand_parents
from app.rag.retrieval.reranker import Reranker


@dataclass
class PreparedRetrieval:
    plan: QueryPlan
    sources: list[dict] = field(default_factory=list)
    context_chunks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rerank_degraded: str | None = None
    excluded_for_mode: int = 0
    expanded_parents: int = 0


def _default_serializer(item) -> dict:
    return {
        "content": getattr(item, "content", ""),
        "source_file": getattr(item, "source_file", ""),
        "page_num": getattr(item, "page_num", None),
        "score": round(float(getattr(item, "rerank_score", 0.0) or 0.0), 4),
        "document_id": getattr(item, "document_id", None),
        "heading": getattr(item, "heading", None),
        "chunk_id": getattr(item, "chunk_id", ""),
    }


async def prepare_retrieval_context(
    db: AsyncSession,
    items: list,
    *,
    question: str,
    mode: str = EXPLAIN_MODE,
    plan: QueryPlan | None = None,
    reranker: Reranker | None = None,
    serializer=None,
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> PreparedRetrieval:
    plan = plan or plan_query(analyze_query(question), mode=mode)
    notes: list[str] = []

    kept: list = []
    for item in items:
        content_type = (getattr(item, "content_type", None) or "").strip()
        if content_type and content_type in plan.exclude_content_types:
            continue
        kept.append(item)
    prepared = PreparedRetrieval(plan=plan, excluded_for_mode=len(items) - len(kept))

    if plan.rerank_mode != "none" and kept:
        outcome = await (reranker or Reranker(mode=plan.rerank_mode)).rerank(question, kept)
        kept = outcome.items
        prepared.rerank_degraded = outcome.degraded_reason
        if outcome.degraded_reason:
            notes.append(f"rerank_degraded:{outcome.degraded_reason}")

    serialize = serializer or _default_serializer
    prepared.sources = [serialize(item) for item in kept]

    context_items = kept
    if plan.expand_parents and kept:
        expansion = await expand_parents(db, kept)
        context_items = expansion.items
        prepared.expanded_parents = sum(
            1 for item in context_items if getattr(item, "expanded_from", None)
        )
        notes.extend(expansion.reasons[:5])

    blocks, context_notes = build_context_blocks(context_items, token_budget=token_budget)
    prepared.context_chunks = render_context(blocks)
    notes.extend(context_notes)
    prepared.notes = notes
    return prepared
