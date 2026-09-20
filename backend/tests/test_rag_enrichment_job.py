"""阶段 3：富化从入库主链路拆出——入库先 ready，summary/question 向量后台补齐。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.collector.pipeline import DocumentPipeline
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.rag.enrichment.job import enrich_document
from tests.support import create_user, create_workspace


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _CapturingStore:
    def __init__(self) -> None:
        self.deleted: list[list[str]] = []
        self.added_ids: list[str] = []
        self.added_metadatas: list[dict] = []

    async def delete_ids(self, workspace_id, doc_ids):
        self.deleted.append(list(doc_ids))

    async def add_documents(self, *, doc_ids=None, metadatas=None, **_kwargs):
        self.added_ids = list(doc_ids or [])
        self.added_metadatas = list(metadatas or [])

    async def replace_document(self, **_kwargs):
        return None


class _Splitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


async def _completion(prompt: str) -> str:
    count = prompt.count("<chunk id=")
    return json.dumps([
        {
            "summary": f"摘要 {index}",
            "subject": "概率论",
            "knowledge_points": ["条件概率"],
            "keywords": ["条件概率"],
            "difficulty": 2,
            "content_type": "definition",
            "questions": ["什么是条件概率？"],
        }
        for index in range(max(1, count))
    ], ensure_ascii=False)


class EnrichmentJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, username="enrich-job")
        self.workspace = await create_workspace(self.db, self.user, name="富化任务", slug="enrich-job")
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="notes.md",
            file_path="notes.md",
            file_type="md",
            status="ready",
            chunk_count=2,
            enrichment_state="pending",
        )
        self.db.add(self.document)
        await self.db.flush()
        for index in range(2):
            self.db.add(DocumentChunk(
                id=f"doc_chunk_{index}",
                workspace_id=self.workspace.id,
                document_id=self.document.id,
                source_file="notes.md",
                chunk_index=index,
                content=f"条件概率是指已知 B 发生时 A 发生的概率（第 {index} 段）。",
                tokenized_content="条件概率",
                chunk_level="child",
                content_type="concept",
                enrichment_status="pending",
            ))
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_job_backfills_metadata_and_extra_vectors(self):
        store = _CapturingStore()
        summary = await enrich_document(
            self.db,
            self.document.id,
            completion=_completion,
            embedder=_FakeEmbedding(),
            store=store,
        )

        self.assertEqual(summary["state"], "ready")
        self.assertEqual(summary["chunks_ready"], 2)
        self.assertEqual(summary["vectors_added"], 4)      # 2 个 chunk × (summary + question)
        # 只补非 content 向量：不能重写 content 记录
        self.assertNotIn("doc_chunk_0", store.added_ids)
        self.assertIn("doc_chunk_0#summary", store.added_ids)
        self.assertIn("doc_chunk_0#question0", store.added_ids)
        self.assertTrue(all(meta["vector_kind"] != "content" for meta in store.added_metadatas))
        # 先按精确 id 删除，避免 questions 数量变化后留下孤儿向量
        self.assertEqual(store.deleted[0], store.added_ids)

        rows = list((await self.db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == self.document.id)
        )).scalars().all())
        self.assertTrue(all(row.enrichment_status == "ready" for row in rows))
        self.assertTrue(all(row.summary for row in rows))
        self.assertEqual(rows[0].chunk_metadata["questions"], ["什么是条件概率？"])
        await self.db.refresh(self.document)
        self.assertEqual(self.document.enrichment_state, "ready")
        self.assertEqual(self.document.enrichment_progress["chunks_ready"], 2)

    async def test_second_run_is_a_no_op(self):
        store = _CapturingStore()
        await enrich_document(
            self.db, self.document.id, completion=_completion, embedder=_FakeEmbedding(), store=store
        )
        store.added_ids = []
        store.deleted = []

        second = await enrich_document(
            self.db, self.document.id, completion=_completion, embedder=_FakeEmbedding(), store=store
        )

        self.assertEqual(second["enriched_now"], 0)
        # 没有新富化、上次也写过向量 → 直接跳过重写（廉价 no-op）
        self.assertEqual(store.added_ids, [])
        self.assertEqual(store.deleted, [])
        self.assertEqual(second["vectors_added"], 4)
        self.assertEqual(second["state"], "ready")

    async def test_llm_failure_marks_chunks_failed_without_breaking_document(self):
        async def broken(prompt: str) -> str:
            raise RuntimeError("provider offline")

        store = _CapturingStore()
        summary = await enrich_document(
            self.db, self.document.id, completion=broken, embedder=_FakeEmbedding(), store=store
        )

        self.assertEqual(summary["state"], "failed")
        self.assertEqual(summary["chunks_failed"], 2)
        rows = list((await self.db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == self.document.id)
        )).scalars().all())
        self.assertTrue(all(row.enrichment_status == "failed" for row in rows))
        # 规则关键词仍然保留，检索链不受影响
        self.assertTrue(all(row.keywords for row in rows))
        await self.db.refresh(self.document)
        self.assertEqual(self.document.enrichment_state, "failed")
        self.assertEqual(self.document.status, "ready")


class PipelineEnrichmentDecouplingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "notes.md")
        Path(self.path).write_text(
            "# 第 1 章 概率\n\n## 1.1 定义\n\n条件概率是指已知 B 发生时 A 发生的概率。\n",
            encoding="utf-8",
        )
        async with self.sessions() as db:
            user = await create_user(db, username="decouple")
            workspace = await create_workspace(db, user, name="入库", slug="decouple")
            document = Document(
                workspace_id=workspace.id, filename="notes.md", file_path=self.path,
                file_type="md", status="pending",
            )
            db.add(document)
            await db.commit()
            self.document_id = document.id
            self.workspace_id = workspace.id

    async def asyncTearDown(self):
        self.tmp.cleanup()
        await self.engine.dispose()

    async def test_ingestion_indexes_content_only_and_queues_enrichment(self):
        store = _CapturingStore()

        async def replace_document(**kwargs):
            store.added_ids = list(kwargs.get("doc_ids") or [])
            store.added_metadatas = list(kwargs.get("metadatas") or [])

        store.replace_document = replace_document
        queued: list[str] = []

        with patch("app.config.settings.RAG_ENRICH_ENABLED", True), \
                patch("app.services.document_jobs.enqueue_document_enrichment", queued.append), \
                patch("app.rag.enrichment.build_completion", lambda settings=None, **_: _completion):
            pipeline = DocumentPipeline(_FakeEmbedding(), store, _Splitter())
            async with self.sessions() as db:
                result = await pipeline.process_document(
                    self.document_id, self.path, "md", self.workspace_id, db
                )
            async with self.sessions() as db:
                document = await db.get(Document, self.document_id)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(queued, [self.document_id])          # 入库结束即排队富化
        self.assertEqual(document.enrichment_state, "pending")  # 但此刻还没富化
        self.assertTrue(store.added_ids)
        self.assertTrue(all("#" not in str(doc_id) for doc_id in store.added_ids))
        self.assertEqual(
            {meta.get("vector_kind") for meta in store.added_metadatas}, {"content"}
        )

    async def test_ingestion_skips_enrichment_queue_when_disabled(self):
        store = _CapturingStore()
        queued: list[str] = []

        with patch("app.config.settings.RAG_ENRICH_ENABLED", False), \
                patch("app.services.document_jobs.enqueue_document_enrichment", queued.append):
            pipeline = DocumentPipeline(_FakeEmbedding(), store, _Splitter())
            async with self.sessions() as db:
                await pipeline.process_document(
                    self.document_id, self.path, "md", self.workspace_id, db
                )
            async with self.sessions() as db:
                document = await db.get(Document, self.document_id)

        self.assertEqual(queued, [])
        self.assertEqual(document.enrichment_state, "skipped")


if __name__ == "__main__":
    unittest.main()
