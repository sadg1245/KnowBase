import importlib
import os
import tempfile
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.collector.pipeline import DocumentPipeline
from app.api.routes.documents import _extract_text
from app.core.vector_store import VectorStore
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.workspace import Workspace
from tests.support import create_user, create_workspace


def _load_filter():
    try:
        module = importlib.import_module("app.collector.content_filter")
    except ModuleNotFoundError:
        return None
    return getattr(module, "filter_learning_content", None)


def _chunk(page: int, heading: str, content: str) -> dict:
    return {
        "content": content,
        "metadata": {
            "page_num": page,
            "heading": heading,
            "source_file": "book.pdf",
        },
    }


class LearningContentFilterTests(unittest.TestCase):
    def test_numbered_chapter_discards_all_front_matter_before_body(self):
        filter_content = _load_filter()
        self.assertTrue(callable(filter_content), "正文过滤器尚未实现")
        chunks = [
            _chunk(3, "数字版权声明", "本电子书仅供个人使用"),
            _chunk(8, "目录", "第1章 Python入门……26"),
            _chunk(9, "", "1.1 Python是什么……26"),
            _chunk(18, "前言", "人工智能正在改变世界"),
            _chunk(26, "1.1 Python是什么", "Python是一种简单易学的编程语言"),
            _chunk(27, "1.2 Python的安装", "本节介绍安装方法"),
        ]

        filtered = filter_content(chunks)

        self.assertEqual([item["metadata"]["page_num"] for item in filtered], [26, 27])

    def test_appendices_and_references_remain_but_terminal_sections_are_removed(self):
        filter_content = _load_filter()
        self.assertTrue(callable(filter_content), "正文过滤器尚未实现")
        chunks = [
            _chunk(26, "第1章 Python入门", "正文"),
            _chunk(280, "附录A", "补充代码"),
            _chunk(290, "参考文献", "研究资料"),
            _chunk(300, "致谢", "感谢编辑"),
            _chunk(301, "", "感谢家人"),
            _chunk(302, "索引", "Python 26"),
            _chunk(311, "版权信息", "商标和版权说明"),
            _chunk(312, "连接图灵", "出版社读者服务"),
            _chunk(314, "看完了", "联系编辑"),
        ]

        filtered = filter_content(chunks)

        self.assertEqual([item["metadata"]["page_num"] for item in filtered], [26, 280, 290])

    def test_unstructured_documents_are_filtered_conservatively(self):
        filter_content = _load_filter()
        self.assertTrue(callable(filter_content), "正文过滤器尚未实现")
        chunks = [
            _chunk(1, "版权声明", "未经授权不得传播"),
            _chunk(2, "", "版权声明续页"),
            _chunk(3, "研究背景", "这是没有编号章节的正文"),
            _chunk(4, "研究方法", "正文方法"),
            _chunk(5, "参考文献", "正文引用"),
        ]

        filtered = filter_content(chunks)

        self.assertEqual([item["metadata"]["page_num"] for item in filtered], [3, 4, 5])

    def test_plain_documents_without_non_body_signals_are_unchanged(self):
        filter_content = _load_filter()
        self.assertTrue(callable(filter_content), "正文过滤器尚未实现")
        chunks = [
            _chunk(1, "研究背景", "项目背景"),
            _chunk(2, "研究结论", "项目结论"),
        ]

        filtered = filter_content(chunks)

        self.assertEqual(filtered, chunks)

    def test_english_chapter_boundary_also_removes_unlabelled_cover_content(self):
        filter_content = _load_filter()
        self.assertTrue(callable(filter_content), "正文过滤器尚未实现")
        chunks = [
            _chunk(1, "", "Deep Learning from Scratch"),
            _chunk(2, "Copyright", "All rights reserved"),
            _chunk(3, "Chapter 1", "Python basics"),
            _chunk(4, "Appendix A", "Example code"),
        ]

        filtered = filter_content(chunks)

        self.assertEqual([item["metadata"]["page_num"] for item in filtered], [3, 4])


class _StaticParser:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks

    def parse(self, _file_path: str) -> list[dict]:
        return self.chunks


class _PassThroughSplitter:
    def split_documents(self, chunks: list[dict]) -> list[dict]:
        return chunks


class _EmbeddingService:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]


class _MemoryVectorStore:
    def __init__(self):
        self.texts: list[str] = ["stale copyright chunk"]

    async def add_documents(self, *, texts: list[str], **_kwargs) -> None:
        self.texts.extend(texts)

    async def replace_document(self, *, texts: list[str], **_kwargs) -> None:
        self.texts = list(texts)


class DocumentPipelineContentBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_pipeline_indexes_only_filtered_body_chunks(self):
        raw_chunks = [
            _chunk(3, "数字版权声明", "本电子书仅供个人使用"),
            _chunk(18, "前言", "这是一段前言"),
            _chunk(26, "第1章 Python入门", "Python正文"),
            _chunk(280, "附录A", "附录代码"),
        ]
        vector_store = _MemoryVectorStore()
        pipeline = DocumentPipeline(_EmbeddingService(), vector_store, _PassThroughSplitter())
        pipeline._get_parser = lambda _file_type: _StaticParser(raw_chunks)  # type: ignore[method-assign]

        async with self.session_factory() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="测试", slug="body-filter")
            document = Document(
                workspace_id=workspace.id,
                filename="book.pdf",
                file_path="ignored.pdf",
                file_type=".pdf",
                file_size=1,
            )
            db.add(document)
            await db.commit()

            result = await pipeline.process_document(
                document.id,
                document.file_path,
                document.file_type,
                workspace.id,
                db,
            )
            keyword_chunks = (await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document.id).order_by(DocumentChunk.chunk_index)
            )).scalars().all()
            await db.refresh(document)

        self.assertEqual(result["chunks_count"], 2)
        self.assertIsNotNone(document.processed_at)
        self.assertEqual(vector_store.texts, ["Python正文", "附录代码"])
        # 阶段 3：parent 行也落在 document_chunks，只有 child 进入向量与正文断言
        children = [item for item in keyword_chunks if item.chunk_level == "child"]
        parents = [item for item in keyword_chunks if item.chunk_level == "parent"]
        self.assertEqual([item.content for item in children], ["Python正文", "附录代码"])
        self.assertTrue(parents)
        self.assertTrue(all(child.parent_id for child in children))

    async def test_reindex_clears_stale_vectors_when_document_has_no_body(self):
        vector_store = _MemoryVectorStore()
        pipeline = DocumentPipeline(_EmbeddingService(), vector_store, _PassThroughSplitter())
        pipeline._get_parser = lambda _file_type: _StaticParser([
            _chunk(1, "版权声明", "未经授权不得传播"),
        ])  # type: ignore[method-assign]

        async with self.session_factory() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="空正文", slug="empty-body")
            document = Document(
                workspace_id=workspace.id,
                filename="notice.pdf",
                file_path="ignored.pdf",
                file_type=".pdf",
                file_size=1,
            )
            db.add(document)
            await db.commit()

            result = await pipeline.process_document(
                document.id,
                document.file_path,
                document.file_type,
                workspace.id,
                db,
            )
            await db.refresh(document)

        self.assertEqual(result["chunks_count"], 0)
        self.assertIsNotNone(document.processed_at)
        self.assertEqual(vector_store.texts, [])


class _MemoryCollection:
    def __init__(self):
        self.rows = {
            "doc-a_chunk_0": {"text": "old", "metadata": {"doc_id": "doc-a"}},
            "doc-a_legacy": {"text": "legacy", "metadata": {"document_id": "doc-a"}},
            "doc-b_chunk_0": {"text": "keep", "metadata": {"doc_id": "doc-b"}},
        }

    def delete(self, *, where: dict) -> None:
        key, value = next(iter(where.items()))
        self.rows = {
            row_id: row for row_id, row in self.rows.items()
            if row["metadata"].get(key) != value
        }

    def upsert(self, *, ids: list[str], documents: list[str], metadatas: list[dict], **_kwargs) -> None:
        for row_id, text, metadata in zip(ids, documents, metadatas):
            self.rows[row_id] = {"text": text, "metadata": metadata}


class _MemoryChromaClient:
    def __init__(self, collection: _MemoryCollection):
        self.collection = collection

    def get_or_create_collection(self, **_kwargs) -> _MemoryCollection:
        return self.collection


class VectorReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def test_reindex_replaces_current_and_legacy_chunks_without_touching_other_documents(self):
        collection = _MemoryCollection()
        store = object.__new__(VectorStore)
        store.host = "memory"
        store.port = 0
        store._client = _MemoryChromaClient(collection)
        replace_document = getattr(store, "replace_document", None)
        self.assertTrue(callable(replace_document), "安全重索引方法尚未实现")

        await replace_document(
            workspace_id="workspace-a",
            document_id="doc-a",
            doc_ids=["doc-a_chunk_0"],
            texts=["new body"],
            embeddings=[[0.0, 1.0]],
            metadatas=[{"doc_id": "doc-a", "source_file": "book.pdf"}],
        )

        self.assertEqual(set(collection.rows), {"doc-a_chunk_0", "doc-b_chunk_0"})
        self.assertEqual(collection.rows["doc-a_chunk_0"]["text"], "new body")
        self.assertEqual(collection.rows["doc-b_chunk_0"]["text"], "keep")


class InlineExtractionContentBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_inline_fallback_uses_the_same_body_filter(self):
        import fitz

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "book.pdf")
            document = fitz.open()
            for content in [
                "All rights reserved",
                "This is the preface",
                "Python body content",
                "Appendix example code",
            ]:
                page = document.new_page()
                page.insert_text((72, 72), content)
            document.set_toc([
                [1, "Copyright", 1],
                [1, "Preface", 2],
                [1, "Chapter 1", 3],
                [1, "Appendix A", 4],
            ])
            document.save(path)
            document.close()

            text = await _extract_text(path, ".pdf")

        self.assertNotIn("All rights reserved", text)
        self.assertNotIn("This is the preface", text)
        self.assertIn("Python body content", text)
        self.assertIn("Appendix example code", text)


if __name__ == "__main__":
    unittest.main()
