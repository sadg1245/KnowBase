"""Long-term learning memory: generation, dedup, recall, and lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assessment import MistakeRecord
from app.models.learning import KnowledgePoint, LearningMemory, QuizQuestion as QuestionModel
from app.models.workspace import Workspace
from app.services.hybrid_retrieval import build_fts_match_query, tokenize_for_search
from app.services.learner_profile import invalidate_profile_cache

MEMORY_KINDS = ("session_summary", "mistake_pattern", "preference", "insight", "manual")

KIND_IMPORTANCE = {
    "manual": 0.9,
    "preference": 0.8,
    "mistake_pattern": 0.75,
    "session_summary": 0.6,
    "insight": 0.5,
}


class MemoryVectorStore(Protocol):
    def upsert(self, *, memory_id: str, embedding: list[float], metadata: dict, document: str) -> None: ...
    def query(self, *, embedding: list[float], top_k: int, where: dict) -> list[tuple[str, float, dict]]: ...
    def delete(self, *, memory_id: str) -> None: ...


class ChromaMemoryVectorStore:
    """Isolated per-user collection; never participates in document evidence recall."""

    def __init__(self, user_id: str) -> None:
        self.collection_name = f"memory_{user_id}".replace("-", "_")

    def _collection(self):
        from app.core.chroma import get_chroma_client

        # Cosine space so ``1 - distance`` is a true similarity: the dedup threshold is expressed as
        # a cosine similarity (settings.MEMORY_DEDUP_SIMILARITY) and the in-memory test doubles score
        # the same way. The document path keeps Chroma's L2 default and is unaffected.
        return get_chroma_client().get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, *, memory_id: str, embedding: list[float], metadata: dict, document: str) -> None:
        self._collection().upsert(
            ids=[memory_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document],
        )

    def query(self, *, embedding: list[float], top_k: int, where: dict) -> list[tuple[str, float, dict]]:
        result = self._collection().query(
            query_embeddings=[embedding],
            n_results=top_k,
            where=where or None,
            include=["distances", "metadatas"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        return [
            (
                memory_id,
                max(0.0, 1.0 - (distances[index] if index < len(distances) else 1.0)),
                metadatas[index] if index < len(metadatas) else {},
            )
            for index, memory_id in enumerate(ids)
        ]

    def delete(self, *, memory_id: str) -> None:
        self._collection().delete(ids=[memory_id])


@lru_cache(maxsize=1)
def _embedding_function():
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(settings.DEFAULT_EMBEDDING)

    def embed(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, normalize_embeddings=True).tolist()

    return embed


@dataclass
class MemoryHit:
    memory: Any
    score: float
    semantic_score: float
    keyword_score: float


@dataclass
class RecallResult:
    hits: list[MemoryHit]
    degraded_reason: str | None = None


def format_memory_block(hits: list[MemoryHit]) -> str:
    if not hits:
        return ""
    lines = ["（以下内容是学习记忆，不是资料证据，也不能引用）"]
    lines.extend(f"- [{hit.memory.kind}] {hit.memory.title}：{hit.memory.content}" for hit in hits)
    return "\n".join(lines)


class LearningMemoryService:
    def __init__(
        self,
        db: AsyncSession,
        user_id: str,
        *,
        vector_store: MemoryVectorStore | None = None,
        embed=None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.vector_store = vector_store
        self.embed = embed

    # -- collaborators -----------------------------------------------------

    def _store(self) -> MemoryVectorStore | None:
        if self.vector_store is not None:
            return self.vector_store
        try:
            self.vector_store = ChromaMemoryVectorStore(self.user_id)
        except Exception as exc:  # pragma: no cover - depends on local chroma
            logger.warning("Memory vector store unavailable: {}", exc)
            return None
        return self.vector_store

    def _embed(self, texts: list[str]) -> list[list[float]]:
        embed = self.embed or _embedding_function()
        return embed(texts)

    # -- writes ------------------------------------------------------------

    async def remember(
        self,
        *,
        kind: str,
        title: str,
        content: str,
        workspace_id: str | None = None,
        source_refs: dict | None = None,
        importance: float | None = None,
    ) -> LearningMemory | None:
        if kind not in MEMORY_KINDS:
            return None
        refs = source_refs or {}
        if not refs:
            return None
        cleaned = " ".join((content or "").split())[: settings.MEMORY_MAX_CONTENT_LENGTH]
        heading = " ".join((title or "").split())[:255]
        if not cleaned or not heading:
            return None

        try:
            embedding = self._embed([f"{heading}\n{cleaned}"])[0]
        except Exception as exc:
            logger.warning("Memory embedding unavailable: {}", exc)
            embedding = None

        existing = await self._find_duplicate(embedding, kind=kind, workspace_id=workspace_id)
        if existing is not None:
            existing.title = heading
            existing.content = cleaned
            existing.tokenized_content = tokenize_for_search(f"{heading} {cleaned}")
            existing.importance = max(existing.importance, importance or KIND_IMPORTANCE.get(kind, 0.5))
            existing.updated_at = datetime.now(timezone.utc)
            await self.db.flush()
            self._upsert(existing, embedding)
            return existing

        memory = LearningMemory(
            user_id=self.user_id,
            workspace_id=workspace_id,
            kind=kind,
            title=heading,
            content=cleaned,
            tokenized_content=tokenize_for_search(f"{heading} {cleaned}"),
            source_refs=refs,
            importance=importance or KIND_IMPORTANCE.get(kind, 0.5),
        )
        self.db.add(memory)
        await self.db.flush()
        self._upsert(memory, embedding)
        return memory

    def _upsert(self, memory: LearningMemory, embedding: list[float] | None) -> None:
        store = self._store()
        if store is None or embedding is None:
            memory.embedding_state = "failed"
            return
        try:
            store.upsert(
                memory_id=memory.id,
                embedding=embedding,
                metadata={
                    "user_id": self.user_id,
                    "workspace_id": memory.workspace_id or "",
                    "kind": memory.kind,
                    "is_active": bool(memory.is_active),
                },
                document=f"{memory.title}\n{memory.content}",
            )
            memory.embedding_state = "ready"
        except Exception as exc:
            logger.warning("Memory vector upsert failed for {}: {}", memory.id, exc)
            memory.embedding_state = "failed"

    async def _find_duplicate(self, embedding, *, kind: str, workspace_id: str | None):
        if embedding is None:
            return None
        store = self._store()
        if store is None:
            return None
        try:
            where: dict = {"$and": [{"is_active": True}, {"kind": kind}]}
            if workspace_id:
                where = {"$and": [{"is_active": True}, {"kind": kind}, {"workspace_id": workspace_id}]}
            candidates = store.query(embedding=embedding, top_k=1, where=where)
        except Exception as exc:
            logger.warning("Memory dedup lookup degraded: {}", exc)
            return None
        if not candidates:
            return None
        memory_id, score, _ = candidates[0]
        if score < settings.MEMORY_DEDUP_SIMILARITY:
            return None
        return (
            await self.db.execute(
                select(LearningMemory).where(
                    LearningMemory.id == memory_id,
                    LearningMemory.user_id == self.user_id,
                )
            )
        ).scalar_one_or_none()

    # -- reads -------------------------------------------------------------

    async def recall(
        self, *, question: str, workspace_id: str | None, top_k: int | None = None
    ) -> RecallResult:
        limit = top_k or settings.MEMORY_SELECTED_K
        semantic: dict[str, float] = {}
        degraded: str | None = None
        store = self._store()
        if store is None:
            degraded = "vector_unavailable"
        else:
            try:
                embedding = self._embed([question])[0]
                where: dict = {"is_active": True}
                if workspace_id:
                    where = {"$and": [{"is_active": True}, {"workspace_id": workspace_id}]}
                for memory_id, score, _ in store.query(
                    embedding=embedding, top_k=settings.MEMORY_RECALL_K, where=where
                ):
                    semantic[memory_id] = max(0.0, min(1.0, score))
            except Exception as exc:
                logger.warning("Memory semantic recall degraded: {}", exc)
                degraded = "vector_unavailable"

        keyword = await self._keyword_recall(question)
        if not semantic and not keyword:
            return RecallResult([], degraded)

        rows = list(
            (
                await self.db.execute(
                    select(LearningMemory).where(
                        LearningMemory.user_id == self.user_id,
                        LearningMemory.is_active.is_(True),
                        LearningMemory.id.in_(set(semantic) | set(keyword)),
                        *(
                            [LearningMemory.workspace_id.in_([workspace_id, None])]
                            if workspace_id
                            else []
                        ),
                    )
                )
            ).scalars().all()
        )
        hits = [
            MemoryHit(
                memory=row,
                score=0.6 * semantic.get(row.id, 0.0)
                + 0.25 * keyword.get(row.id, 0.0)
                + 0.15 * row.importance,
                semantic_score=semantic.get(row.id, 0.0),
                keyword_score=keyword.get(row.id, 0.0),
            )
            for row in rows
        ]
        hits.sort(key=lambda hit: -hit.score)
        return RecallResult(hits[:limit], degraded)

    async def _keyword_recall(self, question: str) -> dict[str, float]:
        match_query = build_fts_match_query(question)
        if not match_query:
            return {}
        statement = text(
            "SELECT m.id AS id FROM learning_memories_fts "
            "JOIN learning_memories m ON m.rowid = learning_memories_fts.rowid "
            "WHERE learning_memories_fts MATCH :match_query "
            "AND m.user_id = :user_id AND m.is_active = 1 "
            "ORDER BY bm25(learning_memories_fts) ASC LIMIT :top_k"
        )
        try:
            rows = (
                await self.db.execute(
                    statement,
                    {
                        "match_query": match_query,
                        "user_id": self.user_id,
                        "top_k": settings.MEMORY_RECALL_K,
                    },
                )
            ).mappings().all()
        except Exception as exc:
            logger.warning("Memory keyword recall degraded: {}", exc)
            return {}
        return {row["id"]: 1.0 / (index + 1) for index, row in enumerate(rows)}

    async def list_memories(
        self,
        *,
        kind: str | None = None,
        workspace_id: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningMemory], int]:
        filters = [LearningMemory.user_id == self.user_id]
        if kind:
            filters.append(LearningMemory.kind == kind)
        if workspace_id:
            filters.append(LearningMemory.workspace_id == workspace_id)
        if is_active is not None:
            filters.append(LearningMemory.is_active.is_(is_active))
        total = int(
            (
                await self.db.execute(
                    select(func.count(LearningMemory.id)).where(*filters)
                )
            ).scalar()
            or 0
        )
        rows = list(
            (
                await self.db.execute(
                    select(LearningMemory)
                    .where(*filters)
                    .order_by(LearningMemory.updated_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars().all()
        )
        return rows, total

    # -- lifecycle ---------------------------------------------------------

    async def update_memory(self, memory_id: str, **changes) -> LearningMemory | None:
        memory = (
            await self.db.execute(
                select(LearningMemory).where(
                    LearningMemory.id == memory_id, LearningMemory.user_id == self.user_id
                )
            )
        ).scalar_one_or_none()
        if memory is None:
            return None
        content_changed = False
        if "title" in changes and changes["title"]:
            memory.title = " ".join(str(changes["title"]).split())[:255]
            content_changed = True
        if "content" in changes and changes["content"]:
            memory.content = " ".join(str(changes["content"]).split())[
                : settings.MEMORY_MAX_CONTENT_LENGTH
            ]
            content_changed = True
        if "importance" in changes and changes["importance"] is not None:
            memory.importance = float(changes["importance"])
        if "is_active" in changes and changes["is_active"] is not None:
            memory.is_active = bool(changes["is_active"])
        if content_changed:
            memory.tokenized_content = tokenize_for_search(f"{memory.title} {memory.content}")
        memory.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        if content_changed or "is_active" in changes:
            try:
                embedding = self._embed([f"{memory.title}\n{memory.content}"])[0]
            except Exception:
                embedding = None
            self._upsert(memory, embedding)
        return memory

    async def delete_memory(self, memory_id: str) -> bool:
        memory = (
            await self.db.execute(
                select(LearningMemory).where(
                    LearningMemory.id == memory_id, LearningMemory.user_id == self.user_id
                )
            )
        ).scalar_one_or_none()
        if memory is None:
            return False
        store = self._store()
        if store is not None:
            try:
                store.delete(memory_id=memory_id)
            except Exception as exc:
                logger.warning("Memory vector delete failed for {}: {}", memory_id, exc)
        await self.db.delete(memory)
        await self.db.flush()
        return True

    async def record_usage(self, memories: list[LearningMemory]) -> None:
        if not memories:
            return
        now = datetime.now(timezone.utc)
        for memory in memories:
            memory.use_count += 1
            memory.last_used_at = now
        await self.db.flush()


async def _owner_user_id(db: AsyncSession, workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    workspace = await db.get(Workspace, workspace_id)
    return getattr(workspace, "owner_id", None)


async def remember_session_summary(
    db: AsyncSession,
    *,
    user_id: str,
    session,
    content: str,
    service: LearningMemoryService | None = None,
) -> None:
    """Best-effort session summary memory; never raises into the caller."""
    try:
        text_content = " ".join((content or "").split())
        if not text_content:
            return
        writer = service or LearningMemoryService(db, user_id)
        async with db.begin_nested():
            await writer.remember(
                kind="session_summary",
                title=getattr(session, "title", "") or "学习会话",
                content=text_content[-800:],
                workspace_id=getattr(session, "workspace_id", None),
                source_refs={"session_id": getattr(session, "id", None)},
            )
        invalidate_profile_cache(user_id, getattr(session, "workspace_id", None))
    except Exception as exc:
        logger.warning("Session summary memory skipped: {}", exc)


async def remember_mistake_pattern(
    db: AsyncSession,
    *,
    workspace_id: str,
    question_id: str,
    user_id: str | None = None,
    window_days: int = 30,
    service: LearningMemoryService | None = None,
) -> None:
    """Store a pattern memory once a knowledge point has two recent mistakes."""
    try:
        owner = user_id or await _owner_user_id(db, workspace_id)
        if not owner:
            return
        question = await db.get(QuestionModel, question_id)
        if question is None or not question.knowledge_point_id:
            return
        since = datetime.now(timezone.utc) - timedelta(days=window_days)
        count = int(
            (
                await db.execute(
                    select(func.count(MistakeRecord.id)).where(
                        MistakeRecord.knowledge_point_id == question.knowledge_point_id,
                        MistakeRecord.workspace_id == workspace_id,
                        MistakeRecord.last_wrong_at >= since,
                    )
                )
            ).scalar()
            or 0
        )
        if count < 2:
            return
        point = await db.get(KnowledgePoint, question.knowledge_point_id)
        title = getattr(point, "title", "") or "未命名知识点"
        record = (
            await db.execute(
                select(MistakeRecord).where(MistakeRecord.question_id == question.id)
            )
        ).scalar_one_or_none()
        pattern = (getattr(record, "error_reason", None) or "").strip() or "答案类型或解题步骤出错"
        writer = service or LearningMemoryService(db, owner)
        async with db.begin_nested():
            await writer.remember(
                kind="mistake_pattern",
                title=f"{title} 的常见错误",
                content=f"{title} 上「{pattern}」最近 {window_days} 天内出现 {count} 次。",
                workspace_id=workspace_id,
                source_refs={
                    "knowledge_point_id": question.knowledge_point_id,
                    "mistake_id": getattr(record, "id", None),
                },
            )
        invalidate_profile_cache(owner, workspace_id)
    except Exception as exc:
        logger.warning("Mistake pattern memory skipped: {}", exc)


async def remember_report_insight(
    db: AsyncSession,
    *,
    user_id: str,
    period_type: str,
    suggestion: str,
    workspace_id: str | None = None,
    service: LearningMemoryService | None = None,
) -> None:
    """Best-effort report insight memory; never raises into the caller."""
    try:
        cleaned = " ".join((suggestion or "").split())
        if not cleaned:
            return
        writer = service or LearningMemoryService(db, user_id)
        async with db.begin_nested():
            await writer.remember(
                kind="insight",
                title=f"{period_type} 学习报告建议",
                content=cleaned[:1500],
                workspace_id=workspace_id,
                source_refs={"origin": "report", "period_type": period_type},
            )
    except Exception as exc:
        logger.warning("Report insight memory skipped: {}", exc)
