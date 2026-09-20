"""SQLite FTS5 + vector hybrid retrieval with deterministic evidence scoring."""

from __future__ import annotations

import re
import asyncio
import json
from dataclasses import dataclass
from collections.abc import Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat import DocumentChunk, RetrievalHit, RetrievalRun
from app.models.document import Document
from app.models.workspace import Workspace
from app.schemas.scope import ResolvedRetrievalScope


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
        metadata = chunk.get("metadata") or {}
        chunk_id = str(metadata.get("chunk_id") or f"{document_id}_chunk_{index}")
        active_ids.append(chunk_id)
        content = str(chunk.get("content") or "")
        row = existing.get(chunk_id)
        if row is None:
            row = DocumentChunk(id=chunk_id, workspace_id=workspace_id, document_id=document_id)
            db.add(row)
        row.source_file = source_file
        row.page_num = metadata.get("page_num")
        row.page_end = metadata.get("page_end")
        row.heading = metadata.get("heading")
        row.heading_level = metadata.get("heading_level")
        row.section_path = _section_path(metadata.get("section_path"))
        row.chunk_index = index
        row.content = content
        row.tokenized_content = tokenize_for_search(content)
        # 阶段 3：Parent-Child 结构与 chunk 级元数据
        row.chunk_level = str(metadata.get("chunk_level") or "child")
        row.parent_id = metadata.get("parent_id")
        row.unit_id = metadata.get("unit_id")
        row.content_type = str(metadata.get("content_type") or "concept")
        row.document_type = metadata.get("document_type")
        row.subject = metadata.get("subject")
        row.summary = metadata.get("summary")
        row.keywords = list(metadata.get("keywords") or [])
        row.knowledge_points = list(metadata.get("knowledge_points") or [])
        row.difficulty = metadata.get("difficulty")
        row.enrichment_status = str(metadata.get("enrichment_status") or "skipped")
        row.index_version = int(metadata.get("index_version") or settings.RAG_INDEX_VERSION)
        questions = [str(item) for item in (metadata.get("questions") or []) if str(item).strip()]
        row.chunk_metadata = {
            **dict(metadata.get("chunk_metadata") or {}),
            **({"questions": questions} if questions else {}),
        }
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
    workspace_id: str | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    vector_score: float = 0.0
    keyword_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: float = 0.0
    profile_bonus: float = 0.0
    vector_kinds: tuple[str, ...] = ()
    content_type: str | None = None
    difficulty: int | None = None
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
    resolved_scope: ResolvedRetrievalScope | None = None
    expansion_rounds: int = 0
    expanded_scope: bool = False


@dataclass
class RetrievalRequest:
    """一次范围化检索的完整输入。"""

    query: str
    scope: ResolvedRetrievalScope
    owned_workspace_ids: list[str]
    session_id: str | None = None
    user_message_id: str | None = None
    # chunk_id → 画像相关度（0..1）；实际加权由 PROFILE_RANK_BONUS_MAX 控制
    profile_bonus: dict[str, float] | None = None
    # 画像薄弱点标题等文本线索；命中标题/正文时产生有界排序 Bonus
    profile_hints: list[str] | None = None
    # 画像折算出的难度区间与内容类型偏好（§20.2/§20.3），同样只影响排序
    preference_content_types: list[str] | None = None
    difficulty_range: tuple[int, int] | None = None
    # 元数据硬预过滤（§18.2）：在召回阶段就排除不相关的内容类型 / 文档类型
    metadata_filter: dict | None = None
    vector_top_k: int = 20
    keyword_top_k: int = 20
    selected_top_k: int = 8
    supported_threshold: float = 0.58
    second_threshold: float = 0.45
    limited_threshold: float = 0.42
    expansion_rounds: int = 0
    expanded_scope: bool = False
    scope_snapshot: dict | None = None


def _normalize(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {key: 1.0 if high > 0 else 0.0 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _normalize_within_collections(items: Sequence[RetrievalCandidate]) -> dict[str, float]:
    """按 collection（workspace）分别归一化向量分数。

    不同 collection 的距离尺度不可比，跨库直接排序会系统性偏向某一库。
    """
    grouped: dict[str | None, list[RetrievalCandidate]] = {}
    for item in items:
        grouped.setdefault(item.workspace_id, []).append(item)
    normalized: dict[str, float] = {}
    for group in grouped.values():
        normalized.update(_normalize({item.chunk_id: item.vector_score for item in group}))
    return normalized


def _scope_preference_bonus(
    candidate: RetrievalCandidate, scope: ResolvedRetrievalScope
) -> float:
    """范围软先验：只影响排序，不排除任何候选。"""
    bonus = 0.0
    if candidate.document_id and candidate.document_id in scope.preferred_document_ids:
        bonus += 0.30
    if (
        scope.preferred_workspace_id
        and candidate.workspace_id == scope.preferred_workspace_id
    ):
        bonus += 0.20
    return bonus


def _profile_hint_bonus(hints: Sequence[str] | None, candidate: RetrievalCandidate) -> float:
    """画像线索命中度（0..1）。只影响排序，绝不参与证据分级。"""
    if not hints:
        return 0.0
    heading = (candidate.heading or "").lower()
    content = (candidate.content or "").lower()
    hits = 0.0
    for hint in hints:
        text = str(hint).strip().lower()
        if len(text) < 2:
            continue
        if text in heading:
            hits += 1.0
        elif text in content:
            hits += 0.5
    return min(1.0, hits)


def _profile_preference_bonus(
    candidate: RetrievalCandidate,
    *,
    content_types: Sequence[str] | None,
    difficulty_range: tuple[int, int] | None,
) -> float:
    """内容类型与难度偏好（0..1）；只影响排序，绝不参与证据分级。"""
    bonus = 0.0
    candidate_type = (candidate.content_type or "").strip().lower()
    if content_types and candidate_type:
        if candidate_type in {value.lower() for value in content_types}:
            bonus += 1.0
    if difficulty_range and candidate.difficulty:
        low, high = difficulty_range
        if low <= int(candidate.difficulty) <= high:
            bonus += 0.5
    return min(1.0, bonus)


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


def build_metadata_where(filters: dict | None) -> dict | None:
    """把引擎无关的元数据过滤翻译成 Chroma `where` 子句（§18.2）。"""
    if not filters:
        return None
    clauses: list[dict] = []
    content_types = [str(value) for value in (filters.get("content_types") or []) if value]
    if content_types:
        clauses.append({"content_type": {"$in": content_types}})
    excluded = [str(value) for value in (filters.get("exclude_content_types") or []) if value]
    if excluded:
        clauses.append({"content_type": {"$nin": excluded}})
    document_types = [str(value) for value in (filters.get("document_types") or []) if value]
    if document_types:
        clauses.append({"document_type": {"$in": document_types}})
    subjects = [str(value) for value in (filters.get("subjects") or []) if value]
    if subjects:
        clauses.append({"subject": {"$in": subjects}})
    difficulty_range = filters.get("difficulty_range")
    if difficulty_range:
        low, high = int(difficulty_range[0]), int(difficulty_range[1])
        clauses.append({"difficulty": {"$gte": low, "$lte": high}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def build_sql_metadata_filter(filters: dict | None, *, prefix: str = "c") -> tuple[str, dict]:
    """返回 (SQL 片段, 绑定参数) 供 FTS 召回使用，语义与 `build_metadata_where` 一致。"""
    if not filters:
        return "", {}
    conditions: list[str] = []
    params: dict[str, object] = {}

    def bind(name: str, values: list[str]) -> str:
        names = []
        for index, value in enumerate(values):
            key = f"{name}_{index}"
            names.append(f":{key}")
            params[key] = value
        return ", ".join(names)

    content_types = [str(value) for value in (filters.get("content_types") or []) if value]
    if content_types:
        conditions.append(f"{prefix}.content_type IN ({bind('md_content_type', content_types)})")
    excluded = [str(value) for value in (filters.get("exclude_content_types") or []) if value]
    if excluded:
        conditions.append(f"{prefix}.content_type NOT IN ({bind('md_exclude_type', excluded)})")
    document_types = [str(value) for value in (filters.get("document_types") or []) if value]
    if document_types:
        conditions.append(f"{prefix}.document_type IN ({bind('md_document_type', document_types)})")
    subjects = [str(value) for value in (filters.get("subjects") or []) if value]
    if subjects:
        conditions.append(f"{prefix}.subject IN ({bind('md_subject', subjects)})")
    difficulty_range = filters.get("difficulty_range")
    if difficulty_range:
        params["md_difficulty_low"] = int(difficulty_range[0])
        params["md_difficulty_high"] = int(difficulty_range[1])
        conditions.append(
            f"{prefix}.difficulty BETWEEN :md_difficulty_low AND :md_difficulty_high"
        )
    if not conditions:
        return "", {}
    return " AND " + " AND ".join(conditions), params


class HybridRetrievalService:
    """Run vector and FTS recall, then persist a reproducible retrieval audit."""

    def __init__(self, db: AsyncSession, vector_recall) -> None:
        self.db = db
        self.vector_recall = vector_recall

    async def _keyword_recall(
        self,
        *,
        query: str,
        workspace_ids: list[str],
        document_ids: list[str],
        top_k: int,
        filters: dict | None = None,
    ) -> list[RetrievalCandidate]:
        match_query = build_fts_match_query(query)
        if not match_query:
            return []
        workspace_ids = list(dict.fromkeys(workspace_ids))
        if not workspace_ids:
            return []
        params: dict[str, object] = {
            "match_query": match_query,
            "top_k": top_k,
        }
        workspace_names = []
        for index, workspace_id in enumerate(workspace_ids):
            name = f"workspace_id_{index}"
            workspace_names.append(f":{name}")
            params[name] = workspace_id
        document_filter = ""
        if document_ids:
            names = []
            for index, document_id in enumerate(dict.fromkeys(document_ids)):
                name = f"document_id_{index}"
                names.append(f":{name}")
                params[name] = document_id
            document_filter = f" AND c.document_id IN ({', '.join(names)})"
        metadata_filter, metadata_params = build_sql_metadata_filter(filters)
        params.update(metadata_params)
        statement = text(
            "SELECT c.id, c.workspace_id, c.document_id, c.source_file, c.page_num, "
            "c.heading, c.content, c.content_type, c.difficulty, c.parent_id, "
            "bm25(document_chunks_fts) AS keyword_rank_score "
            "FROM document_chunks_fts "
            "JOIN document_chunks c ON c.rowid = document_chunks_fts.rowid "
            "WHERE document_chunks_fts MATCH :match_query "
            f"AND c.workspace_id IN ({', '.join(workspace_names)})"
            f"{document_filter} "
            f"{metadata_filter} "
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
                workspace_id=row["workspace_id"],
                keyword_rank=index,
                keyword_score=1.0 / (1.0 + abs(float(row["keyword_rank_score"] or 0.0))),
            )
            for index, row in enumerate(rows, 1)
        ]

    async def _vector_recall(
        self,
        *,
        query: str,
        workspace_ids: list[str],
        document_ids: list[str],
        top_k: int,
        filters: dict | None = None,
    ) -> list[RetrievalCandidate]:
        rows = await self.vector_recall(
            query=query,
            workspace_ids=workspace_ids,
            document_ids=document_ids,
            top_k=top_k,
            filters=filters,
        )
        return [
            RetrievalCandidate(
                chunk_id=str(row.get("chunk_id") or row.get("id") or f"vector-{index}"),
                document_id=row.get("document_id"),
                source_file=row.get("source_file", "unknown"),
                page_num=row.get("page_num"),
                heading=row.get("heading"),
                content=row.get("content", ""),
                workspace_id=row.get("workspace_id"),
                vector_rank=index,
                vector_score=max(0.0, min(1.0, float(row.get("score", 0.0)))),
                vector_kinds=tuple(row.get("vector_kinds") or ()),
                content_type=row.get("content_type"),
                difficulty=row.get("difficulty"),
            )
            for index, row in enumerate(rows, 1)
        ]

    async def retrieve_scoped(self, request: RetrievalRequest) -> HybridRetrievalResult:
        """按已解析的范围执行检索，并写入范围审计。"""
        scope = request.scope
        query = request.query
        workspace_ids = list(dict.fromkeys(scope.hard_workspace_ids))
        document_ids = list(dict.fromkeys(scope.hard_document_ids))
        session_id = request.session_id
        user_message_id = request.user_message_id
        vector_top_k = request.vector_top_k
        keyword_top_k = request.keyword_top_k
        selected_top_k = request.selected_top_k
        supported_threshold = request.supported_threshold
        second_threshold = request.second_threshold
        limited_threshold = request.limited_threshold

        if not workspace_ids:
            # fail-closed：范围为空时绝不退化为「不过滤」
            return await self._record_empty_run(request, reason="范围内没有可访问的知识库")

        vector_result, keyword_result = await asyncio.gather(
            self._vector_recall(
                query=query,
                workspace_ids=workspace_ids,
                document_ids=document_ids,
                top_k=vector_top_k,
                filters=request.metadata_filter,
            ),
            self._keyword_recall(
                query=query,
                workspace_ids=workspace_ids,
                document_ids=document_ids,
                top_k=keyword_top_k,
                filters=request.metadata_filter,
            ),
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
            if not current.workspace_id and item.workspace_id:
                current.workspace_id = item.workspace_id

        vector_ids = [item.chunk_id for item in vector_items]
        keyword_ids = [item.chunk_id for item in keyword_items]
        fusion = weighted_rrf(vector_ids, keyword_ids)
        fusion_norm = _normalize(fusion)
        # 分库归一后再融合，避免不同 collection 的距离尺度互相污染
        vector_norm = _normalize_within_collections(vector_items)
        keyword_norm = _normalize({item.chunk_id: item.keyword_score for item in candidates.values()})
        bonus_map = request.profile_bonus or {}
        for item in candidates.values():
            item.fusion_score = fusion.get(item.chunk_id, 0.0)
            item.rerank_score = rerank_score(
                rrf_norm=fusion_norm.get(item.chunk_id, 0.0),
                vector_norm=vector_norm.get(item.chunk_id, 0.0),
                keyword_norm=keyword_norm.get(item.chunk_id, 0.0),
                structure_bonus=min(
                    1.0,
                    _structure_bonus(query, item) + _scope_preference_bonus(item, scope),
                ),
            )
            raw_bonus = max(0.0, min(1.0, float(bonus_map.get(item.chunk_id, 0.0))))
            raw_bonus = max(raw_bonus, _profile_hint_bonus(request.profile_hints, item))
            raw_bonus = max(
                raw_bonus,
                _profile_preference_bonus(
                    item,
                    content_types=request.preference_content_types,
                    difficulty_range=request.difficulty_range,
                ),
            )
            # 只记录实际加权后的分数增量，便于审计还原
            item.profile_bonus = round(settings.PROFILE_RANK_BONUS_MAX * raw_bonus, 6)

        # 证据分级只用基础分；画像 Bonus 只影响最终排序
        ranked = sorted(
            candidates.values(),
            key=lambda item: (-(item.rerank_score + item.profile_bonus), item.chunk_id),
        )
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
            workspace_id=workspace_ids[0] if len(workspace_ids) == 1 else None,
            document_ids=document_ids,
            scope_mode=scope.mode,
            scope_snapshot=request.scope_snapshot or scope.audit_snapshot(),
            scope_resolution=scope.audit_snapshot(),
            expansion_rounds=request.expansion_rounds,
            expanded_scope=request.expanded_scope,
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
                "profile_bonus_max": settings.PROFILE_RANK_BONUS_MAX,
                "workspace_count": len(workspace_ids),
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
                profile_bonus=item.profile_bonus,
                vector_kinds=list(item.vector_kinds),
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
            resolved_scope=scope,
            expansion_rounds=request.expansion_rounds,
            expanded_scope=request.expanded_scope,
        )

    async def _record_empty_run(
        self, request: RetrievalRequest, *, reason: str
    ) -> HybridRetrievalResult:
        """范围为空时的 fail-closed 记录。

        检索器本身可用（因此回答层走模型兜底而不是报错），但不会返回任何候选。
        """
        run = RetrievalRun(
            session_id=request.session_id,
            user_message_id=request.user_message_id,
            query=request.query,
            workspace_id=None,
            document_ids=list(request.scope.hard_document_ids),
            scope_mode=request.scope.mode,
            scope_snapshot=request.scope_snapshot or request.scope.audit_snapshot(),
            scope_resolution=request.scope.audit_snapshot(),
            expansion_rounds=request.expansion_rounds,
            expanded_scope=request.expanded_scope,
            vector_succeeded=True,
            keyword_succeeded=True,
            degradation_reason=reason,
            selected_top_k=request.selected_top_k,
            config_snapshot={"workspace_count": 0, "fail_closed": True},
            evidence_status="insufficient",
            top_score=0.0,
        )
        self.db.add(run)
        await self.db.flush()
        return HybridRetrievalResult(
            items=[],
            evidence_status="insufficient",
            run_id=run.id,
            vector_succeeded=True,
            keyword_succeeded=True,
            degradation_reason=reason,
            top_score=0.0,
            resolved_scope=request.scope,
            expansion_rounds=request.expansion_rounds,
            expanded_scope=request.expanded_scope,
        )

    async def retrieve(
        self,
        *,
        query: str,
        workspace_id: str | None,
        document_ids: list[str],
        session_id: str | None = None,
        user_message_id: str | None = None,
        vector_top_k: int = 20,
        keyword_top_k: int = 20,
        selected_top_k: int = 8,
        supported_threshold: float = 0.58,
        second_threshold: float = 0.45,
        limited_threshold: float = 0.42,
        owned_workspace_ids: list[str] | None = None,
    ) -> HybridRetrievalResult:
        """内部兼容壳：等价于迁移前的单库 + 可选文件严格范围。

        只允许内部调用方（评测脚本、旧调用点）使用；客户端输入必须先经过
        `ScopeResolver` 的所有权收敛后再走 `retrieve_scoped`。
        """
        workspaces = (
            [workspace_id] if workspace_id else list(owned_workspace_ids or [])
        )
        scope = ResolvedRetrievalScope(
            mode="strict",
            hard_workspace_ids=workspaces,
            hard_document_ids=list(dict.fromkeys(document_ids or [])),
            expansion_enabled=False,
            expansion_ceiling="none",
            resolution_reason=["legacy_compat"],
        )
        return await self.retrieve_scoped(
            RetrievalRequest(
                query=query,
                scope=scope,
                owned_workspace_ids=list(owned_workspace_ids or workspaces),
                session_id=session_id,
                user_message_id=user_message_id,
                vector_top_k=vector_top_k,
                keyword_top_k=keyword_top_k,
                selected_top_k=selected_top_k,
                supported_threshold=supported_threshold,
                second_threshold=second_threshold,
                limited_threshold=limited_threshold,
                scope_snapshot={"mode": "strict", "legacy_compat": True},
            )
        )
