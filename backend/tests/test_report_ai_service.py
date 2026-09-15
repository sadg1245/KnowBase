"""AI report suggestion snapshot cache and failure persistence tests."""

import unittest
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.learning import ReportSuggestion, UserProfile
from app.services import report_ai_service


class ReportAIServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.db.add(UserProfile(timezone_name="Asia/Shanghai"))
        await self.db.flush()
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
        )
        second = await report_ai_service.generate_suggestion(
            self.db, self.settings, "week", date(2026, 9, 16), completion=completion
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
            )
        await self.db.rollback()
        row = await self.db.scalar(select(ReportSuggestion))
        self.assertEqual(row.status, "failed")
        self.assertIn("provider unavailable", row.error_message)

        async def success(_prompt):
            return "今天先完成复习。", "model-x"

        retried = await report_ai_service.generate_suggestion(
            self.db, self.settings, "day", date(2026, 9, 15), completion=success
        )
        self.assertEqual(retried["id"], row.id)
        self.assertEqual(retried["status"], "ready")


if __name__ == "__main__":
    unittest.main()
