"""第一阶段：文档与知识点标签规范化，以及人工标签保护。"""

import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.config import settings
from app.core.tags import TagValidationError, normalize_tags
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint
from app.schemas.learning import KnowledgePointUpdate
from app.schemas.schemas import DocumentUpdate
from app.services.learning_content import LearningMaterial, replace_document_learning_content
from app.api.routes.documents import update_document
from app.api.routes.learning import update_point
from tests.support import create_user, create_workspace


class TagNormalizationTests(unittest.TestCase):
    def test_shared_normalizer_strips_deduplicates_and_keeps_first_order(self):
        self.assertEqual(
            normalize_tags([" 数学 ", "", "数学", "代数", None if False else "代数"]),
            ["数学", "代数"],
        )
        self.assertEqual(normalize_tags(None), [])
        self.assertEqual(normalize_tags([]), [])

    def test_shared_normalizer_rejects_invalid_values_and_boundaries(self):
        with self.assertRaises(TagValidationError):
            normalize_tags(["ok", 12])
        with self.assertRaises(TagValidationError):
            normalize_tags("not-a-list")
        with self.assertRaises(TagValidationError):
            normalize_tags(["x" * (settings.TAG_MAX_LENGTH + 1)])
        with self.assertRaises(TagValidationError):
            normalize_tags([f"tag-{index}" for index in range(settings.TAG_MAX_COUNT + 1)])
        # 边界值本身是允许的。
        self.assertEqual(len(normalize_tags(["x" * settings.TAG_MAX_LENGTH])), 1)
        self.assertEqual(len(normalize_tags([f"t{index}" for index in range(settings.TAG_MAX_COUNT)])),
                         settings.TAG_MAX_COUNT)


class TagApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(
            self.db, self.user, name="标签", slug="tags"
        )
        self.document = Document(
            workspace_id=self.workspace.id, filename="tags.pdf", file_path="tags.pdf",
            file_type=".pdf", status="ready",
        )
        self.db.add(self.document)
        await self.db.flush()
        self.db.add(DocumentChunk(
            id=f"{self.document.id}_0", workspace_id=self.workspace.id,
            document_id=self.document.id, source_file="tags.pdf", page_num=1,
            heading="第一章", section_path=["第一章"], chunk_index=0,
            content="body", tokenized_content="body",
        ))
        self.point = KnowledgePoint(
            workspace_id=self.workspace.id, document_id=self.document.id,
            title="特征值", summary="s", explanation="e",
        )
        self.db.add(self.point)
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_document_and_point_tags_share_the_same_normalization(self):
        document = await update_document(
            self.document.id,
            DocumentUpdate(tags=[" 线性代数 ", "", "线性代数", "考研"]),
            self.db,
            current_user=self.user,
        )
        self.assertEqual(document.tags, ["线性代数", "考研"])

        point = await update_point(
            self.point.id,
            KnowledgePointUpdate(tags=[" 重要 ", "重要", "考研"]),
            self.db,
            current_user=self.user,
        )
        self.assertEqual(point["tags"], ["重要", "考研"])
        self.assertTrue(self.point.tags_locked)

        with self.assertRaises(HTTPException) as raised:
            await update_document(
                self.document.id,
                DocumentUpdate(tags=["x" * (settings.TAG_MAX_LENGTH + 1)]),
                self.db,
                current_user=self.user,
            )
        self.assertEqual(raised.exception.status_code, 422)

        # 非字符串标签在请求契约层就被拒绝，等价于 HTTP 422。
        with self.assertRaises(ValidationError):
            KnowledgePointUpdate(tags=["ok", 3])

    def _material(self, tags: list[str]) -> LearningMaterial:
        return LearningMaterial(
            summary="更新后的摘要",
            chapter_summaries=[],
            core_concepts=[],
            important_terms=[],
            common_mistakes=[],
            prerequisites=[],
            learning_order=[],
            review_points=[],
            knowledge_points=[{
                "title": "特征值",
                "summary": "新摘要",
                "explanation": "新解释",
                "importance": 4,
                "difficulty": 2,
                "tags": tags,
                "source_chunk_index": 0,
            }],
        )

    async def test_regeneration_keeps_manual_tags_unless_explicitly_overwritten(self):
        await update_point(
            self.point.id,
            KnowledgePointUpdate(tags=["人工标签"]),
            self.db,
            current_user=self.user,
        )

        await replace_document_learning_content(
            self.db, self.document, self._material(["AI 标签"])
        )
        points = (await self.db.execute(select(KnowledgePoint))).scalars().all()
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].tags, ["人工标签"])
        self.assertTrue(points[0].tags_locked)

        await replace_document_learning_content(
            self.db, self.document, self._material(["AI 标签"]), overwrite_tags=True
        )
        points = (await self.db.execute(select(KnowledgePoint))).scalars().all()
        self.assertEqual(points[0].tags, ["AI 标签"])
        self.assertFalse(points[0].tags_locked)

    async def test_generated_content_without_manual_tags_uses_ai_tags(self):
        await replace_document_learning_content(
            self.db, self.document, self._material(["自动标签"])
        )
        points = (await self.db.execute(select(KnowledgePoint))).scalars().all()
        self.assertEqual(points[0].tags, ["自动标签"])
        self.assertFalse(points[0].tags_locked)


if __name__ == "__main__":
    unittest.main()
