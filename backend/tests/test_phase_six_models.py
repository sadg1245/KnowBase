"""Persistence and validation contracts for phase-six learning insights."""

import unittest
from datetime import date

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 - register complete SQLAlchemy metadata
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.schemas.insights import GoalUpdate, GlobalGoalsUpdate, WorkspaceGoalUpdate


class PhaseSixModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgresql_compat_migration_adds_phase_six_columns(self):
        statements = []

        class Result:
            def __init__(self, values=()): self.values = values
            def scalars(self): return self.values

        class Connection:
            dialect = type("Dialect", (), {"name": "postgresql"})()

            async def execute(self, statement, params=None):
                sql = str(statement)
                statements.append((sql, params))
                if "information_schema.tables" in sql:
                    return Result(("user_profiles", "study_activities"))
                if "information_schema.columns" in sql:
                    return Result(("id", "created_at"))
                return Result()

        await run_compat_migrations(Connection())
        sql = "\n".join(statement for statement, _ in statements)
        self.assertIn('ALTER TABLE "user_profiles" ADD COLUMN "timezone_name"', sql)
        self.assertIn('ALTER TABLE "study_activities" ADD COLUMN "occurred_at"', sql)
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS ix_study_activities_event_key", sql)

    def test_phase_six_tables_and_columns_are_registered(self):
        self.assertTrue(
            {"study_sessions", "learning_goals", "report_suggestions"}
            <= set(Base.metadata.tables)
        )
        activity = Base.metadata.tables["study_activities"]
        self.assertTrue(
            {"event_key", "source_type", "source_id", "occurred_at", "schema_version"}
            <= set(activity.c.keys())
        )
        profile = Base.metadata.tables["user_profiles"]
        self.assertTrue({"timezone_name", "weekly_goal_days"} <= set(profile.c.keys()))

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

    async def test_compat_migration_adds_activity_and_profile_fields_idempotently(self):
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
                    "CREATE TABLE study_activities (id TEXT PRIMARY KEY, activity_type TEXT, title TEXT, duration_seconds INTEGER, created_at DATETIME)",
                ]
                for ddl in legacy_tables:
                    await connection.execute(text(ddl))
                await connection.execute(text(
                    "INSERT INTO study_activities VALUES "
                    "('legacy', 'review', '旧复习', 20, '2026-09-15 01:02:03')"
                ))
                await connection.run_sync(Base.metadata.create_all)
                await run_compat_migrations(connection)
                await run_compat_migrations(connection)
                activity_columns = {
                    row[1]
                    for row in (await connection.execute(text("PRAGMA table_info(study_activities)"))).fetchall()
                }
                profile_columns = {
                    row[1]
                    for row in (await connection.execute(text("PRAGMA table_info(user_profiles)"))).fetchall()
                }
                row = (await connection.execute(text(
                    "SELECT event_key, source_type, source_id, occurred_at, schema_version "
                    "FROM study_activities WHERE id = 'legacy'"
                ))).one()
                self.assertTrue(
                    {"event_key", "source_type", "source_id", "occurred_at", "schema_version"}
                    <= activity_columns
                )
                self.assertTrue({"timezone_name", "weekly_goal_days"} <= profile_columns)
                self.assertEqual(str(row.occurred_at), "2026-09-15 01:02:03")
                self.assertEqual(row.schema_version, 1)
        finally:
            await engine.dispose()

    async def test_compat_migration_seeds_profile_goals_once(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(text(
                    "INSERT INTO user_profiles "
                    "(id, display_name, daily_goal_minutes, daily_review_target, weekly_goal_days, "
                    "timezone_name, preferred_mode, reminder_time, created_at, updated_at) VALUES "
                    "('profile', '学习者', 35, 11, 6, 'Asia/Shanghai', 'explain', '20:00', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ))
                await run_compat_migrations(connection)
                await run_compat_migrations(connection)
                rows = (await connection.execute(text(
                    "SELECT metric, target_value FROM learning_goals ORDER BY metric"
                ))).all()
                self.assertEqual(rows, [
                    ("daily_minutes", 35.0),
                    ("daily_reviews", 11.0),
                    ("weekly_days", 6.0),
                ])
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
