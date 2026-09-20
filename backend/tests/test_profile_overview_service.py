"""Deterministic learner profile: thresholds, evidence, emptiness, and isolation."""

import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.assessment import MistakeRecord, QuizAttempt, WeakKnowledgeState
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity
from app.schemas.insights import WorkspaceGoalUpdate
from app.services import goal_service
from app.services.profile_overview import LearnerProfileOverviewService, mastery_band
from tests.support import create_preferences, create_user, create_workspace

NOW = datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc)  # 12:00 Asia/Shanghai


class MasteryBandTests(unittest.TestCase):
    def test_thresholds_match_the_design_document(self):
        cases = [
            (0.0, "not_mastered", "未掌握"),
            (0.29, "not_mastered", "未掌握"),
            (0.30, "weak", "薄弱"),
            (0.49, "weak", "薄弱"),
            (0.50, "learning", "学习中"),
            (0.69, "learning", "学习中"),
            (0.70, "mastered", "已掌握"),
            (0.84, "mastered", "已掌握"),
            (0.85, "proficient", "熟练"),
            (1.0, "proficient", "熟练"),
        ]

        for score, status, label in cases:
            with self.subTest(score=score):
                self.assertEqual(mastery_band(score), (status, label))


class ProfileOverviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, display_name="小光")
        await create_preferences(
            self.db, self.user, preferred_mode="simple", timezone_name="Asia/Shanghai"
        )
        self.workspace = await create_workspace(
            self.db, self.user, name="AI Agent 开发", slug="profile-agent"
        )

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _point(self, title: str, mastery: float, *, importance: int = 3) -> KnowledgePoint:
        point = KnowledgePoint(
            workspace_id=self.workspace.id, title=title, mastery=mastery, importance=importance
        )
        self.db.add(point)
        await self.db.flush()
        return point

    async def _activity(self, *, title: str, minutes: int, hours_ago: float, **extra) -> StudyActivity:
        row = StudyActivity(
            user_id=self.user.id,
            workspace_id=self.workspace.id,
            activity_type=extra.pop("activity_type", "document_read"),
            title=title,
            duration_seconds=minutes * 60,
            payload=extra.pop("payload", None),
            occurred_at=NOW - timedelta(hours=hours_ago),
            **extra,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def _build(self, **kwargs):
        return await LearnerProfileOverviewService(self.db, self.user.id).build(
            now=NOW, **kwargs
        )

    async def test_profile_without_learning_evidence_waits_instead_of_showing_zero(self):
        await self._point("RAG", 0.0)
        await self._point("LangGraph", 0.0)

        profile = await self._build()

        self.assertTrue(profile.is_empty)
        self.assertEqual(profile.mastery_overview, [])
        self.assertEqual(profile.weak_points, [])
        self.assertEqual(profile.current_focus, [])
        self.assertEqual(profile.insight.text, "")
        self.assertEqual(profile.knowledge_point_count, 2)
        self.assertIn("开始一次学习", profile.empty_hint or "")

    async def test_mastery_carries_status_trend_and_confidence(self):
        point = await self._point("RAG", 0.76)
        await self._activity(title="阅读 RAG 章节", minutes=20, hours_ago=24)
        await self._activity(
            title="掌握了知识点：RAG",
            minutes=0,
            hours_ago=120,
            activity_type="mastery_changed",
            payload={
                "knowledge_point_id": point.id,
                "before_mastery": 0.63,
                "after_mastery": 0.76,
            },
        )
        stale = await self._point("LangGraph", 0.41)
        await self._activity(
            title="掌握了知识点：LangGraph",
            minutes=0,
            hours_ago=24 * 60,
            activity_type="mastery_changed",
            payload={
                "knowledge_point_id": stale.id,
                "before_mastery": 0.43,
                "after_mastery": 0.41,
            },
        )

        profile = await self._build()

        area = profile.mastery_overview[0]
        self.assertEqual(area.name, "AI Agent 开发")
        self.assertEqual(area.score, 0.585)
        self.assertEqual(area.status, "learning")
        self.assertEqual(area.knowledge_point_count, 2)
        self.assertEqual(area.trend, 0.065)
        self.assertEqual(area.confidence, 0.9)
        # 60 天前的证据只降低置信度，不直接扣掌握度。
        self.assertEqual(area.confidence_note, None)
        children = {child.name: child for child in area.children}
        self.assertEqual(children["RAG"].score, 0.76)
        self.assertEqual(children["RAG"].status, "mastered")
        self.assertEqual(children["RAG"].trend, 0.13)
        self.assertEqual(children["LangGraph"].trend, 0.0)
        # 长时间没有新证据时只降低置信度，并在条目上说明原因。
        self.assertEqual(children["LangGraph"].confidence, 0.35)
        self.assertIn("60 天没有有效复习或练习", children["LangGraph"].confidence_note or "")

    async def test_weak_points_are_ranked_and_explain_why(self):
        weak = await self._point("LangGraph State", 0.38)
        await self._point("RAG", 0.76)
        question = QuizQuestion(
            workspace_id=self.workspace.id,
            knowledge_point_id=weak.id,
            question_type="short",
            difficulty_level="medium",
            prompt="解释 State 的生命周期",
            answer="State 在节点间传递",
        )
        card = Flashcard(
            workspace_id=self.workspace.id, knowledge_point_id=weak.id, front="F", back="B"
        )
        self.db.add_all([question, card])
        await self.db.flush()
        for index, correct in enumerate((True, False, False, True, False)):
            self.db.add(
                QuizAttempt(
                    quiz_set_id="set",
                    quiz_run_id="run",
                    question_id=question.id,
                    attempt_number=index + 1,
                    is_correct=correct,
                    evaluation_status="graded",
                    duration_seconds=90,
                    submitted_at=NOW - timedelta(hours=index + 1),
                )
            )
        self.db.add_all(
            [
                ReviewLog(card_id=card.id, rating=1, reviewed_at=NOW - timedelta(days=2)),
                ReviewLog(card_id=card.id, rating=2, reviewed_at=NOW - timedelta(days=1)),
                MistakeRecord(
                    question_id=question.id,
                    knowledge_point_id=weak.id,
                    workspace_id=self.workspace.id,
                    wrong_count=2,
                    error_reason="State 与普通局部变量混淆",
                    last_wrong_at=NOW - timedelta(hours=3),
                ),
            ]
        )
        self.db.add(
            WeakKnowledgeState(
                knowledge_point_id=weak.id,
                workspace_id=self.workspace.id,
                weakness_score=81,
                accuracy_component=60,
                repeat_error_component=50,
                review_feedback_component=100,
                response_time_component=0,
                recency_component=20,
                evidence={
                    "graded_attempt_count": 5,
                    "unresolved_mistake_count": 2,
                    "review_count": 2,
                    "last_relevant_activity_at": (NOW - timedelta(hours=1)).isoformat(),
                },
                recommended_actions=[
                    {"type": "review", "label": "加入近期复习", "path": "/review"},
                    {
                        "type": "targeted_practice",
                        "label": "针对性练习",
                        "path": f"/practice?workspace_id={self.workspace.id}&knowledge_point_id={weak.id}&mode=targeted",
                    },
                ],
            )
        )
        await self.db.flush()

        profile = await self._build()

        self.assertEqual(len(profile.weak_points), 1)
        point = profile.weak_points[0]
        self.assertEqual(point.name, "LangGraph State")
        self.assertEqual(point.area, "AI Agent 开发")
        self.assertEqual(point.mastery, 0.38)
        self.assertEqual(point.weakness_score, 0.81)
        self.assertEqual(point.weakness_band, "priority")
        self.assertIn("最近 5 题答对 2 题", point.reasons)
        self.assertIn("最近 2 次复习都没记住", point.reasons)
        self.assertIn("仍有 1 道错题未掌握", point.reasons)
        self.assertEqual([action.type for action in point.actions], ["review", "practice", "explain"])
        self.assertEqual(point.actions[0].path, "/review")
        self.assertEqual(point.evidence.attempt_accuracy, 0.4)
        self.assertEqual(len(point.evidence.recent_attempts), 5)
        # 错题道数与重复错误次数分开统计，避免把「错 3 次」说成「3 道题」。
        self.assertEqual(point.evidence.mistake_count, 1)
        self.assertEqual(point.evidence.repeat_error_count, 2)
        self.assertEqual(point.evidence.recent_reviews[0].label, "模糊")
        self.assertEqual(point.evidence.state_note, "掌握明显不足，建议优先处理")
        self.assertEqual(point.evidence.components["accuracy"], 60.0)
        # 练习与讲解动作必须可点，路径来自既有确定性建议。
        self.assertTrue(point.actions[1].path and "knowledge_point_id" in point.actions[1].path)
        self.assertTrue(point.actions[2].path and point.actions[2].path.startswith("/learn?"))

    async def test_common_errors_recent_learning_and_goals_use_real_rows(self):
        strong = await self._point("Prompt Engineering", 0.9)
        middle = await self._point("RAG", 0.6)
        weak = await self._point("LangGraph", 0.2)
        question = QuizQuestion(
            workspace_id=self.workspace.id,
            knowledge_point_id=weak.id,
            question_type="short",
            prompt="Q",
            answer="A",
        )
        self.db.add(question)
        await self.db.flush()
        self.db.add(
            MistakeRecord(
                question_id=question.id,
                knowledge_point_id=weak.id,
                workspace_id=self.workspace.id,
                wrong_count=2,
                error_reason="Conditional Edge 返回值理解错误",
                last_wrong_at=NOW - timedelta(hours=2),
            )
        )
        await self._activity(title="今天学习 RAG", minutes=32, hours_ago=1)
        await self._activity(title="昨天学习 Python", minutes=45, hours_ago=20)
        await goal_service.update_workspace_goal(
            self.db,
            self.workspace.id,
            WorkspaceGoalUpdate(target_mastery=80, target_date=date(2026, 12, 31)),
            now=NOW,
            user_id=self.user.id,
        )

        profile = await self._build()

        self.assertFalse(profile.is_empty)
        self.assertEqual(profile.recent_learning[0].label, "今天")
        self.assertEqual(profile.recent_learning[0].minutes, 32.0)
        self.assertEqual(profile.recent_learning[0].areas[0].name, "AI Agent 开发")
        self.assertEqual(profile.recent_learning[1].label, "昨天")
        self.assertEqual(profile.recent_learning[1].minutes, 45.0)
        self.assertEqual(profile.common_errors[0].pattern, "Conditional Edge 返回值理解错误")
        self.assertEqual(profile.common_errors[0].count, 2)
        self.assertEqual(profile.common_errors[0].knowledge_point_title, "LangGraph")
        goal = profile.goals[0]
        self.assertEqual(goal.title, "掌握「AI Agent 开发」")
        self.assertEqual(goal.completed, ["Prompt Engineering"])
        self.assertEqual(goal.learning, ["RAG"])
        self.assertEqual(goal.pending, ["LangGraph"])
        self.assertAlmostEqual(goal.actual, 56.67, places=1)

    async def test_focus_points_follow_recent_evidence_and_profile_is_stable(self):
        point = await self._point("RAG", 0.7)
        await self._activity(title="阅读 RAG", minutes=25, hours_ago=2)
        await self._activity(
            title="提问",
            minutes=5,
            hours_ago=3,
            activity_type="question_asked",
            payload={"knowledge_point_id": point.id, "mode": "deep"},
        )

        first = await self._build()
        second = await self._build()

        self.assertEqual(first.current_focus[0].name, "AI Agent 开发")
        self.assertEqual(first.current_focus[0].recent_minutes, 30.0)
        self.assertEqual(first.focus_points[0].name, "RAG")
        self.assertEqual(first.observations.deep_mode_ratio, 1.0)
        self.assertTrue(
            any("更常选择深入学习" in note for note in first.observations.notes)
        )
        self.assertEqual(first.model_dump(), second.model_dump())

    async def test_other_users_learning_never_leaks_into_the_profile(self):
        await self._point("RAG", 0.7)
        await self._activity(title="阅读 RAG", minutes=25, hours_ago=2)
        other = await create_user(self.db, username="other-learner", display_name="另一个人")
        other_workspace = await create_workspace(self.db, other, name="他人的知识库", slug="other-ws")
        other_point = KnowledgePoint(
            workspace_id=other_workspace.id, title="他人知识点", mastery=0.2
        )
        self.db.add(other_point)
        await self.db.flush()
        self.db.add_all(
            [
                WeakKnowledgeState(
                    knowledge_point_id=other_point.id,
                    workspace_id=other_workspace.id,
                    weakness_score=95,
                ),
                StudyActivity(
                    user_id=other.id,
                    workspace_id=other_workspace.id,
                    activity_type="document_read",
                    title="他人的学习",
                    duration_seconds=600,
                    occurred_at=NOW - timedelta(hours=1),
                ),
            ]
        )
        await self.db.flush()

        profile = await self._build(weak_limit=5)

        self.assertEqual([item.name for item in profile.current_focus], ["AI Agent 开发"])
        self.assertEqual(profile.weak_points, [])
        self.assertEqual(
            [area.name for day in profile.recent_learning for area in day.areas],
            ["AI Agent 开发"],
        )


if __name__ == "__main__":
    unittest.main()
