"""Deterministic contracts for hybrid retrieval and evidence gating."""

import importlib
import unittest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import Settings
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.chat import DocumentChunk, RetrievalHit, RetrievalRun
from app.models.document import Document
from app.models.workspace import Workspace


def _module():
    try:
        return importlib.import_module("app.services.hybrid_retrieval")
    except ModuleNotFoundError:
        return None


class HybridRetrievalMathTests(unittest.TestCase):
    def test_evidence_thresholds_are_environment_configurable(self):
        configured = Settings(
            RAG_SUPPORTED_THRESHOLD=0.7,
            RAG_SECOND_THRESHOLD=0.5,
            RAG_LIMITED_THRESHOLD=0.3,
        )
        if not hasattr(configured, "RAG_SUPPORTED_THRESHOLD"):
            self.fail("evidence threshold settings are missing")

        self.assertEqual(configured.RAG_SUPPORTED_THRESHOLD, 0.7)
        self.assertEqual(configured.RAG_SECOND_THRESHOLD, 0.5)
        self.assertEqual(configured.RAG_LIMITED_THRESHOLD, 0.3)

    def test_fts_query_quotes_tokens_and_neutralizes_operators(self):
        module = _module()
        if module is None:
            self.fail("hybrid_retrieval service is missing")

        query = module.build_fts_match_query("向量检索 OR \"删除\"")

        self.assertNotIn(" OR ", query)
        self.assertIn('"OR"', query)
        self.assertGreaterEqual(query.count('"'), 6)

    def test_weighted_rrf_merges_both_recall_paths(self):
        module = _module()
        if module is None:
            self.fail("hybrid_retrieval service is missing")

        scores = module.weighted_rrf(["a", "b"], ["b", "c"], k=60)

        self.assertAlmostEqual(scores["a"], 0.65 / 61, places=8)
        self.assertAlmostEqual(scores["b"], 0.65 / 62 + 0.35 / 61, places=8)
        self.assertAlmostEqual(scores["c"], 0.35 / 62, places=8)
        self.assertGreater(scores["b"], scores["a"])

    def test_rerank_formula_is_deterministic(self):
        module = _module()
        if module is None:
            self.fail("hybrid_retrieval service is missing")

        score = module.rerank_score(
            rrf_norm=0.8,
            vector_norm=0.6,
            keyword_norm=0.4,
            structure_bonus=1.0,
        )

        self.assertAlmostEqual(score, 0.69, places=8)

    def test_evidence_threshold_boundaries(self):
        module = _module()
        if module is None:
            self.fail("hybrid_retrieval service is missing")

        self.assertEqual(module.classify_evidence([0.58, 0.45]), "supported")
        self.assertEqual(module.classify_evidence([0.58, 0.20], strong_phrase=True), "supported")
        self.assertEqual(module.classify_evidence([0.58, 0.20]), "limited")
        self.assertEqual(module.classify_evidence([0.42]), "limited")
        self.assertEqual(module.classify_evidence([0.4199]), "insufficient")
        self.assertEqual(module.classify_evidence([]), "insufficient")


class HybridRetrievalIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_keyword_recall_respects_document_scope_and_audits_degradation(self):
        module = _module()
        if module is None or not hasattr(module, "HybridRetrievalService"):
            self.fail("HybridRetrievalService is missing")

        async def failed_vector_recall(**_kwargs):
            raise RuntimeError("vector offline")

        async with self.session_factory() as db:
            workspace = Workspace(name="检索测试", slug="retrieval-test")
            db.add(workspace)
            await db.flush()
            first = Document(
                workspace_id=workspace.id,
                filename="选择.pdf",
                file_path="/tmp/a.pdf",
                file_type="pdf",
                status="ready",
            )
            second = Document(
                workspace_id=workspace.id,
                filename="排除.pdf",
                file_path="/tmp/b.pdf",
                file_type="pdf",
                status="ready",
            )
            db.add_all([first, second])
            await db.flush()
            db.add_all([
                DocumentChunk(
                    id="chunk-a",
                    workspace_id=workspace.id,
                    document_id=first.id,
                    source_file=first.filename,
                    chunk_index=0,
                    content="混合检索组合关键词召回和向量召回。",
                    tokenized_content=module.tokenize_for_search("混合检索组合关键词召回和向量召回。"),
                ),
                DocumentChunk(
                    id="chunk-b",
                    workspace_id=workspace.id,
                    document_id=second.id,
                    source_file=second.filename,
                    chunk_index=0,
                    content="混合检索也出现在这个不应返回的文件中。",
                    tokenized_content=module.tokenize_for_search("混合检索也出现在这个不应返回的文件中。"),
                ),
            ])
            await db.flush()

            result = await module.HybridRetrievalService(db, failed_vector_recall).retrieve(
                query="混合检索",
                workspace_id=workspace.id,
                document_ids=[first.id],
            )

            self.assertFalse(result.vector_succeeded)
            self.assertTrue(result.keyword_succeeded, result.degradation_reason)
            self.assertEqual([item.chunk_id for item in result.items], ["chunk-a"])
            self.assertIn("vector offline", result.degradation_reason)
            self.assertEqual(result.evidence_status, "supported")
            self.assertEqual((await db.execute(select(func.count(RetrievalRun.id)))).scalar(), 1)
            self.assertEqual((await db.execute(select(func.count(RetrievalHit.id)))).scalar(), 1)

    async def test_chunk_upsert_is_repeatable_and_updates_fts(self):
        module = _module()
        if module is None or not hasattr(module, "upsert_document_chunks"):
            self.fail("document chunk upsert is missing")

        async with self.session_factory() as db:
            workspace = Workspace(name="索引测试", slug="index-test")
            db.add(workspace)
            await db.flush()
            document = Document(
                workspace_id=workspace.id,
                filename="索引.pdf",
                file_path="/tmp/index.pdf",
                file_type="pdf",
                status="ready",
            )
            db.add(document)
            await db.flush()
            chunks = [{"content": "第一版索引内容", "metadata": {"page_num": 1, "heading": "概念"}}]
            await module.upsert_document_chunks(db, workspace.id, document.id, document.filename, chunks)
            chunks[0]["content"] = "更新后的证据内容"
            await module.upsert_document_chunks(db, workspace.id, document.id, document.filename, chunks)
            await db.flush()

            stored = (await db.execute(select(DocumentChunk))).scalars().all()
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0].content, "更新后的证据内容")

            async def no_vectors(**_kwargs):
                return []

            result = await module.HybridRetrievalService(db, no_vectors).retrieve(
                query="更新后的证据",
                workspace_id=workspace.id,
                document_ids=[document.id],
            )
            self.assertEqual([item.chunk_id for item in result.items], [f"{document.id}_chunk_0"])

    async def test_chroma_backfill_is_idempotent_for_existing_documents(self):
        module = _module()
        if module is None or not hasattr(module, "backfill_keyword_index"):
            self.fail("Chroma keyword backfill is missing")

        class Collection:
            def count(self):
                return 1

            def get(self, **_kwargs):
                return {
                    "ids": ["legacy-chunk"],
                    "documents": ["已有向量片段"],
                    "metadatas": [{"doc_id": "doc-legacy", "source_file": "旧资料.pdf", "chunk_index": 0}],
                }

        class Client:
            def get_collection(self, **_kwargs):
                return Collection()

        async with self.session_factory() as db:
            workspace = Workspace(id="workspace-legacy", name="旧知识库", slug="legacy")
            document = Document(
                id="doc-legacy",
                workspace_id=workspace.id,
                filename="旧资料.pdf",
                file_path="/tmp/legacy.pdf",
                file_type="pdf",
                status="ready",
            )
            db.add_all([workspace, document])
            await db.flush()

            first = await module.backfill_keyword_index(db, Client())
            second = await module.backfill_keyword_index(db, Client())

            self.assertEqual(first, 1)
            self.assertEqual(second, 0)
            self.assertEqual((await db.execute(select(func.count(DocumentChunk.id)))).scalar(), 1)


class FtsMigrationDegradationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sqlite_without_fts5_does_not_block_startup_migrations(self):
        class Dialect:
            name = "sqlite"

        class Rows:
            def fetchall(self):
                return []

        class Connection:
            dialect = Dialect()

            async def execute(self, statement, *_args, **_kwargs):
                sql = str(statement)
                if "CREATE VIRTUAL TABLE" in sql:
                    raise RuntimeError("no such module: fts5")
                return Rows()

        try:
            await run_compat_migrations(Connection())
        except RuntimeError as exc:
            self.fail(f"FTS5 absence blocked startup: {exc}")


if __name__ == "__main__":
    unittest.main()
