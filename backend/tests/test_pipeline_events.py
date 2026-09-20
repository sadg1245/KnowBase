"""Every ingestion stage must leave a durable, ordered audit row."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.collector.pipeline import DocumentPipeline
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.document import Document
from app.models.pipeline import DocumentPipelineEvent
from tests.support import create_user, create_workspace


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FailingEmbedding:
    async def embed_texts(self, texts):
        raise RuntimeError("embedding offline")


class _FakeVectorStore:
    def __init__(self) -> None:
        self.calls = 0

    async def replace_document(self, **_kwargs):
        self.calls += 1


class _PassThroughSplitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


class PipelineEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        self.tmp.cleanup()
        await self.engine.dispose()

    async def _seed_document(self, path: str) -> tuple[str, str]:
        async with self.sessions() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="流水线", slug="pipeline-events")
            document = Document(
                workspace_id=workspace.id,
                filename="notes.txt",
                file_path=path,
                file_type="txt",
                status="pending",
            )
            db.add(document)
            await db.commit()
            return document.id, workspace.id

    async def _events(self, document_id: str):
        async with self.sessions() as db:
            return (
                await db.execute(
                    select(DocumentPipelineEvent)
                    .where(DocumentPipelineEvent.document_id == document_id)
                    .order_by(DocumentPipelineEvent.started_at)
                )
            ).scalars().all()

    async def _document(self, document_id: str) -> Document:
        async with self.sessions() as db:
            return (
                await db.execute(select(Document).where(Document.id == document_id))
            ).scalar_one()

    async def test_successful_run_records_four_ordered_nodes_and_stage(self):
        path = str(Path(self.tmp.name) / "notes.txt")
        Path(path).write_text("条件概率的定义与公式。\n\n贝叶斯定理。", encoding="utf-8")
        document_id, workspace_id = await self._seed_document(path)
        vector_store = _FakeVectorStore()
        pipeline = DocumentPipeline(_FakeEmbedding(), vector_store, _PassThroughSplitter())

        async with self.sessions() as db:
            result = await pipeline.process_document(document_id, path, "txt", workspace_id, db)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(vector_store.calls, 1)

        events = await self._events(document_id)
        document = await self._document(document_id)

        self.assertEqual(
            [event.node for event in events],
            ["parsing", "structure", "chunking", "embedding", "indexing"],
        )
        self.assertTrue(all(event.status == "succeeded" for event in events))
        self.assertTrue(all(event.finished_at is not None for event in events))
        self.assertTrue(all((event.duration_ms or 0) >= 0 for event in events))
        self.assertEqual(document.pipeline_stage, "ready")

    async def test_embedding_failure_records_a_failed_event_and_stage(self):
        path = str(Path(self.tmp.name) / "broken.txt")
        Path(path).write_text("任意内容", encoding="utf-8")
        document_id, workspace_id = await self._seed_document(path)
        pipeline = DocumentPipeline(
            _FailingEmbedding(), _FakeVectorStore(), _PassThroughSplitter()
        )

        async with self.sessions() as db:
            result = await pipeline.process_document(document_id, path, "txt", workspace_id, db)

        self.assertEqual(result["status"], "failed")

        events = await self._events(document_id)
        document = await self._document(document_id)

        self.assertEqual(
            [event.node for event in events], ["parsing", "structure", "chunking", "embedding"]
        )
        self.assertEqual(events[-1].status, "failed")
        self.assertIn("embedding offline", events[-1].detail)
        self.assertEqual(document.pipeline_stage, "failed")
        self.assertEqual(document.status, "failed")
