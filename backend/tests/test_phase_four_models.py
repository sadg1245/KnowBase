"""Persistence and validation contracts for phase-four review cards."""

import unittest

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register complete SQLAlchemy metadata
from app.models.base import Base
from app.models.learning import Flashcard, ReviewLog
from tests.support import create_user, create_workspace
from app.core.migrations import run_compat_migrations
from app.schemas.learning import FlashcardCreate, FlashcardUpdate, ReviewRequest


class PhaseFourModelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_flashcard_defaults_preserve_review_state(self):
        async with self.sessions() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="Cards", slug="cards")
            card = Flashcard(workspace_id=workspace.id, front="Q", back="A")
            db.add(card)
            await db.flush()

            self.assertEqual(card.tags, [])
            self.assertEqual(card.difficulty, 2)
            self.assertEqual(card.mastery, 0.0)
            self.assertEqual(card.mastery_status, "not_started")
            self.assertEqual(card.source_type, "manual")
            self.assertIsNone(card.source_snapshot)
            self.assertEqual(card.algorithm_version, "simple_v1")
            self.assertEqual(card.scheduler_data, {})
            self.assertIsNone(card.last_reviewed_at)
            self.assertEqual(card.total_review_seconds, 0)
            self.assertIsNotNone(card.updated_at)

    def test_review_log_exposes_mastery_timing_and_algorithm_columns(self):
        columns = ReviewLog.__table__.columns
        expected = {
            "duration_seconds",
            "previous_mastery",
            "next_mastery",
            "previous_status",
            "next_status",
            "algorithm_version",
        }
        self.assertTrue(expected <= set(columns.keys()))

    def test_review_request_accepts_duration_and_rejects_out_of_range(self):
        self.assertEqual(ReviewRequest(rating=3, duration_seconds=18).duration_seconds, 18)
        self.assertEqual(ReviewRequest(rating=3).duration_seconds, 0)
        with self.assertRaises(ValidationError):
            ReviewRequest(rating=3, duration_seconds=3601)
        with self.assertRaises(ValidationError):
            ReviewRequest(rating=3, duration_seconds=-1)

    def test_card_create_normalizes_tags_and_validates_source_and_difficulty(self):
        payload = FlashcardCreate(
            workspace_id="workspace",
            front="Question",
            back="Answer",
            tags=[" memory ", "", "memory", "核心"],
            difficulty=4,
            source_type="selection",
        )
        self.assertEqual(payload.tags, ["memory", "核心"])
        self.assertEqual(payload.difficulty, 4)
        self.assertEqual(payload.source_type, "selection")
        with self.assertRaises(ValidationError):
            FlashcardCreate(workspace_id="workspace", front="Q", back="A", difficulty=6)
        with self.assertRaises(ValidationError):
            FlashcardCreate(workspace_id="workspace", front="Q", back="A", source_type="import")

    def test_card_update_does_not_expose_scheduler_counters(self):
        fields = set(FlashcardUpdate.model_fields)
        self.assertTrue(
            {"front", "back", "workspace_id", "tags", "difficulty", "source_label", "due_at"}
            <= fields
        )
        self.assertFalse({"review_count", "ease", "interval_days"} & fields)

    async def test_retired_compat_migrations_never_alter_structure(self):
        """结构变更由 Alembic 负责；运行时兼容入口只维护检索索引。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                legacy_tables = [
                    "CREATE TABLE workspaces (id TEXT PRIMARY KEY)",
                    "CREATE TABLE documents (id TEXT PRIMARY KEY)",
                    "CREATE TABLE document_chunks (id TEXT PRIMARY KEY, tokenized_content TEXT, heading TEXT, source_file TEXT)",
                    "CREATE TABLE knowledge_points (id TEXT PRIMARY KEY)",
                    "CREATE TABLE user_profiles (id TEXT PRIMARY KEY)",
                    "CREATE TABLE conversations (id TEXT PRIMARY KEY)",
                    "CREATE TABLE quiz_questions (id TEXT PRIMARY KEY)",
                    "CREATE TABLE flashcards (id TEXT PRIMARY KEY, front TEXT, back TEXT)",
                    "CREATE TABLE review_logs (id TEXT PRIMARY KEY, flashcard_id TEXT, rating INTEGER)",
                ]
                for ddl in legacy_tables:
                    await connection.execute(text(ddl))
                await connection.execute(text("INSERT INTO flashcards VALUES ('legacy', 'Q', 'A')"))
                await run_compat_migrations(connection)
                await run_compat_migrations(connection)
                columns = {
                    row[1]
                    for row in (await connection.execute(
                        text("PRAGMA table_info(flashcards)")
                    )).fetchall()
                }
                self.assertEqual(columns, {"id", "front", "back"})
                objects = {
                    row[0]
                    for row in (await connection.execute(
                        text("SELECT name FROM sqlite_master WHERE type = 'table'")
                    )).fetchall()
                }
                self.assertIn("document_chunks_fts", objects)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
