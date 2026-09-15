"""Behavior tests for the append-only activity ledger and active study sessions."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.document import Document
from app.models.learning import StudyActivity
from app.models.workspace import Workspace
from app.schemas.insights import StudySessionStart
from app.services.activity_service import InvalidActivityType, append_activity
from app.services.study_session_service import (
    SessionCompleted,
    expire_stale_sessions,
    finish_session,
    heartbeat_session,
    start_session,
)


NOW = datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)


class ActivitySessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.workspace = Workspace(name="Calculus", slug="calculus")
        self.db.add(self.workspace)
        await self.db.flush()
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="limits.pdf",
            file_path="limits.pdf",
            file_type=".pdf",
        )
        self.db.add(self.document)
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_duplicate_event_key_returns_original_without_mutating_it(self):
        first = await append_activity(
            self.db,
            event_key="activity:card:1",
            activity_type="card_created",
            title="创建卡片",
            source_type="flashcard",
            source_id="1",
            occurred_at=NOW,
        )
        second = await append_activity(
            self.db,
            event_key="activity:card:1",
            activity_type="card_created",
            title="不应覆盖",
            source_type="flashcard",
            source_id="1",
            occurred_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.title, "创建卡片")
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 1)

    async def test_unknown_activity_type_is_rejected_before_persistence(self):
        with self.assertRaises(InvalidActivityType):
            await append_activity(
                self.db,
                event_key="bad:1",
                activity_type="mouse_moved",
                title="不允许",
                source_type="document",
                source_id=self.document.id,
            )
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 0)

    async def test_heartbeat_counts_ordered_intervals_once_and_caps_long_gap(self):
        session = await start_session(
            self.db,
            StudySessionStart(
                id="session-1",
                context_type="document",
                context_id=self.document.id,
                workspace_id=self.workspace.id,
            ),
            NOW,
        )
        await heartbeat_session(self.db, session.id, 1, NOW + timedelta(seconds=30))
        duplicate = await heartbeat_session(self.db, session.id, 1, NOW + timedelta(seconds=31))
        duplicate_seconds = duplicate.active_seconds
        result = await heartbeat_session(self.db, session.id, 2, NOW + timedelta(seconds=150))
        self.assertEqual(duplicate_seconds, 30)
        self.assertEqual(result.active_seconds, 90)
        self.assertEqual(result.last_sequence, 2)

    async def test_finish_is_idempotent_and_creates_one_document_read_activity(self):
        session = await start_session(
            self.db,
            StudySessionStart(
                id="session-2",
                context_type="document",
                context_id=self.document.id,
                workspace_id=self.workspace.id,
            ),
            NOW,
        )
        await heartbeat_session(self.db, session.id, 1, NOW + timedelta(seconds=30))
        first = await finish_session(self.db, session.id, 1, NOW + timedelta(seconds=35))
        second = await finish_session(self.db, session.id, 1, NOW + timedelta(seconds=40))
        self.assertEqual(first.activity.id, second.activity.id)
        self.assertEqual(first.session.status, "completed")
        self.assertEqual(first.activity.activity_type, "document_read")
        self.assertEqual(first.activity.duration_seconds, 30)
        self.assertEqual(first.activity.source_id, session.id)
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 1)

    async def test_completed_session_rejects_new_heartbeat(self):
        session = await start_session(
            self.db,
            StudySessionStart(
                id="session-3",
                context_type="document",
                context_id=self.document.id,
                workspace_id=self.workspace.id,
            ),
            NOW,
        )
        await finish_session(self.db, session.id, 0, NOW + timedelta(seconds=1))
        with self.assertRaises(SessionCompleted):
            await heartbeat_session(self.db, session.id, 1, NOW + timedelta(seconds=30))

    async def test_stale_session_expires_and_keeps_accumulated_time(self):
        session = await start_session(
            self.db,
            StudySessionStart(
                id="session-stale",
                context_type="document",
                context_id=self.document.id,
                workspace_id=self.workspace.id,
            ),
            NOW,
        )
        await heartbeat_session(self.db, session.id, 1, NOW + timedelta(seconds=30))
        expired = await expire_stale_sessions(self.db, NOW + timedelta(hours=12, seconds=1))
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].session.status, "expired")
        self.assertEqual(expired[0].activity.duration_seconds, 30)


if __name__ == "__main__":
    unittest.main()
