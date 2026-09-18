"""Learner profile aggregation, relevance pruning, and cache lifetime."""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.assessment import MistakeRecord, WeakKnowledgeState
from app.models.base import Base
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.services import learner_profile
from tests.support import create_preferences, create_user, create_workspace


NOW = datetime(2026, 9, 18, 2, 0, tzinfo=timezone.utc)


class LearnerProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, display_name="小光")
        await create_preferences(self.db, self.user, preferred_mode="simple", daily_goal_minutes=30)
        self.workspace = await create_workspace(self.db, self.user, name="算法", slug="profile-algorithms")
        learner_profile.invalidate_profile_cache(self.user.id)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _weak_point(self, title: str, mastery: float, weakness: float):
        point = KnowledgePoint(workspace_id=self.workspace.id, title=title, mastery=mastery)
        self.db.add(point)
        await self.db.flush()
        self.db.add(WeakKnowledgeState(
            knowledge_point_id=point.id,
            workspace_id=self.workspace.id,
            weakness_score=weakness,
            evidence={"reason": "最近两次练习错误"},
        ))
        await self.db.flush()
        return point

    async def test_question_relevance_selects_matching_knowledge_points_first(self):
        closure = await self._weak_point("闭包", 0.45, 72)
        await self._weak_point("数据库索引", 0.30, 88)

        snapshot = await learner_profile.LearnerProfileService(self.db, self.user.id).build(
            workspace_id=self.workspace.id, question="闭包为什么会捕获循环变量"
        )

        self.assertEqual(snapshot.weak_points[0].knowledge_point_id, closure.id)
        self.assertEqual(snapshot.display_name, "小光")
        self.assertIn("30", snapshot.goal_summary)

    async def test_unrelated_question_degrades_to_recent_topics(self):
        await self._weak_point("闭包", 0.45, 72)
        self.db.add(StudyActivity(
            user_id=self.user.id,
            workspace_id=self.workspace.id,
            activity_type="question_asked",
            title="RAG 检索器重排",
            occurred_at=NOW - timedelta(hours=1),
        ))
        await self.db.flush()

        snapshot = await learner_profile.LearnerProfileService(self.db, self.user.id).build(
            workspace_id=self.workspace.id, question="完全不相关的主题"
        )

        self.assertEqual(snapshot.weak_points, [])
        self.assertIn("RAG 检索器重排", snapshot.recent_topics)

    async def test_mistake_patterns_are_aggregated_per_knowledge_point(self):
        point = await self._weak_point("闭包", 0.45, 72)
        for index in range(2):
            question = QuizQuestion(
                workspace_id=self.workspace.id, prompt=f"Q{index}", answer="A",
                knowledge_point_id=point.id,
            )
            self.db.add(question)
            await self.db.flush()
            self.db.add(MistakeRecord(
                question_id=question.id, workspace_id=self.workspace.id,
                knowledge_point_id=point.id, error_reason="循环变量绑定错误",
            ))
        await self.db.flush()

        snapshot = await learner_profile.LearnerProfileService(self.db, self.user.id).build(
            workspace_id=self.workspace.id, question="闭包"
        )

        self.assertEqual(snapshot.common_mistakes[0].count, 2)
        self.assertEqual(snapshot.common_mistakes[0].pattern, "循环变量绑定错误")

    async def test_cache_is_reused_until_invalidated(self):
        await self._weak_point("闭包", 0.45, 72)
        service = learner_profile.LearnerProfileService(self.db, self.user.id)
        first = await service.build(workspace_id=self.workspace.id, question="闭包")
        await self._weak_point("闭包2", 0.20, 90)
        cached = await learner_profile.LearnerProfileService(self.db, self.user.id).build(
            workspace_id=self.workspace.id, question="闭包"
        )
        learner_profile.invalidate_profile_cache(self.user.id, self.workspace.id)
        refreshed = await learner_profile.LearnerProfileService(self.db, self.user.id).build(
            workspace_id=self.workspace.id, question="闭包"
        )

        self.assertEqual(len(first.weak_points), 1)
        self.assertEqual(len(cached.weak_points), 1)
        self.assertEqual(len(refreshed.weak_points), 2)

    def test_profile_block_states_it_is_not_evidence(self):
        snapshot = learner_profile.LearnerProfileSnapshot(
            display_name="小光",
            preferred_mode="simple",
            goal_summary="日目标 30 分钟",
            mastery=[],
            weak_points=[
                learner_profile.ProfileWeakPoint("kp-1", "闭包", 0.45, 72, "最近两次练习错误")
            ],
            recent_topics=["FastAPI 中间件"],
            common_mistakes=[learner_profile.ProfileMistake("闭包", "循环变量绑定错误", 2)],
            next_actions=["复习闭包"],
            generated_at=NOW,
        )
        block = learner_profile.format_profile_block(snapshot)

        self.assertIn("闭包", block)
        self.assertIn("不是资料证据", block)
        self.assertNotIn("[资料", block)


if __name__ == "__main__":
    unittest.main()
