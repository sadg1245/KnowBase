"""阶段 1：解析质量必须落库，扫描件不能静默变成「零 chunk 但一切正常」。"""

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
from tests.support import create_user, create_workspace


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeVectorStore:
    async def replace_document(self, **_kwargs):
        return None


class _PassThroughSplitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


class ParseQualityPersistenceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed(self, path: str, *, file_type: str) -> tuple[str, str]:
        async with self.sessions() as db:
            user = await create_user(db, username=f"quality-{file_type}")
            workspace = await create_workspace(db, user, name="质量", slug=f"quality-{file_type}")
            document = Document(
                workspace_id=workspace.id,
                filename=Path(path).name,
                file_path=path,
                file_type=file_type,
                status="pending",
            )
            db.add(document)
            await db.commit()
            return document.id, workspace.id

    async def _document(self, document_id: str) -> Document:
        async with self.sessions() as db:
            return (
                await db.execute(select(Document).where(Document.id == document_id))
            ).scalar_one()

    async def _run(self, document_id: str, path: str, file_type: str, workspace_id: str):
        pipeline = DocumentPipeline(_FakeEmbedding(), _FakeVectorStore(), _PassThroughSplitter())
        async with self.sessions() as db:
            return await pipeline.process_document(document_id, path, file_type, workspace_id, db)

    async def test_scanned_pdf_is_marked_degraded_and_keeps_zero_chunks(self):
        import fitz

        path = str(Path(self.tmp.name) / "scanned.pdf")
        pdf = fitz.open()
        pdf.new_page()
        pdf.save(path)
        pdf.close()
        document_id, workspace_id = await self._seed(path, file_type="pdf")

        result = await self._run(document_id, path, "pdf", workspace_id)
        document = await self._document(document_id)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(document.chunk_count, 0)
        # 关键：不是「零 chunk 但一切正常」，而是带明确降级原因。
        self.assertEqual(document.parse_degraded, "scanned_pdf")
        self.assertTrue(document.parse_quality["scanned"])
        self.assertIn("扫描件", document.parse_quality["notes"][0])

    async def test_text_document_records_quality_without_degradation(self):
        path = str(Path(self.tmp.name) / "notes.txt")
        Path(path).write_text("条件概率的定义。\n\n贝叶斯定理。", encoding="utf-8")
        document_id, workspace_id = await self._seed(path, file_type="txt")

        result = await self._run(document_id, path, "txt", workspace_id)
        document = await self._document(document_id)

        self.assertEqual(result["status"], "ready")
        self.assertGreater(document.chunk_count, 0)
        self.assertIsNone(document.parse_degraded)
        self.assertFalse(document.parse_quality["scanned"])
        self.assertEqual(document.parse_quality["signature"], "text")


if __name__ == "__main__":
    unittest.main()
