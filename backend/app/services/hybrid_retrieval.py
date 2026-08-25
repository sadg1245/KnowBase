"""SQLite FTS5 + vector hybrid retrieval with deterministic evidence scoring."""

from __future__ import annotations

import re
import asyncio
import json
from dataclasses import dataclass
from collections.abc import Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import DocumentChunk, RetrievalHit, RetrievalRun
from app.models.document import Document
from app.models.workspace import Workspace


def _search_tokens(value: str) -> list[str]:
    cleaned = re.sub(r"[\x00-\x1f]+", " ", value).strip()
    if not cleaned:
        return []
    try:
        import jieba

        tokens = jieba.lcut_for_search(cleaned)
    except ImportError:
        tokens = []
        for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9_]+", cleaned):
            if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) > 2:
                tokens.extend(part[index:index + 2] for index in range(len(part) - 1))
            else:
                tokens.append(part)
    result: list[str] = []
    for token in tokens:
        token = token.strip()
        if token and token not in result:
            result.append(token)
    return result


def tokenize_for_search(value: str) -> str:
    """Return a space-separated representation suitable for the FTS column."""
    return " ".join(_search_tokens(value))


def build_fts_match_query(value: str) -> str:
    """Build an AND query where every token is a quoted FTS literal."""
    tokens = _search_tokens(value)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _section_path(value: object) -> list[str]:
    """Normalize stored or Chroma-serialized paths for the JSON DB column."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def weighted_rrf(
    vector_ids: Sequence[str],
    keyword_ids: Sequence[str],
    *,
    k: int = 60,
    vector_weight: float = 0.65,
    keyword_weight: float = 0.35,
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for rank, chunk_id in enumerate(vector_ids, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + vector_weight / (k + rank)
    for rank, chunk_id in enumerate(keyword_ids, 1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + keyword_weight / (k + rank)
    return scores


def rerank_score(
    *,
    rrf_norm: float,
    vector_norm: float,
    keyword_norm: float,
    structure_bonus: float,
) -> float:
    return (
        0.50 * rrf_norm
        + 0.30 * vector_norm
        + 0.15 * keyword_norm
        + 0.05 * structure_bonus
    )


def classify_evidence(
    scores: Sequence[float],
    *,
    strong_phrase: bool = False,
    supported_threshold: float = 0.58,
    second_threshold: float = 0.45,
    limited_threshold: float = 0.42,
) -> str:
    ordered = sorted(scores, reverse=True)
    if not ordered or ordered[0] < limited_threshold:
        return "insufficient"
    if ordered[0] >= supported_threshold and (
        strong_phrase or (len(ordered) > 1 and ordered[1] >= second_threshold)
    ):
        return "supported"
    return "limited"


async def upsert_document_chunks(
    db: AsyncSession,
    workspace_id: str,
    document_id: str,
    source_file: str,
    chunks: list[dict],
) -> int:
    """Synchronize parsed chunks with the keyword index using stable vector IDs."""
    existing = {
        row.id: row
        for row in (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == document_id))).scalars().all()
    }
    active_ids: list[str] = []
    for index, chunk in enumerate(chunks):
        chunk_id = f"{document_id}_chunk_{index}"
        active_ids.append(chunk_id)
        metadata = chunk.get("metadata") or {}
        content = str(chunk.get("content") or "")
        row = existing.get(chunk_id)
        if row is None:
            row = DocumentChunk(id=chunk_id, workspace_id=workspace_id, document_id=document_id)
            db.add(row)
        row.source_file = source_file
        row.page_num = metadata.get("page_num")
        row.heading = metadata.get("heading")
        row.heading_level = metadata.get("heading_level")
        row.section_path = _section_path(metadata.get("section_path"))
        row.chunk_index = index
        row.content = content
        row.tokenized_content = tokenize_for_search(content)
    stale_ids = set(existing) - set(active_ids)
    if stale_ids:
        await db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(stale_ids)))
    await db.flush()
    return len(active_ids)


async def backfill_keyword_index(db: AsyncSession, chroma_client, batch_size: int = 500) -> int:
    """Best-effort, repeatable migration of existing Chroma chunks into FTS5."""
    workspaces = list((await db.execute(select(Workspace))).scalars().all())
    valid_documents = {
        row.id: row
        for row in (await db.execute(select(Document).where(Document.status == "ready"))).scalars().all()
    }
    existing_ids = set((await db.execute(select(DocumentChunk.id))).scalars().all())
    inserted = 0
    for workspace in workspaces:
        collection_name = f"ws_{workspace.id}".replace("-", "_")
        try:
            collection = chroma_client.get_collection(name=collection_name)
            count = collection.count()
        except Exception:
            continue
        for offset in range(0, count, batch_size):
            page = collection.get(
                limit=min(batch_size, count - offset),
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids = page.get("ids") or []
            contents = page.get("documents") or []
            metadatas = page.get("metadatas") or []
            for index, chunk_id in enumerate(ids):
                if chunk_id in existing_ids:
                    continue
                metadata = metadatas[index] if index < len(metadatas) else {}
                document_id = metadata.get("doc_id", metadata.get("document_id"))
                document = valid_documents.get(document_id)
                if document is None or document.workspace_id != workspace.id:
                    continue
                content = contents[index] if index < len(contents) else ""
                db.add(DocumentChunk(
                    id=chunk_id,
                    workspace_id=workspace.id,
                    document_id=document.id,
                    source_file=metadata.get("source_file", document.filename),
                    page_num=metadata.get("page_num"),
                    heading=metadata.get("heading"),
                    heading_level=metadata.get("heading_level"),
                    section_path=_section_path(metadata.get("section_path")),
                    chunk_index=int(metadata.get("chunk_index", index)),
                    content=content,
                    tokenized_content=tokenize_for_search(content),
                ))
                existing_ids.add(chunk_id)
                inserted += 1
            await db.flush()
    return inserted


@dataclass
class RetrievalCandidate:
    chunk_id: str
    document_id: str | None
    source_file: str
    page_num: int | None
    heading: str | None
    content: str
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_score: float = 0.0
    keyword_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: float = 0.0
    final_rank: int | None = None


@dataclass
class HybridRetrievalResult:
    items: list[RetrievalCandidate]
    evidence_status: str
    run_id: str
    vector_succeeded: bool
    keyword_succeeded: bool
    degradation_reason: str
    top_score: float


def _normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: 1.0 if high > 0 else 0.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _structure_bonus(query: str, candidate: RetrievalCandidate) -> float:
    bonus = 0.0
    normalized_query = re.sub(r"\s+", "", query).lower()
    normalized_content = re.sub(r"\s+", "", candidate.content).lower()
    if normalized_query and normalized_query in normalized_content:
        bonus += 0.55
    heading = (candidate.heading or "").lower()
    if any(token.lower() in heading for token in _search_tokens(query)):
        bonus += 0.30
    return min(1.0, bonus)


class HybridRetrievalService:
    """Run vector and FTS recall, then persist a reproducible retrieval audit."""

    def __init__(self, db: AsyncSession, vector_recall) -> None:
        self.db = db
        self.vector_recall = vector_recall

    async def _keyword_recall(
        self,
        *,
        query: str,
        workspace_id: str,
        document_ids: list[str],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        match_query = build_fts_match_query(query)
        if not match_query:
            return []
        params: dict[str, object] = {
            "match_query": match_query,
            "workspace_id": workspace_id,
            "top_k": top_k,
        }
        document_filter = ""
        if document_ids:
            names = []
            for index, document_id in enumerate(dict.fromkeys(document_ids)):
                name = f"document_id_{index}"
                names.append(f":{name}")
                params[name] = document_id
            document_filter = f" AND c.document_id IN ({', '.join(names)})"
        statement = text(
            "SELECT c.id, c.document_id, c.source_file, c.page_num, c.heading, c.content, "
            "bm25(document_chunks_fts) AS keyword_rank_score "
            "FROM document_chunks_fts "
            "JOIN document_chunks c ON c.rowid = document_chunks_fts.rowid "
            "WHERE document_chunks_fts MATCH :match_query "
            "AND c.workspace_id = :workspace_id"
            f"{document_filter} "
            "ORDER BY keyword_rank_score ASC LIMIT :top_k"
        )
        rows = (await self.db.execute(statement, params)).mappings().all()
        return [
            RetrievalCandidate(
                chunk_id=row["id"],
                document_id=row["document_id"],
                source_file=row["source_file"],
                page_num=row["page_num"],
                heading=row["heading"],
                content=row["content"],
                keyword_rank=index,
                keyword_score=1.0 / (1.0 + abs(float(row["keyword_rank_score"] or 0.0))),
            )
            for index, row in enumerate(rows, 1)
        ]

    async def _vector_recall(
        self,
        *,
        query: str,
        workspace_id: str,
        document_ids: list[str],
        top_k: int,
    ) -> list[RetrievalCandidate]:
        rows = await self.vector_recall(
            query=query,
            workspace_id=workspace_id,
            document_ids=document_ids,
            top_k=top_k,
        )
        return [
            RetrievalCandidate(
                chunk_id=str(row.get("chunk_id") or row.get("id") or f"vector-{index}"),
                document_id=row.get("document_id"),
                source_file=row.get("source_file", "unknown"),
                page_num=row.get("page_num"),
                heading=row.get("heading"),
                content=row.get("content", ""),
                vector_rank=index,
                vector_score=max(0.0, min(1.0, float(row.get("score", 0.0)))),
            )
            for index, row in enumerate(rows, 1)
        ]

    async def retrieve(
        self,
        *,
        query: str,
        workspace_id: str,
        document_ids: list[str],
        session_id: str | None = None,
        user_message_id: str | None = None,
        vector_top_k: int = 20,
        keyword_top_k: int = 20,
        selected_top_k: int = 8,
        supported_threshold: float = 0.58,
        second_threshold: float = 0.45,
        limited_threshold: float = 0.42,
    ) -> HybridRetrievalResult:
        vector_result, keyword_result = await asyncio.gather(
            self._vector_recall(query=query, workspace_id=workspace_id, document_ids=document_ids, top_k=vector_top_k),
            self._keyword_recall(query=query, workspace_id=workspace_id, document_ids=document_ids, top_k=keyword_top_k),
            return_exceptions=True,
        )
        vector_succeeded = not isinstance(vector_result, Exception)
        keyword_succeeded = not isinstance(keyword_result, Exception)
        degradation = []
        if not vector_succeeded:
            degradation.append(f"向量检索不可用：{vector_result}")
            vector_items: list[RetrievalCandidate] = []
        else:
            vector_items = vector_result
        if not keyword_succeeded:
            degradation.append(f"关键词检索不可用：{keyword_result}")
            keyword_items: list[RetrievalCandidate] = []
        else:
            keyword_items = keyword_result

        candidates: dict[str, RetrievalCandidate] = {}
        for item in vector_items + keyword_items:
            current = candidates.get(item.chunk_id)
            if current is None:
                candidates[item.chunk_id] = item
                continue
            if item.vector_rank is not None:
                current.vector_rank = item.vector_rank
                current.vector_score = item.vector_score
            if item.keyword_rank is not None:
                current.keyword_rank = item.keyword_rank
                current.keyword_score = item.keyword_score
            if not current.content and item.content:
                current.content = item.content

        vector_ids = [item.chunk_id for item in vector_items]
        keyword_ids = [item.chunk_id for item in keyword_items]
        fusion = weighted_rrf(vector_ids, keyword_ids)
        fusion_norm = _normalize(fusion)
        vector_norm = _normalize({item.chunk_id: item.vector_score for item in candidates.values()})
        keyword_norm = _normalize({item.chunk_id: item.keyword_score for item in candidates.values()})
        for item in candidates.values():
            item.fusion_score = fusion.get(item.chunk_id, 0.0)
            item.rerank_score = rerank_score(
                rrf_norm=fusion_norm.get(item.chunk_id, 0.0),
                vector_norm=vector_norm.get(item.chunk_id, 0.0),
                keyword_norm=keyword_norm.get(item.chunk_id, 0.0),
                structure_bonus=_structure_bonus(query, item),
            )

        ranked = sorted(candidates.values(), key=lambda item: (-item.rerank_score, item.chunk_id))
        for index, item in enumerate(ranked, 1):
            item.final_rank = index
        selected = ranked[:selected_top_k]
        strong_phrase = any(re.sub(r"\s+", "", query).lower() in re.sub(r"\s+", "", item.content).lower() for item in selected)
        evidence_status = classify_evidence(
            [item.rerank_score for item in selected],
            strong_phrase=strong_phrase,
            supported_threshold=supported_threshold,
            second_threshold=second_threshold,
            limited_threshold=limited_threshold,
        )
        top_score = selected[0].rerank_score if selected else 0.0

        run = RetrievalRun(
            session_id=session_id,
            user_message_id=user_message_id,
            query=query,
            workspace_id=workspace_id,
            document_ids=document_ids,
            vector_succeeded=vector_succeeded,
            keyword_succeeded=keyword_succeeded,
            degradation_reason="；".join(degradation) or None,
            vector_top_k=vector_top_k,
            keyword_top_k=keyword_top_k,
            selected_top_k=selected_top_k,
            config_snapshot={
                "rrf_k": 60,
                "vector_weight": 0.65,
                "keyword_weight": 0.35,
                "supported_threshold": supported_threshold,
                "second_threshold": second_threshold,
                "limited_threshold": limited_threshold,
            },
            evidence_status=evidence_status,
            top_score=top_score,
        )
        self.db.add(run)
        await self.db.flush()
        for item in ranked:
            self.db.add(RetrievalHit(
                retrieval_run_id=run.id,
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                source_file=item.source_file,
                page_num=item.page_num,
                heading=item.heading,
                content_snapshot=item.content,
                vector_rank=item.vector_rank,
                keyword_rank=item.keyword_rank,
                vector_score=item.vector_score,
                keyword_score=item.keyword_score,
                fusion_score=item.fusion_score,
                rerank_score=item.rerank_score,
                final_rank=item.final_rank,
                selected_as_evidence=item in selected,
            ))
        await self.db.flush()
        return HybridRetrievalResult(
            items=selected,
            evidence_status=evidence_status,
            run_id=run.id,
            vector_succeeded=vector_succeeded,
            keyword_succeeded=keyword_succeeded,
            degradation_reason="；".join(degradation),
            top_score=top_score,
        )
