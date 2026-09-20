"""开启富化后：summary / question 向量真实产生，元数据可写入 Chroma。"""

import json
import tempfile
import types
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
from app.rag.enrichment.metadata_enricher import build_completion
from app.rag.enrichment.job import enrich_document
from app.rag.indexing.multivector import expand_child_vectors
from tests.support import create_user, create_workspace

SOURCE = """# 第 1 章 条件概率

## 1.1 定义

条件概率是指已知 B 发生时 A 发生的概率。

$$P(A|B)=\\frac{P(AB)}{P(B)}$$
"""


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _CapturingVectorStore:
    def __init__(self) -> None:
        self.doc_ids: list[str] = []
        self.texts: list[str] = []
        self.metadatas: list[dict] = []
        self.upserted_ids: list[str] = []
        self.upserted_metadatas: list[dict] = []

    async def replace_document(self, *, doc_ids=None, texts=None, metadatas=None, **_kwargs):
        self.doc_ids = list(doc_ids or [])
        self.texts = list(texts or [])
        self.metadatas = list(metadatas or [])

    async def delete_ids(self, workspace_id, doc_ids):
        return None

    async def add_documents(self, *, doc_ids=None, metadatas=None, **_kwargs):
        self.upserted_ids = list(doc_ids or [])
        self.upserted_metadatas = list(metadatas or [])


class _Splitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


class MultivectorSanitisationTests(unittest.TestCase):
    def test_list_metadata_is_json_encoded_for_chroma(self):
        rows = [{
            "content": "条件概率的定义",
            "metadata": {
                "chunk_id": "c1",
                "content_type": "definition",
                "summary": "条件概率摘要",
                "questions": ["什么是条件概率？"],
                "keywords": ["条件概率", "贝叶斯"],
                "difficulty": 2,
                "chunk_metadata": {"block_start": 0},
            },
        }]
        ids, texts, metadatas = expand_child_vectors(rows, kinds=["content", "summary", "question"])

        self.assertEqual(ids, ["c1", "c1#summary", "c1#question0"])
        for meta in metadatas:
            for value in meta.values():
                self.assertIn(
                    type(value),
                    (str, int, float, bool, type(None)),
                    f"Chroma 元数据必须是标量：{value!r}",
                )
        self.assertEqual(json.loads(metadatas[0]["questions"]), ["什么是条件概率？"])
        self.assertEqual(json.loads(metadatas[0]["chunk_metadata"]), {"block_start": 0})
        self.assertEqual(metadatas[0]["difficulty"], 2)


class CompletionBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_completion_uses_the_configured_provider(self):
        captured: dict = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content='[{"summary": "s"}]')
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message, finish_reason="stop")]
            )

        settings = types.SimpleNamespace(
            RAG_ENRICH_MAX_TOKENS=1234,
            DEFAULT_LLM_PROVIDER="deepseek",
            DEFAULT_LLM_MODEL="deepseek-chat",
        )
        with patch("app.services.assessment_ai._provider", return_value=("deepseek/deepseek-chat", "k", None)), \
                patch("litellm.acompletion", fake_acompletion):
            completion = build_completion(settings)
            text = await completion("标注这些 chunk")

        self.assertIn("summary", text)
        self.assertEqual(captured["model"], "deepseek/deepseek-chat")
        self.assertEqual(captured["messages"][0]["content"], "标注这些 chunk")
        self.assertEqual(captured["response_format"], {"type": "json_object"})
        self.assertLessEqual(captured["max_tokens"], 1234)


class EnrichedPipelineVectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "chapter.md")
        Path(self.path).write_text(SOURCE, encoding="utf-8")
        async with self.sessions() as db:
            user = await create_user(db, username="enrich-vector")
            workspace = await create_workspace(db, user, name="富化", slug="enrich-vector")
            document = Document(
                workspace_id=workspace.id,
                filename="chapter.md",
                file_path=self.path,
                file_type="md",
                status="pending",
            )
            db.add(document)
            await db.commit()
            self.document_id = document.id
            self.workspace_id = workspace.id

    async def asyncTearDown(self):
        self.tmp.cleanup()
        await self.engine.dispose()

    async def test_pipeline_indexes_content_then_job_backfills_summary_and_question(self):
        store = _CapturingVectorStore()
        prompts: list[str] = []

        async def fake_completion(prompt: str) -> str:
            prompts.append(prompt)
            # 该批次有几个 chunk 就返回几条标注
            count = prompt.count("<chunk id=")
            return json.dumps([
                {
                    "summary": f"摘要 {index}",
                    "subject": "概率论",
                    "knowledge_points": ["条件概率"],
                    "keywords": ["条件概率", "贝叶斯"],
                    "difficulty": 2,
                    "content_type": "definition",
                    "questions": ["什么是条件概率？", "如何推导条件概率？"],
                }
                for index in range(max(1, count))
            ], ensure_ascii=False)

        with patch("app.rag.enrichment.build_completion", lambda settings=None, **_: fake_completion), \
                patch("app.config.settings.RAG_ENRICH_ENABLED", True):
            pipeline = DocumentPipeline(_FakeEmbedding(), store, _Splitter())
            with patch("app.services.document_jobs.enqueue_document_enrichment", lambda _id: None):
                async with self.sessions() as db:
                    result = await pipeline.process_document(
                        self.document_id, self.path, "md", self.workspace_id, db
                    )
            # 入库阶段只写 content 向量，并按设计把富化排到后台
            self.assertEqual(result["status"], "ready")
            self.assertEqual({meta.get("vector_kind") for meta in store.metadatas}, {"content"})
            self.assertFalse(prompts)

            async with self.sessions() as db:
                await enrich_document(
                    db,
                    self.document_id,
                    completion=fake_completion,
                    embedder=_FakeEmbedding(),
                    store=store,
                )
            async with self.sessions() as db:
                rows = list((
                    await db.execute(
                        select(DocumentChunk).where(DocumentChunk.document_id == self.document_id)
                    )
                ).scalars().all())

        kinds = [meta.get("vector_kind") for meta in store.upserted_metadatas]
        self.assertIn("summary", kinds)
        self.assertIn("question", kinds)
        # content 向量在入库阶段已经写好，后台任务只补非 content 向量
        self.assertNotIn("content", kinds)
        self.assertTrue(any(str(doc_id).endswith("#summary") for doc_id in store.upserted_ids))
        self.assertTrue(any("#question0" in str(doc_id) for doc_id in store.upserted_ids))
        self.assertTrue(prompts)   # 确实调用了模型
        enriched = [row for row in rows if row.chunk_level == "child" and row.summary]
        self.assertTrue(enriched)
        self.assertEqual(enriched[0].enrichment_status, "ready")
        self.assertEqual(enriched[0].subject, "概率论")
        self.assertEqual(enriched[0].chunk_metadata["questions"][0], "什么是条件概率？")

    async def test_disabled_enrichment_keeps_single_content_vector(self):
        store = _CapturingVectorStore()
        with patch("app.config.settings.RAG_ENRICH_ENABLED", False):
            pipeline = DocumentPipeline(_FakeEmbedding(), store, _Splitter())
            async with self.sessions() as db:
                await pipeline.process_document(
                    self.document_id, self.path, "md", self.workspace_id, db
                )

        kinds = {meta.get("vector_kind") for meta in store.metadatas}
        self.assertEqual(kinds, {"content"})


if __name__ == "__main__":
    unittest.main()
