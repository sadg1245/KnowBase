"""Contracts for validated structured learning generation."""

import unittest

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint
from app.models.workspace import Workspace
from app.services.learning_content import LearningMaterial, replace_document_learning_content


def material_payload(**overrides):
    payload = {
        "summary": "A concise summary.",
        "chapter_summaries": [],
        "core_concepts": [],
        "important_terms": [],
        "common_mistakes": [],
        "prerequisites": [],
        "learning_order": [],
        "review_points": [],
        "knowledge_points": [{
            "title": "Core concept",
            "summary": "A short explanation.",
            "explanation": "A longer explanation of the concept.",
            "importance": 3,
            "difficulty": 2,
            "tags": ["basics"],
            "source_chunk_index": 0,
        }],
    }
    payload.update(overrides)
    return payload


class LearningMaterialTests(unittest.TestCase):
    def test_learning_material_clamps_point_values(self):
        material = LearningMaterial.model_validate(material_payload(knowledge_points=[{
            "title": "Concept",
            "summary": "Summary",
            "explanation": "Explanation",
            "importance": 9,
            "difficulty": 0,
            "tags": ["basics"],
            "source_chunk_index": 0,
        }]))

        self.assertEqual(material.knowledge_points[0].importance, 5)
        self.assertEqual(material.knowledge_points[0].difficulty, 1)

    def test_learning_material_rejects_empty_knowledge_points(self):
        with self.assertRaises(ValidationError):
            LearningMaterial.model_validate(material_payload(knowledge_points=[]))


class LearningContentReplacementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_replace_learning_content_is_idempotent(self):
        async with self.session_factory() as db:
            workspace = Workspace(name="Test", slug="test")
            db.add(workspace)
            await db.flush()
            document = Document(
                workspace_id=workspace.id,
                filename="notes.txt",
                file_path="notes.txt",
                file_type=".txt",
                status="ready",
            )
            db.add(document)
            await db.flush()
            db.add(DocumentChunk(
                id=f"{document.id}_chunk_0",
                workspace_id=workspace.id,
                document_id=document.id,
                source_file=document.filename,
                page_num=7,
                heading="Introduction",
                chunk_index=0,
                content="Durable chunk content.",
                tokenized_content="durable chunk content",
            ))
            await db.flush()

            material = LearningMaterial.model_validate(material_payload())
            await replace_document_learning_content(db, document, material)
            await replace_document_learning_content(db, document, material)

            rows = (await db.execute(select(KnowledgePoint).where(
                KnowledgePoint.document_id == document.id,
            ))).scalars().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].source_page, 7)
            self.assertEqual(rows[0].source_heading, "Introduction")
            self.assertEqual(document.learning_status, "ready")

