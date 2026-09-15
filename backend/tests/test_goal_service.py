"""Behavior tests for measurable, timezone-aware learning goals."""

import unittest
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.learning import KnowledgePoint, LearningGoal, StudyActivity, UserProfile
from app.models.workspace import Workspace
from app.schemas.insights import GlobalGoalsUpdate, WorkspaceGoalUpdate
from app.services import goal_service


NOW = datetime(2026, 9, 15, 8, 0, tzinfo=timezone.utc)


class GoalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def request(self, **overrides):
        values = {
            "daily_minutes": 40,
            "daily_reviews": 12,
            "weekly_days": 6,
            "target_completion_date": date(2026, 12, 31),
            "timezone_name": "Asia/Shanghai",
        }
        values.update(overrides)
        return GlobalGoalsUpdate(**values)

    async def test_global_update_syncs_profile_and_records_changed_fields_once(self):
        result = await goal_service.update_global_goals(self.db, self.request(), now=NOW)
        profile = await self.db.scalar(select(UserProfile))
        self.assertEqual(
            (profile.daily_goal_minutes, profile.daily_review_target, profile.weekly_goal_days),
            (40, 12, 6),
        )
        self.assertEqual(profile.timezone_name, "Asia/Shanghai")
        self.assertEqual(result["daily_minutes"]["target"], 40)
        events = list(await self.db.scalars(
            select(StudyActivity).where(StudyActivity.activity_type == "goal_changed")
        ))
        self.assertEqual(len(events), 4)
        self.assertTrue(all("before" in row.payload and "after" in row.payload for row in events))

        await goal_service.update_global_goals(self.db, self.request(), now=NOW)
        events = list(await self.db.scalars(
            select(StudyActivity).where(StudyActivity.activity_type == "goal_changed")
        ))
        self.assertEqual(len(events), 4)

    async def test_invalid_timezone_and_past_date_do_not_mutate_profile(self):
        await goal_service.update_global_goals(self.db, self.request(), now=NOW)
        with self.assertRaises(goal_service.GoalValidationError):
            await goal_service.update_global_goals(
                self.db, self.request(timezone_name="Mars/Olympus"), now=NOW
            )
        with self.assertRaises(goal_service.GoalValidationError):
            await goal_service.update_global_goals(
                self.db, self.request(target_completion_date=date(2026, 9, 14)), now=NOW
            )
        profile = await self.db.scalar(select(UserProfile))
        self.assertEqual(profile.timezone_name, "Asia/Shanghai")
        self.assertEqual(profile.daily_goal_minutes, 40)

    async def test_workspace_progress_uses_average_mastery_and_delete_keeps_history(self):
        workspace = Workspace(name="Math", slug="math-goal")
        self.db.add(workspace)
        await self.db.flush()
        self.db.add_all([
            KnowledgePoint(workspace_id=workspace.id, title="A", mastery=.6),
            KnowledgePoint(workspace_id=workspace.id, title="B", mastery=.8),
        ])
        await self.db.flush()

        progress = await goal_service.update_workspace_goal(
            self.db,
            workspace.id,
            WorkspaceGoalUpdate(target_mastery=80, target_date=date(2026, 12, 1)),
            now=NOW,
        )
        self.assertAlmostEqual(progress["actual"], 70)
        self.assertAlmostEqual(progress["ratio"], .875)

        deleted = await goal_service.delete_workspace_goal(self.db, workspace.id, now=NOW)
        self.assertFalse(deleted["is_active"])
        row = await self.db.scalar(select(LearningGoal).where(LearningGoal.workspace_id == workspace.id))
        self.assertIsNotNone(row)
        self.assertFalse(row.is_active)

    async def test_empty_workspace_is_zero_and_overall_excludes_archived_workspaces(self):
        active = Workspace(name="Active", slug="active-goal")
        empty = Workspace(name="Empty", slug="empty-goal")
        archived = Workspace(name="Archived", slug="archived-goal", archived=True)
        self.db.add_all([active, empty, archived])
        await self.db.flush()
        self.db.add_all([
            KnowledgePoint(workspace_id=active.id, title="Active point", mastery=.8),
            KnowledgePoint(workspace_id=archived.id, title="Archived point", mastery=0),
        ])
        await self.db.flush()
        empty_progress = await goal_service.update_workspace_goal(
            self.db, empty.id,
            WorkspaceGoalUpdate(target_mastery=75, target_date=date(2026, 12, 1)),
            now=NOW,
        )
        self.assertEqual(empty_progress["actual"], 0)
        goals = await goal_service.update_global_goals(self.db, self.request(), now=NOW)
        self.assertEqual(goals["overall_mastery"]["actual"], 80)

    async def test_daily_and_weekly_progress_comes_from_activity_ledger_in_profile_timezone(self):
        await goal_service.update_global_goals(self.db, self.request(), now=NOW)
        self.db.add_all([
            StudyActivity(activity_type="document_read", title="read", duration_seconds=1200,
                          occurred_at=datetime(2026, 9, 14, 16, 30, tzinfo=timezone.utc)),
            StudyActivity(activity_type="review_completed", title="review", source_id="r1",
                          occurred_at=datetime(2026, 9, 15, 2, 0, tzinfo=timezone.utc)),
            StudyActivity(activity_type="review", title="legacy review",
                          occurred_at=datetime(2026, 9, 15, 3, 0, tzinfo=timezone.utc)),
        ])
        await self.db.flush()
        goals = await goal_service.get_goals(self.db, now=NOW)
        self.assertEqual(goals["daily_minutes"]["actual"], 20)
        self.assertEqual(goals["daily_reviews"]["actual"], 2)
        self.assertEqual(goals["weekly_days"]["actual"], 1)


if __name__ == "__main__":
    unittest.main()
