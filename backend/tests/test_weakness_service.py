"""Explainable weak-knowledge scoring and follow-up task behavior."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog
from app.models.workspace import Workspace
from app.services.weakness_service import (
    AttemptEvidence,
    WeaknessMetrics,
    calculate_weakness,
    recalculate_knowledge_point,
    upsert_weak_learning_tasks,
)


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
METRICS = WeaknessMetrics(
    attempts=(AttemptEvidence(is_correct=False, submitted_at=NOW, duration_seconds=20),),
    unresolved_mistake_count=4,
    review_ratings=(1, 2, 2, 2, 1),
    duration_ratios=(),
    last_relevant_activity_at=None,
)


class WeaknessRuleTests(unittest.TestCase):
    def test_weakness_score_exposes_all_weighted_components(self):
        # A change that removes a weight, treats an ungraded answer as wrong, or
        # renames a component makes this hand-checked 72-point fixture fail.
        score = calculate_weakness(METRICS, NOW)

        self.assertEqual(score.total, 72)
        self.assertEqual(
            set(score.components),
            {"accuracy", "repeat_error", "review_feedback", "response_time", "recency"},
        )

    def test_ungraded_attempts_do_not_lower_accuracy(self):
        score = calculate_weakness(
            WeaknessMetrics(
                attempts=(AttemptEvidence(is_correct=None, submitted_at=NOW, duration_seconds=600),),
                unresolved_mistake_count=0,
                review_ratings=(),
                duration_ratios=(),
                last_relevant_activity_at=None,
            ),
            NOW,
        )

        self.assertEqual(score.components["accuracy"], 0)


class WeaknessPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        workspace = Workspace(name="Weakness", slug="weakness")
        self.db.add(workspace)
        await self.db.flush()
        self.point = KnowledgePoint(
            workspace_id=workspace.id,
            title="Fractions",
            summary="Parts of a whole",
            source_page=7,
        )
        self.db.add(self.point)
        await self.db.flush()
        question = QuizQuestion(
            workspace_id=workspace.id,
            knowledge_point_id=self.point.id,
            question_type="single_choice",
            difficulty_level="medium",
            prompt="Q",
            answer="A",
        )
        card = Flashcard(
            workspace_id=workspace.id,
            knowledge_point_id=self.point.id,
            front="F",
            back="B",
        )
        self.db.add_all([question, card])
        await self.db.flush()
        self.db.add_all([
            QuizAttempt(
                quiz_set_id="set", quiz_run_id="run", question_id=question.id,
                attempt_number=1, is_correct=False, evaluation_status="graded",
                duration_seconds=80, submitted_at=NOW - timedelta(hours=1),
            ),
            MistakeRecord(
                question_id=question.id, knowledge_point_id=self.point.id,
                workspace_id=workspace.id, wrong_count=3, mastery_status="unresolved",
                last_wrong_at=NOW - timedelta(hours=1),
            ),
            ReviewLog(card_id=card.id, rating=1, reviewed_at=NOW - timedelta(hours=2)),
        ])
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_recalculation_keeps_one_pending_task_per_point_and_type(self):
        # Removing the pending-task lookup would create four rows instead of two.
        state = await recalculate_knowledge_point(self.db, self.point.id, NOW)
        first = await upsert_weak_learning_tasks(self.db, state, NOW)
        second = await upsert_weak_learning_tasks(self.db, state, NOW)
        rows = (await self.db.execute(select(LearningTask))).scalars().all()

        self.assertGreaterEqual(state.weakness_score, 60)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.task_type for row in rows}, {"review", "targeted_practice"})
        self.assertTrue(all(row.due_at <= NOW + timedelta(days=3) for row in rows))
        self.assertEqual(len(state.recommended_actions), 5)
        self.assertTrue(all("?" in action["path"] for action in state.recommended_actions))


if __name__ == "__main__":
    unittest.main()
