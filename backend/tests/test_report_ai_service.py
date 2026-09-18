"""AI report suggestion snapshot cache and failure persistence tests."""

import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.learning import ReportSuggestion
from app.services import report_ai_service
from tests.support import create_preferences, create_user


class ReportAIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        await create_preferences(self.db, self.user, timezone_name="Asia/Shanghai")
        self.settings = SimpleNamespace(DEFAULT_LLM_PROVIDER="test", DEFAULT_LLM_MODEL="model-x")

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_same_snapshot_reuses_ready_suggestion(self):
        calls = 0

        async def completion(prompt):
            nonlocal calls
            calls += 1
            self.assertIn("学习报告", prompt)
            return "先复习薄弱点。", "model-x"

        first = await report_ai_service.generate_suggestion(
            self.db, self.settings, "week", date(2026, 9, 16), completion=completion
            , user_id=self.user.id
        )
        second = await report_ai_service.generate_suggestion(
            self.db, self.settings, "week", date(2026, 9, 16), completion=completion
            , user_id=self.user.id
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(calls, 1)
        self.assertEqual(first["status"], "ready")

    async def test_failure_is_persisted_and_can_be_retried(self):
        async def failure(_prompt):
            raise RuntimeError("provider unavailable")

        with self.assertRaises(report_ai_service.ReportAIError):
            await report_ai_service.generate_suggestion(
                self.db, self.settings, "day", date(2026, 9, 15), completion=failure
                , user_id=self.user.id
            )
        await self.db.rollback()
        row = await self.db.scalar(select(ReportSuggestion))
        self.assertEqual(row.status, "failed")
        self.assertIn("provider unavailable", row.error_message)

        async def success(_prompt):
            return "今天先完成复习。", "model-x"

        retried = await report_ai_service.generate_suggestion(
            self.db, self.settings, "day", date(2026, 9, 15), completion=success
            , user_id=self.user.id
        )
        self.assertEqual(retried["id"], row.id)
        self.assertEqual(retried["status"], "ready")

    async def test_existing_pending_generation_has_one_owner(self):
        self.db.add(ReportSuggestion(
            user_id=self.user.id,
            period_type="week", period_start=datetime(2026, 9, 13, 16, tzinfo=timezone.utc),
            period_end=datetime(2026, 9, 20, 16, tzinfo=timezone.utc),
            timezone_name="Asia/Shanghai", stats_hash="placeholder",
            stats_snapshot={}, status="pending",
        ))
        await self.db.commit()
        # Use the actual snapshot identity so this row represents a concurrent owner.
        report = await report_ai_service.report_service.build_report(
            self.db, "week", date(2026, 9, 16), now=datetime.now(timezone.utc),
            user_id=self.user.id,
        )
        row = await self.db.scalar(select(ReportSuggestion))
        row.period_start = datetime.fromisoformat(report["period"]["utc_start"])
        row.period_end = datetime.fromisoformat(report["period"]["utc_end"])
        row.stats_hash = report_ai_service.snapshot_hash(report_ai_service.canonical_snapshot(report))
        await self.db.commit()
        calls = 0

        async def completion(_prompt):
            nonlocal calls
            calls += 1
            return "不应调用", "model-x"

        result = await report_ai_service.generate_suggestion(
            self.db, self.settings, "week", date(2026, 9, 16), completion=completion
            , user_id=self.user.id
        )
        self.assertEqual(result["status"], "pending")
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
