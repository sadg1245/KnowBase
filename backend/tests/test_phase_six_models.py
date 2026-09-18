"""Persistence and validation contracts for phase-six learning insights."""

import unittest
from datetime import date

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register complete SQLAlchemy metadata
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.services.activity_service import append_activity
from app.schemas.insights import GoalUpdate, GlobalGoalsUpdate, WorkspaceGoalUpdate


class PhaseSixModelTests(unittest.IsolatedAsyncioTestCase):
    def test_phase_six_tables_and_columns_are_registered(self):
        self.assertTrue(
            {"study_sessions", "learning_goals", "report_suggestions"}
            <= set(Base.metadata.tables)
        )
        activity = Base.metadata.tables["study_activities"]
        self.assertTrue(
            {"user_id", "event_key", "source_type", "source_id", "occurred_at", "schema_version"}
            <= set(activity.c.keys())
        )
        preference = Base.metadata.tables["learning_preferences"]
        self.assertTrue({"timezone_name", "weekly_goal_days"} <= set(preference.c.keys()))
        self.assertNotIn("user_profiles", Base.metadata.tables)

    def test_goal_scope_validation_rejects_mismatched_workspace(self):
        with self.assertRaises(ValidationError):
            GoalUpdate(
                scope_type="global",
                workspace_id="workspace",
                metric="daily_minutes",
                target_value=25,
            )
        with self.assertRaises(ValidationError):
            GoalUpdate(
                scope_type="workspace",
                metric="workspace_mastery",
                target_value=80,
            )

    def test_goal_payloads_enforce_limits_and_dates(self):
        payload = GlobalGoalsUpdate(
            daily_minutes=30,
            daily_reviews=12,
            weekly_days=5,
            target_completion_date=date(2026, 12, 31),
            timezone_name="Asia/Shanghai",
        )
        self.assertEqual(payload.weekly_days, 5)
        self.assertEqual(
            WorkspaceGoalUpdate(target_mastery=80, target_date=date(2026, 12, 31)).target_mastery,
            80,
        )
        with self.assertRaises(ValidationError):
            GlobalGoalsUpdate(
                daily_minutes=0,
                daily_reviews=12,
                weekly_days=5,
                target_completion_date=date(2026, 12, 31),
                timezone_name="Asia/Shanghai",
            )
        with self.assertRaises(ValidationError):
            WorkspaceGoalUpdate(target_mastery=101, target_date=date(2026, 12, 31))

    async def test_retired_compat_migration_is_idempotent_and_keeps_legacy_rows(self):
        """运行时入口不再补列，只保证检索索引可用且不改动已有数据。"""
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
                    "CREATE TABLE study_activities (id TEXT PRIMARY KEY, workspace_id TEXT, activity_type TEXT, title TEXT, duration_seconds INTEGER, payload JSON, created_at DATETIME)",
                ]
                for ddl in legacy_tables:
                    await connection.execute(text(ddl))
                await connection.execute(text(
                    "INSERT INTO study_activities VALUES "
                    "('legacy', NULL, 'review', '旧复习', 20, NULL, '2026-09-15 01:02:03')"
                ))
                await run_compat_migrations(connection)
                await run_compat_migrations(connection)
                row = (await connection.execute(text(
                    "SELECT id, title, duration_seconds FROM study_activities"
                ))).one()
                self.assertEqual(tuple(row), ("legacy", "旧复习", 20))
                indexes = {
                    value[0]
                    for value in (await connection.execute(
                        text("SELECT name FROM sqlite_master WHERE type = 'table'")
                    )).fetchall()
                }
                self.assertIn("document_chunks_fts", indexes)
        finally:
            await engine.dispose()

    async def test_activity_ledger_requires_a_real_owner(self):
        """活动账本不能再用任意字符串作为归属。"""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _enforce_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                with self.assertRaises(IntegrityError):
                    await append_activity(
                        session,
                        user_id="missing-user",
                        event_key="activity:orphan",
                        activity_type="card_created",
                        title="无主活动",
                        source_type="flashcard",
                        source_id="card-1",
                    )
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
