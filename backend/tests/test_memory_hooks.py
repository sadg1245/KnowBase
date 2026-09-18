"""Best-effort memory hooks must never break the learning main flow."""

import unittest
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.migrations import ensure_memory_index
from app.models.assessment import MistakeRecord
from app.models.base import Base
from app.models.chat import ChatSession
from app.models.learning import KnowledgePoint, QuizQuestion
from app.services import learning_memory
from tests.support import create_user, create_workspace


class RecordingService:
    def __init__(self, calls, *, explode=False):
        self.calls = calls
        self.explode = explode

    async def remember(self, **kwargs):
        if self.explode:
            raise RuntimeError("memory backend offline")
        self.calls.append(kwargs)
        return None


class MemoryHookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await ensure_memory_index(connection)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(self.db, self.user)
        self.calls: list[dict] = []

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _question(self) -> QuizQuestion:
        point = KnowledgePoint(workspace_id=self.workspace.id, title="闭包", mastery=0.4)
        self.db.add(point)
        await self.db.flush()
        question = QuizQuestion(
            workspace_id=self.workspace.id, prompt="闭包捕获什么", answer="变量绑定",
            knowledge_point_id=point.id,
        )
        self.db.add(question)
        await self.db.flush()
        return question

    async def test_summary_note_creates_session_summary_memory(self):
        session = ChatSession(user_id=self.user.id, workspace_id=self.workspace.id, title="闭包会话")
        self.db.add(session)
        await self.db.flush()

        await learning_memory.remember_session_summary(
            self.db,
            user_id=self.user.id,
            session=session,
            content="这一节把闭包和作用域链讲完了。",
            service=RecordingService(self.calls),
        )

        self.assertEqual(self.calls[0]["kind"], "session_summary")
        self.assertEqual(self.calls[0]["source_refs"], {"session_id": session.id})
        self.assertEqual(self.calls[0]["workspace_id"], self.workspace.id)

    async def test_mistake_pattern_needs_two_errors_in_the_window(self):
        question = await self._question()
        self.db.add(MistakeRecord(
            question_id=question.id, workspace_id=self.workspace.id,
            knowledge_point_id=question.knowledge_point_id,
            error_reason="循环变量绑定错误",
            last_wrong_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()

        await learning_memory.remember_mistake_pattern(
            self.db, workspace_id=self.workspace.id, question_id=question.id,
            service=RecordingService(self.calls),
        )
        self.assertEqual(self.calls, [])

        second = QuizQuestion(
            workspace_id=self.workspace.id, prompt="第二题", answer="A",
            knowledge_point_id=question.knowledge_point_id,
        )
        self.db.add(second)
        await self.db.flush()
        self.db.add(MistakeRecord(
            question_id=second.id, workspace_id=self.workspace.id,
            knowledge_point_id=question.knowledge_point_id,
            error_reason="循环变量绑定错误",
            last_wrong_at=datetime.now(timezone.utc),
        ))
        await self.db.flush()

        await learning_memory.remember_mistake_pattern(
            self.db, workspace_id=self.workspace.id, question_id=question.id,
            service=RecordingService(self.calls),
        )

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["kind"], "mistake_pattern")
        self.assertIn("循环变量绑定错误", self.calls[0]["content"])

    async def test_report_insight_is_stored_with_its_period(self):
        await learning_memory.remember_report_insight(
            self.db,
            user_id=self.user.id,
            period_type="week",
            suggestion="本周优先复习闭包。",
            service=RecordingService(self.calls),
        )

        self.assertEqual(self.calls[0]["kind"], "insight")
        self.assertEqual(self.calls[0]["source_refs"]["period_type"], "week")

    async def test_hook_failure_is_isolated(self):
        session = ChatSession(user_id=self.user.id, workspace_id=self.workspace.id, title="会话")
        self.db.add(session)
        await self.db.flush()

        await learning_memory.remember_session_summary(
            self.db,
            user_id=self.user.id,
            session=session,
            content="内容",
            service=RecordingService(self.calls, explode=True),
        )

        self.assertEqual(self.calls, [])

    async def test_hook_db_level_failure_leaves_the_session_usable(self):
        """A failing flush must not poison the caller's session or abort its commit."""
        session = ChatSession(user_id=self.user.id, workspace_id=self.workspace.id, title="会话")
        self.db.add(session)
        await self.db.flush()

        class ExplodingService:
            def __init__(self, db):
                self.db = db

            async def remember(self, **kwargs):
                await self.db.execute(text("SELECT * FROM table_that_does_not_exist"))
                return None

        await learning_memory.remember_session_summary(
            self.db,
            user_id=self.user.id,
            session=session,
            content="内容",
            service=ExplodingService(self.db),
        )

        # The caller's own work must still be committable after the best-effort write failed.
        self.assertEqual((await self.db.execute(text("SELECT 1"))).scalar(), 1)
        await self.db.commit()


if __name__ == "__main__":
    unittest.main()
