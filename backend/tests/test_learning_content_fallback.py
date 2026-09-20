"""学习内容生成的两级降级：整篇一次 → 按章分批 + 覆盖率 + 只补失败章节。"""

import json
import types
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings as app_settings
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.services.learning_content import (
    CHAPTER_MARKER,
    LearningGenerationError,
    LearningMaterial,
    generate_document_learning_content,
    merge_chapter_materials,
)
from tests.support import create_user, create_workspace


def _response(payload) -> types.SimpleNamespace:
    content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    message = types.SimpleNamespace(content=content)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message, finish_reason="stop")])


def _material(summary: str, *, chunk_index: int, title: str | None = None) -> dict:
    return {
        "summary": summary,
        "chapter_summaries": [f"{summary} 的章节摘要"],
        "core_concepts": [f"{summary} 概念"],
        "important_terms": [f"{summary} 术语"],
        "common_mistakes": [f"{summary} 常见错误"],
        "prerequisites": [f"{summary} 前置"],
        "learning_order": [f"{summary} 顺序"],
        "review_points": [f"{summary} 复习点"],
        "knowledge_points": [{
            "title": title or f"{summary} 知识点",
            "summary": f"{summary} 概览",
            "explanation": f"{summary} 解释",
            "importance": 3,
            "difficulty": 2,
            "tags": ["测试"],
            "source_chunk_index": chunk_index,
        }],
    }


class MergeTests(unittest.TestCase):
    def test_merge_dedupes_and_orders_chapters(self):
        first = LearningMaterial.model_validate(_material("甲", chunk_index=0))
        second = LearningMaterial.model_validate(_material("乙", chunk_index=2))
        duplicate = LearningMaterial.model_validate(_material("甲", chunk_index=0))

        merged = merge_chapter_materials([first, second, duplicate])

        self.assertEqual(merged.chapter_summaries, ["甲 的章节摘要", "乙 的章节摘要"])
        self.assertEqual(len(merged.knowledge_points), 2)
        self.assertEqual([point.source_chunk_index for point in merged.knowledge_points], [0, 2])

    def test_merge_rejects_empty_knowledge_points(self):
        material = LearningMaterial.model_validate(_material("甲", chunk_index=0))
        with self.assertRaises(LearningGenerationError):
            merge_chapter_materials([])
        self.assertTrue(material.knowledge_points)


class ChapterFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, username="learning-fallback")
        self.workspace = await create_workspace(self.db, self.user, name="降级", slug="learning-fallback")
        # 复用真实配置（provider / model / key 从 .env 读取）；测试注入 completion，不会真的调用模型
        self.settings = app_settings

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _document(self, chapters: list[str]) -> Document:
        document = Document(
            workspace_id=self.workspace.id, filename="book.md", file_path="book.md",
            file_type="md", status="ready",
        )
        self.db.add(document)
        await self.db.flush()
        index = 0
        for chapter in chapters:
            for _ in range(2):
                self.db.add(DocumentChunk(
                    id=f"chunk-{document.id[:6]}-{index}",
                    workspace_id=self.workspace.id,
                    document_id=document.id,
                    source_file="book.md",
                    chunk_index=index,
                    heading=chapter,
                    section_path=[chapter],
                    content=f"{chapter} 的第 {index} 段内容。",
                    tokenized_content="内容",
                    chunk_level="child",
                    content_type="concept",
                ))
                index += 1
        await self.db.commit()
        return document

    async def test_whole_document_path_records_full_coverage(self):
        document = await self._document(["第 1 章", "第 2 章"])
        calls: list[str] = []

        async def completion(**kwargs):
            prompt = kwargs["messages"][0]["content"]
            calls.append(prompt)
            return _response(_material("整篇", chunk_index=0))

        material = await generate_document_learning_content(
            self.db, document.id, self.settings, completion=completion
        )

        self.assertEqual(material.summary, "整篇")
        self.assertEqual(len(calls), 1)
        await self.db.refresh(document)
        self.assertEqual(document.learning_status, "ready")
        self.assertEqual(document.learning_coverage["strategy"], "whole_document")
        self.assertEqual(document.learning_coverage["chapters_ready"], 2)

    async def test_invalid_whole_document_falls_back_to_per_chapter(self):
        document = await self._document(["第 1 章", "第 2 章"])
        calls: list[str] = []

        async def completion(**kwargs):
            prompt = kwargs["messages"][0]["content"]
            calls.append(prompt)
            if CHAPTER_MARKER in prompt:
                chapter = prompt.split(CHAPTER_MARKER, 1)[1].splitlines()[0]
                return _response(_material(chapter.strip(), chunk_index=0 if "1" in chapter else 2))
            return _response("不是 JSON")

        material = await generate_document_learning_content(
            self.db, document.id, self.settings, completion=completion
        )

        # 整篇路径重试一次后失败，再逐章生成
        self.assertEqual(sum(call.count(CHAPTER_MARKER) for call in calls), 2)
        self.assertGreaterEqual(len(calls), 4)
        await self.db.refresh(document)
        self.assertEqual(document.learning_status, "ready")
        self.assertEqual(document.learning_coverage["strategy"], "per_chapter")
        self.assertEqual(document.learning_coverage["chapters_ready"], 2)
        self.assertEqual(len(material.knowledge_points), 2)

    async def test_partial_failure_is_recorded_and_retry_only_reruns_failed_chapter(self):
        document = await self._document(["第 1 章", "第 2 章"])
        chapter_calls: list[str] = []
        fail_second = True

        async def completion(**kwargs):
            nonlocal fail_second
            prompt = kwargs["messages"][0]["content"]
            if CHAPTER_MARKER not in prompt:
                return _response("不是 JSON")
            chapter = prompt.split(CHAPTER_MARKER, 1)[1].splitlines()[0]
            chapter_calls.append(chapter)
            if "第 2 章" in chapter and fail_second:
                return _response("依然不是 JSON")
            return _response(_material(chapter.strip(), chunk_index=0 if "第 1 章" in chapter else 2))

        # 第一次：整篇失败 → 第 1 章成功、第 2 章失败 → learning_status=partial
        await generate_document_learning_content(
            self.db, document.id, self.settings, completion=completion
        )
        await self.db.refresh(document)
        self.assertEqual(document.learning_status, "partial")
        self.assertEqual(document.learning_coverage["chapters_failed"], 1)
        self.assertIn("第 2 章", document.learning_error_message or "")
        first_chapter_calls = [call for call in chapter_calls if "第 1 章" in call]
        self.assertEqual(len(first_chapter_calls), 1)

        # 第二次：整篇再失败一次，但第 1 章复用缓存，只重跑第 2 章
        fail_second = False
        chapter_calls.clear()
        await generate_document_learning_content(
            self.db, document.id, self.settings, completion=completion
        )
        await self.db.refresh(document)
        self.assertEqual(document.learning_status, "ready")
        self.assertEqual(document.learning_coverage["chapters_ready"], 2)
        self.assertTrue(all("第 1 章" not in call for call in chapter_calls))
        self.assertTrue(any("第 2 章" in call for call in chapter_calls))

    async def test_single_chapter_document_reports_failure_without_fake_partial(self):
        document = await self._document(["第 1 章"])

        async def completion(**kwargs):
            return _response("不是 JSON")

        with self.assertRaises(LearningGenerationError):
            await generate_document_learning_content(
                self.db, document.id, self.settings, completion=completion
            )

        await self.db.refresh(document)
        self.assertNotEqual(document.learning_status, "partial")
        self.assertEqual(document.learning_coverage["chapters_failed"], 1)
        self.assertEqual(document.learning_coverage["strategy"], "whole_document")


if __name__ == "__main__":
    unittest.main()
