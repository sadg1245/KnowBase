"""Deterministic natural-period reporting and evidence contracts."""

import unittest
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.assessment import QuizAttempt, QuizRun, QuizSet
from app.models.base import Base
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.services import report_service
from tests.support import create_preferences, create_user, create_workspace


NOW = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)


class ReportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        await create_preferences(self.db, self.user, timezone_name="Asia/Shanghai")
        self.workspace = await create_workspace(
            self.db, self.user, name="Reports", slug="reports"
        )

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _quiz_attempts(self):
        quiz_set = QuizSet(workspace_id=self.workspace.id, title="Test", status="ready", question_count=3)
        self.db.add(quiz_set)
        await self.db.flush()
        run = QuizRun(quiz_set_id=quiz_set.id, round_number=1)
        self.db.add(run)
        await self.db.flush()
        for index, (score, maximum, status) in enumerate(((1, 1, "graded"), (.5, 1, "graded"), (None, 1, "pending"))):
            question = QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=quiz_set.id,
                                    prompt=f"Q{index}", answer="A")
            self.db.add(question)
            await self.db.flush()
            self.db.add(QuizAttempt(
                quiz_set_id=quiz_set.id, quiz_run_id=run.id, question_id=question.id,
                attempt_number=1, score=score, max_score=maximum,
                evaluation_status=status, duration_seconds=30,
                submitted_at=datetime(2026, 9, 15, 2 + index, tzinfo=timezone.utc),
            ))

    async def test_week_report_aggregates_metrics_changes_and_daily_buckets(self):
        self.db.add_all([
            StudyActivity(user_id=self.user.id, activity_type="document_read", title="read", duration_seconds=600,
                          occurred_at=datetime(2026, 9, 15, 2, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="conversation_completed", title="chat", duration_seconds=300,
                          occurred_at=datetime(2026, 9, 16, 2, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="review_completed", title="r1", source_id="r1",
                          occurred_at=datetime(2026, 9, 15, 3, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="review", title="r2",
                          occurred_at=datetime(2026, 9, 16, 3, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="mastery_changed", title="m", payload={
                "before_mastery": .3, "after_mastery": .6,
            }, occurred_at=datetime(2026, 9, 15, 4, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="weakness_changed", title="w1", payload={
                "before_score": 80, "after_score": 50,
            }, occurred_at=datetime(2026, 9, 15, 5, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="weakness_changed", title="w2", payload={
                "before_score": 20, "after_score": 40,
            }, occurred_at=datetime(2026, 9, 15, 6, tzinfo=timezone.utc)),
        ])
        self.db.add(KnowledgePoint(
            workspace_id=self.workspace.id, title="New",
            created_at=datetime(2026, 9, 15, 7, tzinfo=timezone.utc),
        ))
        await self._quiz_attempts()
        await self.db.flush()

        report = await report_service.build_report(
            self.db, "week", date(2026, 9, 16), now=NOW, user_id=self.user.id
        )

        self.assertEqual(report["period"]["local_start"], "2026-09-14")
        self.assertEqual(report["total_active_seconds"], 900)
        self.assertEqual(report["activity_count"], 4)
        self.assertEqual(report["review_count"], 2)
        self.assertEqual(report["quiz_accuracy"], 75.0)
        self.assertEqual(report["pending_grading_count"], 1)
        self.assertEqual(report["new_knowledge_points"], 1)
        self.assertAlmostEqual(report["mastery_delta"], 30.0)
        self.assertEqual(report["weakness_changes"], {"improved": 1, "worsened": 1, "unchanged": 0})
        self.assertEqual(len(report["trend"]), 7)
        self.assertTrue(all("evidence_query" in metric for metric in report["metrics"].values()))
        self.assertIsNone(report["comparisons"]["learning_time"]["percent_change"])

    async def test_day_report_accuracy_excludes_pending_ai_attempts(self):
        await self._quiz_attempts()
        await self.db.flush()
        report = await report_service.build_report(
            self.db, "day", date(2026, 9, 15), now=NOW, user_id=self.user.id
        )
        self.assertEqual(report["quiz_accuracy"], 75.0)
        self.assertEqual(report["pending_grading_count"], 1)

    async def test_metric_evidence_reconstructs_time_and_labels_legacy_sources(self):
        self.db.add_all([
            StudyActivity(user_id=self.user.id, event_key="activity:study-session:s1", activity_type="document_read",
                          title="阅读资料", workspace_id=self.workspace.id,
                          source_type="study_session", source_id="s1", duration_seconds=600,
                          occurred_at=datetime(2026, 9, 15, 2, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="organize", title="旧记录", duration_seconds=60,
                          occurred_at=datetime(2026, 9, 15, 3, tzinfo=timezone.utc)),
        ])
        await self.db.flush()
        report = await report_service.build_report(
            self.db, "day", date(2026, 9, 15), now=NOW, user_id=self.user.id
        )
        first = await report_service.get_metric_evidence(
            self.db, "day", date(2026, 9, 15), "learning_time", limit=1,
            user_id=self.user.id,
        )
        second = await report_service.get_metric_evidence(
            self.db, "day", date(2026, 9, 15), "learning_time", cursor=first["next_cursor"], limit=5,
            user_id=self.user.id,
        )
        items = first["items"] + second["items"]
        self.assertEqual(sum(item["duration_seconds"] for item in items), report["total_active_seconds"])
        self.assertTrue(any(item["source_label"] == "历史记录" for item in items))
        with self.assertRaises(report_service.InvalidEvidenceCursor):
            await report_service.get_metric_evidence(
                self.db, "week", date(2026, 9, 15), "learning_time",
                cursor=first["next_cursor"], limit=5, user_id=self.user.id,
            )

    async def test_legacy_rolling_report_preserves_public_keys(self):
        self.db.add(StudyActivity(
            user_id=self.user.id, activity_type="document_read", title="read", duration_seconds=120,
            occurred_at=NOW,
        ))
        await self.db.flush()
        report = await report_service.build_legacy_report(
            self.db, days=7, now=NOW, user_id=self.user.id
        )
        self.assertEqual(set(report), {
            "days", "total_minutes", "activity_count", "review_count", "quiz_accuracy",
            "mastered_points", "total_points", "daily", "suggestion",
        })
        self.assertEqual(report["total_minutes"], 2)


if __name__ == "__main__":
    unittest.main()
