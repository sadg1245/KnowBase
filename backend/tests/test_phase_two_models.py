"""Persistence contracts for phase-two structured learning metadata."""

import unittest

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint
from tests.support import create_user, create_workspace
from app.schemas.learning import KnowledgePointMerge, KnowledgePointUpdate
from app.schemas.schemas import DocumentResponse, DocumentStatusResponse, DocumentUpdate


class PhaseTwoModelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_document_phase_two_defaults_are_persisted(self):
        async with self.session_factory() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="Test", slug="test")

            row = Document(
                workspace_id=workspace.id,
                filename="a.pdf",
                file_path="a.pdf",
                file_type=".pdf",
            )
            db.add(row)
            await db.flush()
            await db.refresh(row)

            self.assertEqual(row.learning_status, "not_started")
            self.assertEqual(row.tags, [])
            self.assertEqual(row.chapter_summaries, [])
            self.assertEqual(row.core_concepts, [])
            self.assertEqual(row.important_terms, [])
            self.assertEqual(row.common_mistakes, [])
            self.assertEqual(row.prerequisites, [])
            self.assertEqual(row.learning_order, [])
            self.assertEqual(row.review_points, [])
            self.assertIsNone(row.learning_error_message)
            self.assertIsNone(row.processed_at)
            self.assertIsNone(row.learning_generated_at)

    def test_document_response_exposes_phase_two_metadata(self):
        response_fields = DocumentResponse.model_fields
        expected = {
            "tags",
            "chapter_summaries",
            "core_concepts",
            "important_terms",
            "common_mistakes",
            "prerequisites",
            "learning_order",
            "review_points",
            "learning_error_message",
            "processed_at",
            "learning_generated_at",
        }
        self.assertTrue(expected <= set(response_fields))
        self.assertTrue(
            {"learning_status", "learning_error_message", "processed_at", "learning_generated_at"}
            <= set(DocumentStatusResponse.model_fields)
        )

    def test_document_update_accepts_tags(self):
        payload = DocumentUpdate(filename="renamed.pdf", tags=["python"])
        self.assertEqual(payload.filename, "renamed.pdf")
        self.assertEqual(payload.tags, ["python"])

    def test_document_chunk_exposes_structure_metadata(self):
        columns = DocumentChunk.__table__.columns
        self.assertIn("heading_level", columns)
        self.assertIn("section_path", columns)

    def test_knowledge_point_exposes_phase_two_state(self):
        columns = KnowledgePoint.__table__.columns
        self.assertIn("is_key", columns)
        self.assertIn("mastery_status", columns)
        self.assertFalse(columns.is_key.default.arg)
        self.assertEqual(columns.mastery_status.default.arg, "not_started")

    def test_knowledge_point_update_accepts_phase_two_state(self):
        payload = KnowledgePointUpdate(is_key=True, mastery_status="mastered")
        self.assertTrue(payload.is_key)
        self.assertEqual(payload.mastery_status, "mastered")

    def test_knowledge_point_update_rejects_unknown_mastery_status(self):
        with self.assertRaises(ValidationError):
            KnowledgePointUpdate(mastery_status="skipped")

    def test_knowledge_point_merge_requires_sources(self):
        payload = KnowledgePointMerge(target_id="target", source_ids=["source"])
        self.assertEqual(payload.source_ids, ["source"])
        with self.assertRaises(ValidationError):
            KnowledgePointMerge(target_id="target", source_ids=[])


if __name__ == "__main__":
    unittest.main()
