"""后台富化任务：入库完成后增量补写 summary / question 向量。

入库主链路只负责「解析 → 结构 → 切分 → 嵌入 → 索引 → ready」，
大文档因此几十秒即可检索；富化按批在后台跑，完成后：

- 把 summary / subject / keywords / difficulty / content_type / questions 写回 chunk 行；
- 为白名单内容类型增量 upsert `#summary` / `#questionN` 向量（content 向量保持不动）；
- 更新 `documents.enrichment_state` 与 `enrichment_progress`，失败批次可再次补跑。
"""

from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_settings
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.rag.chunking.base import Chunk
from app.rag.enrichment.metadata_enricher import MetadataEnricher, build_completion
from app.rag.indexing.multivector import expand_child_vectors, parse_vector_kinds


def _chunk_from_row(row: DocumentChunk) -> Chunk:
    return Chunk(
        chunk_id=row.id,
        document_id=row.document_id,
        workspace_id=row.workspace_id,
        content=row.content or "",
        chunk_level=row.chunk_level,
        parent_id=row.parent_id,
        unit_id=row.unit_id,
        content_type=row.content_type or "concept",
        heading=row.heading,
        heading_level=row.heading_level,
        section_path=list(row.section_path or []),
        page_start=row.page_num,
        page_end=row.page_end,
        metadata={"questions": (row.chunk_metadata or {}).get("questions") or []},
    )


def _row_payload(row: DocumentChunk) -> dict:
    """把已富化的 chunk 行整理成多向量展开所需的输入。"""
    metadata = {
        "chunk_id": row.id,
        "chunk_level": row.chunk_level,
        "parent_id": row.parent_id,
        "content_type": row.content_type or "concept",
        "document_type": row.document_type,
        "subject": row.subject,
        "summary": row.summary,
        "keywords": list(row.keywords or []),
        "knowledge_points": list(row.knowledge_points or []),
        "difficulty": row.difficulty,
        "questions": list((row.chunk_metadata or {}).get("questions") or []),
        "source_file": row.source_file,
        "page_num": row.page_num,
        "section_path": list(row.section_path or []),
    }
    return {"content": row.content or "", "metadata": metadata}


async def enrich_document(
    db: AsyncSession,
    document_id: str,
    *,
    settings=None,
    completion=None,
    embedder=None,
    store=None,
    force: bool = False,
) -> dict:
    """对一篇文档做富化 + 增量向量补齐；可重复执行（已 ready 的 chunk 会跳过）。"""
    settings = settings or app_settings
    document = await db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} not found")

    rows = list((
        await db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_level == "child",
            )
            .order_by(DocumentChunk.chunk_index.asc())
        )
    ).scalars().all())
    targets = [row for row in rows if row.enrichment_status != "ready"]
    document.enrichment_state = "pending" if targets else "ready"
    await db.flush()

    if targets:
        chunks = [_chunk_from_row(row) for row in targets]
        enricher = MetadataEnricher(
            enabled=True,
            completion=completion or build_completion(settings),
            batch_size=int(getattr(settings, "RAG_ENRICH_BATCH_SIZE", 10)),
            concurrency=int(getattr(settings, "RAG_ENRICH_CONCURRENCY", 3)),
        )
        result = await enricher.enrich(chunks)
        for chunk, row in zip(chunks, targets):
            meta = chunk.metadata
            row.content_type = chunk.content_type
            row.summary = meta.get("summary") or None
            row.subject = meta.get("subject") or None
            row.keywords = list(meta.get("keywords") or [])
            row.knowledge_points = list(meta.get("knowledge_points") or [])
            row.difficulty = meta.get("difficulty")
            row.enrichment_status = str(meta.get("enrichment_status") or row.enrichment_status)
            questions = [str(item) for item in (meta.get("questions") or []) if str(item).strip()]
            row.chunk_metadata = {
                **(row.chunk_metadata or {}),
                **({"questions": questions} if questions else {}),
            }
        await db.flush()
    else:
        result = None

    ready_rows = [row for row in rows if row.enrichment_status == "ready"]
    previous_vectors = int((document.enrichment_progress or {}).get("vector_records_added") or 0)
    enriched_now = result.enriched if result else 0
    # 只有"这次真的富化了"或"上次没写成功过向量"才重写向量，重复执行是廉价的 no-op
    should_write_vectors = bool(force or enriched_now or not previous_vectors)
    ids, texts, metadatas = ([], [], [])
    if should_write_vectors:
        ids, texts, metadatas = expand_child_vectors(
            [_row_payload(row) for row in ready_rows],
            kinds=parse_vector_kinds(
                getattr(settings, "RAG_MULTIVECTOR_KINDS", "content,summary,question")
            ),
            include_content=False,
        )
    vectors_added = 0
    if ids:
        if embedder is None:
            from app.core.embedding import get_embedding_service

            embedder = get_embedding_service()
        if store is None:
            from app.core.vector_store import get_vector_store

            store = get_vector_store()
        embeddings = await embedder.embed_texts(texts)
        # 先按精确 id 删除，避免 questions 数量变化后留下孤儿向量
        await store.delete_ids(document.workspace_id, ids)
        await store.add_documents(
            workspace_id=document.workspace_id,
            doc_ids=ids,
            texts=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        vectors_added = len(ids)

    ready = len(ready_rows)
    failed = sum(1 for row in rows if row.enrichment_status == "failed")
    skipped = len(rows) - ready - failed
    if not should_write_vectors:
        vectors_added = previous_vectors
    document.enrichment_progress = {
        "chunks_total": len(rows),
        "chunks_ready": ready,
        "chunks_failed": failed,
        "chunks_pending": skipped,
        "vector_records_added": vectors_added,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    document.enrichment_state = (
        "ready" if rows and ready == len(rows)
        else "partial" if ready
        else "failed" if rows
        else "ready"
    )
    await db.commit()

    summary = {
        "document_id": document_id,
        "state": document.enrichment_state,
        "chunks_total": len(rows),
        "chunks_ready": ready,
        "chunks_failed": failed,
        "vectors_added": vectors_added,
        "enriched_now": result.enriched if result else 0,
    }
    logger.info("Enrichment finished for document {}: {}", document_id, summary)
    return summary


async def enrich_document_by_id(document_id: str) -> dict:
    """Celery 任务入口：自建会话执行一次后台富化。"""
    from app.models.base import async_session_factory

    async with async_session_factory() as db:
        return await enrich_document(db, document_id)
