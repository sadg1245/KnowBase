"""Phase-two document and knowledge management contracts."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.routes.documents import (
    get_document_section,
    list_document_sections,
    regenerate_document_learning,
    reprocess_document,
    update_document,
)
from app.api.routes.learning import merge_points, point_to_quiz, update_point, workspace_learning_detail
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint, StudyActivity
from app.schemas.learning import KnowledgePointMerge, KnowledgePointUpdate
from app.schemas.schemas import DocumentUpdate
from tests.support import create_user, create_workspace


class DocumentManagementTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _fixture(self, db):
        user = await create_user(db)
        self.user = user
        workspace = await create_workspace(db, user, name="Docs", slug="docs")
        document = Document(
            workspace_id=workspace.id,
            filename="book.pdf",
            file_path="book.pdf",
            file_type=".pdf",
            status="ready",
        )
        db.add(document)
        await db.flush()
        for index in range(2):
            db.add(DocumentChunk(
                id=f"{document.id}_chunk_{index}",
                workspace_id=workspace.id,
                document_id=document.id,
                source_file=document.filename,
                page_num=index + 1,
                heading="第一章",
                heading_level=1,
                section_path=["第一章"],
                chunk_index=index,
                content=f"content {index}",
                tokenized_content=f"content {index}",
            ))
        await db.flush()
        return workspace, document

    async def test_update_sections_neighbors_and_retry_guards(self):
        async with self.sessions() as db:
            _workspace, document = await self._fixture(db)
            updated = await update_document(
                document.id,
                DocumentUpdate(filename=" Renamed.pdf ", tags=[" A ", "", "A", "B"]),
                db,
                current_user=self.user,
            )
            self.assertEqual(updated.filename, "Renamed.pdf")
            self.assertEqual(updated.tags, ["A", "B"])

            sections = await list_document_sections(document.id, db, current_user=self.user)
            self.assertEqual(sections["items"][0]["chunk_id"], f"{document.id}_chunk_0")
            self.assertEqual(sections["outline"][0]["section_path"], ["第一章"])
            detail = await get_document_section(
                document.id, f"{document.id}_chunk_0", db, current_user=self.user
            )
            self.assertIsNone(detail["previous_chunk_id"])
            self.assertEqual(detail["next_chunk_id"], f"{document.id}_chunk_1")

            document.status = "processing"
            await db.flush()
            with self.assertRaises(HTTPException) as conflict:
                await reprocess_document(document.id, db, current_user=self.user)
            self.assertEqual(conflict.exception.status_code, 409)
            with self.assertRaises(HTTPException) as not_ready:
                await regenerate_document_learning(document.id, db=db, current_user=self.user)
            self.assertEqual(not_ready.exception.status_code, 400)

    async def test_learning_detail_merge_mastery_and_quiz(self):
        async with self.sessions() as db:
            workspace, document = await self._fixture(db)
            document.status = "failed"
            document.error_message = "parse failed"
            target = KnowledgePoint(
                workspace_id=workspace.id, document_id=document.id, title="Target",
                summary="A", explanation="EA", tags=["A"], importance=2,
            )
            source = KnowledgePoint(
                workspace_id=workspace.id, document_id=document.id, title="Source",
                summary="B", explanation="EB", tags=["B"], importance=5, is_key=True,
            )
            db.add_all([target, source, StudyActivity(
                user_id=self.user.id,
                workspace_id=workspace.id, activity_type="read", title="Read chapter",
            )])
            await db.flush()

            detail = await workspace_learning_detail(workspace.id, db, current_user=self.user)
            self.assertEqual(detail["recommendations"][0]["type"], "retry_document")
            self.assertEqual(detail["recent_activities"][0]["title"], "Read chapter")

            mastered = await update_point(
                target.id,
                KnowledgePointUpdate(mastery_status="mastered"),
                db,
                current_user=self.user,
            )
            self.assertEqual(mastered["mastery"], 1.0)
            merged = await merge_points(
                KnowledgePointMerge(target_id=target.id, source_ids=[source.id]),
                db,
                current_user=self.user,
            )
            self.assertEqual(set(merged["tags"]), {"A", "B"})
            self.assertTrue(merged["is_key"])
            remaining = (await db.execute(select(KnowledgePoint))).scalars().all()
            self.assertEqual([row.id for row in remaining], [target.id])

            quiz = await point_to_quiz(target.id, db, current_user=self.user)
            self.assertEqual(quiz["knowledge_point_id"], target.id)
            self.assertNotIn("answer", quiz)

