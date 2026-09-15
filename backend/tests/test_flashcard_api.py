"""Flashcard CRUD, generation, source, and validation contracts."""

import unittest
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.routes.learning import (
    create_card,
    dashboard,
    delete_card,
    generate_workspace_cards,
    list_cards,
    point_to_card,
    selection_to_card,
    update_card,
)
from app.models.base import Base
from app.models.assessment import LearningTask, WeakKnowledgeState
from app.models.document import Document
from app.models.learning import Flashcard, KnowledgePoint
from app.models.workspace import Workspace
from app.schemas.learning import (
    FlashcardCreate,
    FlashcardGenerateRequest,
    FlashcardSelectionCreate,
    FlashcardUpdate,
)


class FlashcardApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _fixture(self, db):
        workspace = Workspace(name="Cards", slug="cards")
        other = Workspace(name="Other", slug="other")
        db.add_all([workspace, other])
        await db.flush()
        document = Document(
            workspace_id=workspace.id,
            filename="memory.md",
            file_path="memory.md",
            file_type=".md",
            status="ready",
        )
        db.add(document)
        await db.flush()
        point_a = KnowledgePoint(
            workspace_id=workspace.id,
            document_id=document.id,
            title="Spacing",
            summary="Review over time",
            explanation="Review shortly before forgetting.",
            difficulty=3,
            tags=["memory"],
            source_page=3,
            source_heading="Long-term memory",
        )
        point_b = KnowledgePoint(
            workspace_id=workspace.id,
            document_id=document.id,
            title="Retrieval",
            summary="Recall strengthens memory",
            difficulty=2,
            tags=["practice"],
        )
        db.add_all([point_a, point_b])
        await db.flush()
        return workspace, other, document, point_a, point_b

    async def test_manual_card_can_be_created_updated_filtered_and_deleted(self):
        async with self.sessions() as db:
            workspace, _other, _document, _point_a, _point_b = await self._fixture(db)
            created = await create_card(FlashcardCreate(
                workspace_id=workspace.id,
                front="Question",
                back="Answer",
                tags=["memory"],
                difficulty=3,
                source_type="answer",
            ), db)
            self.assertEqual(created["source_type"], "manual")
            self.assertEqual(created["tags"], ["memory"])
            self.assertEqual(created["mastery_status"], "not_started")

            due = datetime(2026, 9, 1, tzinfo=timezone.utc)
            updated = await update_card(created["id"], FlashcardUpdate(
                front="Updated question",
                tags=["memory", "core"],
                difficulty=4,
                due_at=due,
            ), db)
            self.assertEqual(updated["front"], "Updated question")
            self.assertEqual(updated["tags"], ["memory", "core"])
            self.assertEqual(updated["difficulty"], 4)

            filtered = await list_cards(
                workspace_id=workspace.id,
                source_type="manual",
                tag="core",
                query="updated",
                db=db,
            )
            self.assertEqual([row["id"] for row in filtered], [created["id"]])

            await delete_card(created["id"], db)
            self.assertEqual(await list_cards(workspace_id=workspace.id, db=db), [])

    async def test_selection_card_saves_structured_source_and_rejects_cross_workspace_document(self):
        async with self.sessions() as db:
            workspace, other, document, _point_a, _point_b = await self._fixture(db)
            card = await selection_to_card(FlashcardSelectionCreate(
                workspace_id=workspace.id,
                document_id=document.id,
                front="Why space reviews?",
                back="Because memory fades over time.",
                source_excerpt="Memory fades over time.",
                source_page=3,
                source_heading="Long-term memory",
                tags=["memory"],
                difficulty=3,
            ), db)
            self.assertEqual(card["source_type"], "selection")
            self.assertEqual(card["source_snapshot"]["document_id"], document.id)
            self.assertEqual(card["source_snapshot"]["excerpt"], "Memory fades over time.")
            self.assertEqual(card["source_snapshot"]["page"], 3)

            with self.assertRaises(HTTPException) as raised:
                await selection_to_card(FlashcardSelectionCreate(
                    workspace_id=other.id,
                    document_id=document.id,
                    front="Invalid",
                    back="Invalid",
                    source_excerpt="Invalid",
                ), db)
            self.assertEqual(raised.exception.status_code, 400)

    async def test_point_generation_is_idempotent_and_workspace_generation_skips_existing(self):
        async with self.sessions() as db:
            workspace, _other, _document, point_a, point_b = await self._fixture(db)
            first = await point_to_card(point_a.id, db)
            second = await point_to_card(point_a.id, db)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(first["source_type"], "knowledge_point")
            self.assertEqual(first["difficulty"], 3)
            self.assertEqual(first["tags"], ["memory"])

            generated = await generate_workspace_cards(
                workspace.id,
                FlashcardGenerateRequest(knowledge_point_ids=[point_a.id, point_b.id]),
                db,
            )
            self.assertEqual(generated["created_count"], 1)
            self.assertEqual(generated["cards"][0]["knowledge_point_id"], point_b.id)
            cards = (await db.execute(select(Flashcard))).scalars().all()
            self.assertEqual(len(cards), 2)

    async def test_missing_workspace_and_cross_workspace_point_are_rejected(self):
        async with self.sessions() as db:
            workspace, other, _document, point_a, _point_b = await self._fixture(db)
            with self.assertRaises(HTTPException) as missing:
                await create_card(FlashcardCreate(
                    workspace_id="missing",
                    front="Q",
                    back="A",
                ), db)
            self.assertEqual(missing.exception.status_code, 404)

            with self.assertRaises(HTTPException) as cross_workspace:
                await update_card(
                    (await point_to_card(point_a.id, db))["id"],
                    FlashcardUpdate(workspace_id=other.id),
                    db,
                )
            self.assertEqual(cross_workspace.exception.status_code, 400)

    async def test_due_cards_order_by_weakness_before_due_time(self):
        async with self.sessions() as db:
            workspace, _other, _document, point_a, point_b = await self._fixture(db)
            now = datetime.now(timezone.utc)
            early = Flashcard(
                workspace_id=workspace.id, knowledge_point_id=point_a.id,
                front="Early", back="A", due_at=now - timedelta(minutes=10),
            )
            weak = Flashcard(
                workspace_id=workspace.id, knowledge_point_id=point_b.id,
                front="Weak", back="B", due_at=now - timedelta(minutes=1),
            )
            db.add_all([early, weak])
            await db.flush()
            db.add_all([
                WeakKnowledgeState(workspace_id=workspace.id, knowledge_point_id=point_a.id, weakness_score=20),
                WeakKnowledgeState(workspace_id=workspace.id, knowledge_point_id=point_b.id, weakness_score=90),
            ])
            await db.flush()

            rows = await list_cards(workspace_id=workspace.id, due_only=True, db=db)

            self.assertEqual([row["id"] for row in rows], [weak.id, early.id])

    async def test_dashboard_exposes_due_weak_learning_tasks(self):
        async with self.sessions() as db:
            workspace, _other, _document, point_a, _point_b = await self._fixture(db)
            task = LearningTask(
                workspace_id=workspace.id,
                knowledge_point_id=point_a.id,
                task_type="targeted_practice",
                title="Practice spacing",
                path=f"/practice?workspace_id={workspace.id}&knowledge_point_id={point_a.id}&mode=targeted",
                due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                priority=81,
            )
            db.add(task)
            await db.flush()

            payload = await dashboard(db)

            self.assertTrue(any(
                row.get("id") == task.id
                and row["type"] == "targeted_practice"
                and row["title"] == "Practice spacing"
                and row["path"] == task.path
                for row in payload["today_tasks"]
            ))


if __name__ == "__main__":
    unittest.main()
