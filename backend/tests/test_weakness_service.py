"""Explainable weak-knowledge scoring and follow-up task behavior."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity
from tests.support import create_user, create_workspace
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
    review_ratings=(1,),
    duration_ratios=(1.9,),
    last_relevant_activity_at=NOW,
)


class WeaknessRuleTests(unittest.TestCase):
    def test_weakness_score_exposes_all_weighted_components(self):
        # A change that removes a weight, treats an ungraded answer as wrong, or
        # reverses recency makes this hand-checked current-activity fixture fail.
        score = calculate_weakness(METRICS, NOW)

        self.assertEqual(score.total, 84)
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

    def test_recency_grows_with_time_and_missing_evidence_is_neutral(self):
        def metrics(activity_at):
            return WeaknessMetrics((), 0, (), (), activity_at)

        self.assertEqual(calculate_weakness(metrics(NOW), NOW).components["recency"], 0)
        self.assertEqual(
            calculate_weakness(metrics(NOW - timedelta(days=30)), NOW).components["recency"],
            100,
        )
        self.assertEqual(calculate_weakness(metrics(None), NOW).components["recency"], 50)


class WeaknessPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(
            self.db, self.user, name="Weakness", slug="weakness"
        )
        self.point = KnowledgePoint(
            workspace_id=self.workspace.id,
            title="Fractions",
            summary="Parts of a whole",
            source_page=7,
        )
        self.db.add(self.point)
        await self.db.flush()
        self.question = QuizQuestion(
            workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id,
            question_type="single_choice",
            difficulty_level="medium",
            prompt="Q",
            answer="A",
        )
        card = Flashcard(
            workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id,
            front="F",
            back="B",
        )
        self.db.add_all([self.question, card])
        await self.db.flush()
        self.db.add_all([
            QuizAttempt(
                quiz_set_id="set", quiz_run_id="run", question_id=self.question.id,
                attempt_number=1, is_correct=False, evaluation_status="graded",
                duration_seconds=190, submitted_at=NOW - timedelta(hours=1),
            ),
            MistakeRecord(
                question_id=self.question.id, knowledge_point_id=self.point.id,
                workspace_id=self.workspace.id, wrong_count=4, mastery_status="unresolved",
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
        evidence = (await self.db.execute(select(StudyActivity).where(
            StudyActivity.activity_type == "weakness_changed"
        ))).scalars().all()
        self.assertEqual(len(evidence), 1)
        self.assertIsNone(evidence[0].payload["before_score"])
        self.assertEqual(evidence[0].payload["after_score"], state.weakness_score)
        paths = {action["type"]: action["path"] for action in state.recommended_actions}
        self.assertEqual(paths["review"], "/review")
        self.assertTrue(all("?" in path for kind, path in paths.items() if kind != "review"))

    async def test_failed_attempts_after_graded_attempt_do_not_evict_scoring_window(self):
        # The pre-fix LIMIT selected these 20 failures before filtering, making the
        # one scored error disappear from accuracy and duration evidence.
        baseline_point = KnowledgePoint(
            workspace_id=self.workspace.id, title="Baseline", summary="B",
        )
        self.db.add(baseline_point)
        await self.db.flush()
        for index in range(3):
            question = QuizQuestion(
                workspace_id=self.workspace.id, knowledge_point_id=baseline_point.id,
                question_type="single_choice", difficulty_level="medium",
                prompt=f"Baseline {index}", answer="A",
            )
            self.db.add(question)
            await self.db.flush()
            self.db.add(QuizAttempt(
                quiz_set_id=f"baseline-set-{index}", quiz_run_id=f"baseline-run-{index}",
                question_id=question.id, attempt_number=1, is_correct=True,
                evaluation_status="graded", duration_seconds=100,
                submitted_at=NOW - timedelta(days=1),
            ))
        for index in range(20):
            question = QuizQuestion(
                workspace_id=self.workspace.id, knowledge_point_id=self.point.id,
                question_type="short_answer", difficulty_level="medium",
                prompt=f"Failed {index}", answer="A",
            )
            self.db.add(question)
            await self.db.flush()
            self.db.add(QuizAttempt(
                quiz_set_id=f"failed-set-{index}", quiz_run_id=f"failed-run-{index}",
                question_id=question.id, attempt_number=1, is_correct=None,
                evaluation_status="failed", duration_seconds=999,
                submitted_at=NOW - timedelta(minutes=index),
            ))
        await self.db.flush()

        state = await recalculate_knowledge_point(self.db, self.point.id, NOW)

        self.assertEqual(state.evidence["graded_attempt_count"], 1)
        self.assertEqual(state.accuracy_component, 100)
        self.assertEqual(state.response_time_component, 90)
        self.assertEqual(state.weakness_score, 84)

    async def test_recent_completed_task_and_activity_are_point_scoped(self):
        target = KnowledgePoint(workspace_id=self.workspace.id, title="Target", summary="T")
        other = KnowledgePoint(workspace_id=self.workspace.id, title="Other", summary="O")
        self.db.add_all([target, other])
        await self.db.flush()
        self.db.add_all([
            LearningTask(
                workspace_id=self.workspace.id, knowledge_point_id=target.id,
                task_type="review", title="Old target", status="completed",
                completed_at=NOW - timedelta(days=20),
            ),
            LearningTask(
                workspace_id=self.workspace.id, knowledge_point_id=other.id,
                task_type="review", title="Recent other", status="completed", completed_at=NOW,
            ),
            StudyActivity(
                user_id=self.user.id,
                workspace_id=self.workspace.id, activity_type="task_completed", title="Other activity",
                payload={"knowledge_point_id": other.id}, created_at=NOW,
            ),
        ])
        await self.db.flush()

        stale = await recalculate_knowledge_point(self.db, target.id, NOW)
        stale_recency = stale.recency_component
        self.db.add(LearningTask(
            workspace_id=self.workspace.id, knowledge_point_id=target.id,
            task_type="targeted_practice", title="Recent target", status="completed", completed_at=NOW,
        ))
        self.db.add(StudyActivity(
            user_id=self.user.id,
            workspace_id=self.workspace.id, activity_type="task_completed", title="Target activity",
            payload={"knowledge_point_id": target.id}, created_at=NOW,
        ))
        await self.db.flush()
        recent = await recalculate_knowledge_point(self.db, target.id, NOW)

        self.assertGreater(stale_recency, 60)
        self.assertEqual(recent.recency_component, 0)


if __name__ == "__main__":
    unittest.main()
