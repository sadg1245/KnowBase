"""Daily review summary behavior across local-day boundaries."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, ReviewLog, StudyActivity, UserProfile
from app.models.workspace import Workspace
from app.services.review_service import build_review_summary, local_day_bounds


class LocalDayTests(unittest.TestCase):
    def test_local_day_bounds_convert_china_midnight_to_utc(self):
        now = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
        start, end = local_day_bounds(now, 480)
        self.assertEqual(start, datetime(2026, 8, 28, 16, 0, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc))


class ReviewSummaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_summary_uses_local_day_for_due_completed_overdue_and_streak(self):
        now = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
        async with self.sessions() as db:
            workspace = Workspace(name="Review", slug="review")
            profile = UserProfile(display_name="Learner", daily_review_target=12)
            db.add_all([workspace, profile])
            await db.flush()
            key_point = KnowledgePoint(
                workspace_id=workspace.id,
                title="Key weak point",
                summary="Key",
                mastery=0.4,
                mastery_status="learning",
                importance=5,
                is_key=True,
            )
            weak_point = KnowledgePoint(
                workspace_id=workspace.id,
                title="Weak point",
                summary="Weak",
                mastery=0.1,
                mastery_status="learning",
                importance=3,
            )
            db.add_all([key_point, weak_point])
            await db.flush()
            overdue = Flashcard(
                workspace_id=workspace.id,
                knowledge_point_id=key_point.id,
                front="Overdue",
                back="A",
                due_at=datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc),
                review_count=0,
            )
            due = Flashcard(
                workspace_id=workspace.id,
                knowledge_point_id=weak_point.id,
                front="Due",
                back="A",
                due_at=datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc),
                review_count=2,
            )
            future = Flashcard(
                workspace_id=workspace.id,
                front="Future",
                back="A",
                due_at=now + timedelta(days=1),
            )
            db.add_all([overdue, due, future])
            await db.flush()
            db.add_all([
                ReviewLog(
                    card_id=due.id,
                    rating=3,
                    duration_seconds=45,
                    reviewed_at=datetime(2026, 8, 28, 17, 0, tzinfo=timezone.utc),
                ),
                ReviewLog(
                    card_id=due.id,
                    rating=4,
                    duration_seconds=15,
                    reviewed_at=datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc),
                ),
                StudyActivity(
                    workspace_id=workspace.id,
                    activity_type="read",
                    title="Yesterday",
                    created_at=datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc),
                ),
                StudyActivity(
                    workspace_id=workspace.id,
                    activity_type="read",
                    title="Two days ago",
                    created_at=datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc),
                ),
            ])
            await db.flush()

            summary = await build_review_summary(db, timezone_offset_minutes=480, now=now)

            self.assertEqual(summary["due_count"], 2)
            self.assertEqual(summary["new_count"], 1)
            self.assertEqual(summary["completed_today"], 2)
            self.assertEqual(summary["overdue_count"], 1)
            self.assertEqual(summary["estimated_minutes"], 1)
            self.assertEqual(summary["streak_days"], 3)
            self.assertEqual(summary["daily_target"], 12)
            self.assertEqual(
                [point["title"] for point in summary["weak_points"]],
                ["Key weak point", "Weak point"],
            )

    async def test_summary_uses_thirty_second_default_without_review_history(self):
        now = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
        async with self.sessions() as db:
            workspace = Workspace(name="Review", slug="review-empty")
            db.add(workspace)
            await db.flush()
            for index in range(3):
                db.add(Flashcard(
                    workspace_id=workspace.id,
                    front=f"Q{index}",
                    back="A",
                    due_at=now - timedelta(minutes=index),
                ))
            await db.flush()

            summary = await build_review_summary(db, timezone_offset_minutes=0, now=now)

            self.assertEqual(summary["due_count"], 3)
            self.assertEqual(summary["estimated_minutes"], 2)
            self.assertEqual(summary["completed_today"], 0)
            self.assertEqual(summary["streak_days"], 0)
            self.assertEqual(summary["daily_target"], 10)


if __name__ == "__main__":
    unittest.main()
