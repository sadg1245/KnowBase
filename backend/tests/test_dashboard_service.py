"""Evidence-based dashboard task, streak, and recommendation tests."""

import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.assessment import LearningTask, MistakeRecord, WeakKnowledgeState
from app.models.base import Base
from app.models.document import Document
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, StudyActivity
from app.schemas.insights import GlobalGoalsUpdate, WorkspaceGoalUpdate
from app.services import dashboard_service, goal_service
from tests.support import create_user, create_workspace


NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


class DashboardServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(
            self.db, self.user, name="Algorithms", slug="dashboard-algorithms"
        )
        await goal_service.update_global_goals(self.db, GlobalGoalsUpdate(
            daily_minutes=30,
            daily_reviews=7,
            weekly_days=5,
            target_completion_date=date(2026, 12, 31),
            timezone_name="Asia/Shanghai",
        ), now=NOW, user_id=self.user.id)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_dashboard_caps_and_orders_real_tasks_with_real_sources(self):
        point = KnowledgePoint(workspace_id=self.workspace.id, title="Graphs", mastery=.4)
        self.db.add(point)
        await self.db.flush()
        for index in range(9):
            self.db.add(Flashcard(
                workspace_id=self.workspace.id, front=f"F{index}", back="B",
                due_at=NOW - timedelta(minutes=1),
            ))
        for index, status in enumerate(("unresolved", "learning", "mastered")):
            question = QuizQuestion(
                workspace_id=self.workspace.id, prompt=f"Q{index}", answer="A",
                knowledge_point_id=point.id,
            )
            self.db.add(question)
            await self.db.flush()
            self.db.add(MistakeRecord(
                question_id=question.id, workspace_id=self.workspace.id,
                knowledge_point_id=point.id, mastery_status=status,
            ))
        task = LearningTask(
            workspace_id=self.workspace.id, knowledge_point_id=point.id,
            task_type="targeted_practice", title="巩固图论", path="/practice",
            due_at=NOW - timedelta(minutes=2), priority=90,
        )
        self.db.add(task)
        await self.db.flush()
        await goal_service.update_workspace_goal(
            self.db, self.workspace.id,
            WorkspaceGoalUpdate(target_mastery=80, target_date=date(2026, 9, 20)),
            now=NOW,
            user_id=self.user.id,
        )
        self.db.add(StudyActivity(
            user_id=self.user.id,
            activity_type="document_read", title="read", duration_seconds=300,
            workspace_id=self.workspace.id,
            occurred_at=datetime(2026, 9, 14, 16, 30, tzinfo=timezone.utc),
        ))
        await self.db.flush()

        view = await dashboard_service.build_dashboard(self.db, now=NOW, user_id=self.user.id)

        self.assertLessEqual(len(view["today_tasks"]), 5)
        self.assertEqual([row["type"] for row in view["today_tasks"]], [
            "review", "mistake", "targeted_practice", "workspace_goal", "study_time"
        ])
        self.assertEqual(view["today_tasks"][0]["count"], 7)
        self.assertEqual(view["today_tasks"][0]["status"], "pending")
        self.assertEqual(view["today_tasks"][1]["count"], 2)
        self.assertEqual(view["today_tasks"][2]["id"], task.id)
        self.assertEqual(view["stats"]["today_minutes"], 5)

    async def test_user_timezone_streak_and_completed_derived_tasks_remain_visible(self):
        self.db.add_all([
            StudyActivity(user_id=self.user.id, activity_type="question_asked", title="today",
                          occurred_at=datetime(2026, 9, 14, 16, 5, tzinfo=timezone.utc)),
            StudyActivity(user_id=self.user.id, activity_type="question_asked", title="yesterday",
                          occurred_at=datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)),
        ])
        await self.db.flush()
        view = await dashboard_service.build_dashboard(self.db, now=NOW, user_id=self.user.id)
        self.assertEqual(view["stats"]["streak_days"], 2)
        review = next(row for row in view["today_tasks"] if row["type"] == "review")
        mistake = next(row for row in view["today_tasks"] if row["type"] == "mistake")
        self.assertEqual(review["id"], "derived:2026-09-15:review:global")
        self.assertEqual(review["status"], "completed")
        self.assertEqual(mistake["status"], "completed")

    async def test_workspace_ranking_is_explainable_stable_and_excludes_archived(self):
        strong = await create_workspace(self.db, self.user, name="Strong", slug="rank-strong")
        archived = await create_workspace(
            self.db, self.user, name="Archived", slug="rank-archived", archived=True
        )
        weak_point = KnowledgePoint(workspace_id=self.workspace.id, title="Weak", mastery=.2)
        archived_point = KnowledgePoint(workspace_id=archived.id, title="Hidden", mastery=0)
        self.db.add_all([weak_point, archived_point])
        await self.db.flush()
        self.db.add_all([
            WeakKnowledgeState(
                workspace_id=self.workspace.id, knowledge_point_id=weak_point.id,
                weakness_score=90,
            ),
            WeakKnowledgeState(
                workspace_id=archived.id, knowledge_point_id=archived_point.id,
                weakness_score=100,
            ),
            Document(workspace_id=strong.id, filename="new.pdf", file_path="new.pdf", file_type=".pdf"),
        ])
        await self.db.flush()

        rows = await dashboard_service.rank_workspaces(
            self.db, now=NOW, limit=10, user_id=self.user.id
        )

        self.assertNotIn(archived.id, [row["workspace_id"] for row in rows])
        weak = next(row for row in rows if row["workspace_id"] == self.workspace.id)
        self.assertGreater(weak["components"]["weakness"], 0)
        self.assertTrue(weak["reason"])
        self.assertEqual(rows, await dashboard_service.rank_workspaces(
            self.db, now=NOW, limit=10, user_id=self.user.id
        ))


if __name__ == "__main__":
    unittest.main()
