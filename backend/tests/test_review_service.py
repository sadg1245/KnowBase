"""Review scheduling, mastery, and timing behavior."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, ReviewLog, StudyActivity
from app.models.workspace import Workspace
from app.services.review_service import (
    apply_card_review,
    mastery_after_review,
    mastery_status_for,
    schedule_review,
)


class ReviewRuleTests(unittest.TestCase):
    def test_mastery_rules_use_literal_deltas_and_thresholds(self):
        self.assertEqual(mastery_after_review(0.50, 1), 0.38)
        self.assertEqual(mastery_after_review(0.50, 2), 0.52)
        self.assertEqual(mastery_after_review(0.70, 3), 0.82)
        self.assertEqual(mastery_after_review(0.90, 4), 1.0)
        self.assertEqual(mastery_after_review(0.05, 1), 0.0)
        self.assertEqual(mastery_status_for(0.0, 0), "not_started")
        self.assertEqual(mastery_status_for(0.0, 1), "learning")
        self.assertEqual(mastery_status_for(0.79, 2), "learning")
        self.assertEqual(mastery_status_for(0.8, 1), "mastered")

    def test_review_schedule_keeps_simple_v1_intervals(self):
        self.assertEqual(schedule_review(0, 2.5, 1), (1, 2.3))
        self.assertEqual(schedule_review(0, 2.5, 4), (3, 2.6))
        self.assertEqual(schedule_review(7, 2.5, 3), (18, 2.5))


class ReviewTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_review_updates_card_point_log_and_real_activity_duration(self):
        fixed_now = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
        async with self.sessions() as db:
            workspace = Workspace(name="Memory", slug="memory")
            db.add(workspace)
            await db.flush()
            point = KnowledgePoint(
                workspace_id=workspace.id,
                title="Spacing",
                summary="Review over time",
                mastery=0.70,
                mastery_status="learning",
            )
            db.add(point)
            await db.flush()
            card = Flashcard(
                workspace_id=workspace.id,
                knowledge_point_id=point.id,
                front="What is spacing?",
                back="Review over time",
                interval_days=2,
                mastery=0.70,
                mastery_status="learning",
            )
            db.add(card)
            await db.flush()

            change = await apply_card_review(
                db,
                card,
                rating=3,
                duration_seconds=17,
                now=fixed_now,
            )

            self.assertEqual(card.interval_days, 5)
            self.assertEqual(card.review_count, 1)
            self.assertEqual(card.mastery, 0.82)
            self.assertEqual(card.mastery_status, "mastered")
            self.assertEqual(card.due_at, fixed_now + timedelta(days=5))
            self.assertEqual(card.last_reviewed_at, fixed_now)
            self.assertEqual(card.total_review_seconds, 17)
            self.assertEqual(point.mastery, 0.82)
            self.assertEqual(point.mastery_status, "mastered")
            self.assertEqual(change["previous_mastery"], 0.70)
            self.assertEqual(change["next_mastery"], 0.82)
            self.assertEqual(change["previous_interval"], 2)
            self.assertEqual(change["next_interval"], 5)
            self.assertEqual(change["duration_seconds"], 17)

            review = (await db.execute(select(ReviewLog))).scalar_one()
            self.assertEqual(review.duration_seconds, 17)
            self.assertEqual(review.previous_mastery, 0.70)
            self.assertEqual(review.next_mastery, 0.82)
            self.assertEqual(review.previous_status, "learning")
            self.assertEqual(review.next_status, "mastered")
            self.assertEqual(review.algorithm_version, "simple_v1")
            activity = (await db.execute(select(StudyActivity))).scalar_one()
            self.assertEqual(activity.duration_seconds, 17)
            self.assertEqual(activity.payload["rating"], 3)
            self.assertEqual(activity.payload["card_id"], card.id)

    async def test_forgotten_unlinked_card_clamps_mastery_and_stays_learning(self):
        fixed_now = datetime(2026, 8, 29, 4, 0, tzinfo=timezone.utc)
        async with self.sessions() as db:
            workspace = Workspace(name="Memory", slug="memory-two")
            db.add(workspace)
            await db.flush()
            card = Flashcard(
                workspace_id=workspace.id,
                front="Question",
                back="Answer",
                mastery=0.05,
                mastery_status="learning",
                review_count=3,
                total_review_seconds=9,
            )
            db.add(card)
            await db.flush()

            await apply_card_review(db, card, rating=1, duration_seconds=4, now=fixed_now)

            self.assertEqual(card.mastery, 0.0)
            self.assertEqual(card.mastery_status, "learning")
            self.assertEqual(card.interval_days, 1)
            self.assertEqual(card.review_count, 4)
            self.assertEqual(card.total_review_seconds, 13)


if __name__ == "__main__":
    unittest.main()
