"""HTTP contracts for the learner profile overview and AI insight."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.main import app
from app.models.assessment import MistakeRecord, QuizAttempt, QuizRun, QuizSet, WeakKnowledgeState
from app.models.base import Base
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity
from app.services import profile_insight
from tests.support import create_preferences, create_user, create_workspace

NOW = datetime.now(timezone.utc)


class ProfileAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, display_name="小光")
        await create_preferences(self.db, self.user, timezone_name="Asia/Shanghai")
        self.workspace = await create_workspace(
            self.db, self.user, name="AI Agent 开发", slug="profile-api"
        )
        self.point = KnowledgePoint(
            workspace_id=self.workspace.id, title="LangGraph State", mastery=0.38
        )
        self.db.add(self.point)
        await self.db.flush()
        quiz_set = QuizSet(workspace_id=self.workspace.id, title="State 专项", question_count=1, status="ready")
        self.db.add(quiz_set)
        await self.db.flush()
        quiz_run = QuizRun(quiz_set_id=quiz_set.id, round_number=1, status="submitted")
        self.db.add(quiz_run)
        await self.db.flush()
        question = QuizQuestion(
            workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id,
            quiz_set_id=quiz_set.id,
            question_type="short_answer",
            prompt="State 是什么？",
            answer="状态容器",
        )
        card = Flashcard(
            workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id,
            front="State",
            back="状态容器",
        )
        self.db.add_all([question, card])
        await self.db.flush()
        self.db.add_all([
            WeakKnowledgeState(
                knowledge_point_id=self.point.id,
                workspace_id=self.workspace.id,
                weakness_score=81,
                evidence={"graded_attempt_count": 5, "unresolved_mistake_count": 2},
            ),
            QuizAttempt(
                quiz_set_id=quiz_set.id,
                quiz_run_id=quiz_run.id,
                question_id=question.id,
                attempt_number=1,
                is_correct=False,
                evaluation_status="graded",
                duration_seconds=180,
                submitted_at=NOW - timedelta(hours=4),
            ),
            MistakeRecord(
                question_id=question.id,
                knowledge_point_id=self.point.id,
                workspace_id=self.workspace.id,
                wrong_count=2,
                error_reason="State 与普通局部变量混淆",
                mastery_status="unresolved",
                last_wrong_at=NOW - timedelta(hours=4),
            ),
            ReviewLog(
                card_id=card.id,
                rating=1,
                previous_mastery=0.4,
                next_mastery=0.38,
                reviewed_at=NOW - timedelta(days=1),
            ),
            StudyActivity(
                user_id=self.user.id,
                workspace_id=self.workspace.id,
                activity_type="document_read",
                title="阅读 LangGraph 章节",
                duration_seconds=1800,
                occurred_at=NOW,
            ),
        ])
        await self.db.commit()
        profile_insight.invalidate_insight_cache(self.user.id)

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def test_profile_contract_includes_facts_and_keeps_preference_fields(self):
        response = await self.client.get("/api/learning/profile")

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        for key in (
            "user_id", "display_name", "is_empty", "knowledge_point_count",
            "current_focus", "focus_points", "mastery_overview", "weak_points",
            "common_errors", "goals", "recent_learning", "observations", "insight",
            "trend_window_days", "computed_at",
        ):
            self.assertIn(key, payload)
        # 设置页、学习页与飞书提醒仍读取这些偏好字段。
        for key in (
            "id", "daily_goal_minutes", "daily_review_target", "weekly_goal_days",
            "timezone_name", "preferred_mode",
        ):
            self.assertIn(key, payload)
        self.assertFalse(payload["is_empty"])
        self.assertEqual(payload["current_focus"][0]["name"], "AI Agent 开发")
        area = payload["mastery_overview"][0]
        self.assertEqual(area["name"], "AI Agent 开发")
        self.assertEqual(area["status"], "weak")
        weak = payload["weak_points"][0]
        self.assertEqual(weak["name"], "LangGraph State")
        self.assertEqual(weak["weakness_score"], 0.81)
        self.assertEqual([action["type"] for action in weak["actions"]], ["review", "practice", "explain"])
        self.assertEqual(len(weak["evidence"]["recent_attempts"]), 1)
        self.assertEqual(weak["evidence"]["recent_reviews"][0]["label"], "忘记")
        self.assertEqual(weak["evidence"]["mistake_count"], 1)
        self.assertEqual(weak["evidence"]["repeat_error_count"], 2)
        self.assertIn("仍有 1 道错题未掌握", weak["reasons"])
        self.assertEqual(payload["insight"]["generated_by"], "rules")
        self.assertIn("LangGraph State", payload["insight"]["text"])
        # 画像不是资料证据：不得出现来源编号字段。
        self.assertNotIn("sources", payload)

    async def test_profile_scoped_to_one_workspace_and_other_users_are_hidden(self):
        other = await create_user(self.db, username="other-profile-user")
        other_workspace = await create_workspace(self.db, other, name="别人的库", slug="other-profile")
        await self.db.commit()

        hidden = await self.client.get(
            "/api/learning/profile", params={"workspace_id": other_workspace.id}
        )
        self.assertEqual(hidden.status_code, 404)

        scoped = await self.client.get(
            "/api/learning/profile", params={"workspace_id": self.workspace.id}
        )
        self.assertEqual(scoped.status_code, 200, scoped.text)
        self.assertEqual(
            [area["name"] for area in scoped.json()["mastery_overview"]], ["AI Agent 开发"]
        )

    async def test_insight_endpoint_feeds_deterministic_snapshot_and_caches_it(self):
        prompts: list[str] = []

        async def stub(settings, prompt):
            prompts.append(prompt)
            return ("LangGraph State 掌握度 38%，建议先复习再做 3 道专项练习。", "stub-model")

        with patch("app.services.profile_insight._default_completion", stub):
            first = await self.client.post("/api/learning/profile/insight")
            second = await self.client.post("/api/learning/profile/insight")

        self.assertEqual(first.status_code, 200, first.text)
        body = first.json()
        self.assertEqual(body["generated_by"], "ai")
        self.assertEqual(body["model"], "stub-model")
        self.assertFalse(body["cached"])
        self.assertIn("weak_points", body["based_on"])
        self.assertEqual(body["evidence"]["weak_points"][0]["name"], "LangGraph State")
        # 相同指标只调用一次模型。
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["cached"])
        self.assertEqual(len(prompts), 1)
        self.assertIn("只能使用给定数字", prompts[0])
        self.assertIn("LangGraph State", prompts[0])

    async def test_insight_skips_empty_profile_and_reports_provider_failure(self):
        fresh = await create_user(self.db, username="fresh-profile-user")
        await create_workspace(self.db, fresh, name="空库", slug="fresh-profile")
        await self.db.commit()
        app.dependency_overrides[get_current_user] = lambda: fresh

        empty = await self.client.post("/api/learning/profile/insight")
        self.assertEqual(empty.status_code, 409, empty.text)
        self.assertIn("暂无学习记录", empty.json()["detail"])

        app.dependency_overrides[get_current_user] = lambda: self.user

        async def broken(settings, prompt):
            raise RuntimeError("provider offline")

        with patch("app.services.profile_insight._default_completion", broken):
            failed = await self.client.post("/api/learning/profile/insight")

        self.assertEqual(failed.status_code, 503, failed.text)
        # 模型失败后，确定性画像仍然可用。
        self.assertEqual((await self.client.get("/api/learning/profile")).status_code, 200)

    async def test_dashboard_embeds_the_same_profile_facts(self):
        dashboard = await self.client.get("/api/learning/dashboard")

        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        profile = dashboard.json()["profile"]
        self.assertEqual(profile["current_focus"], "AI Agent 开发")
        self.assertFalse(profile["is_empty"])
        self.assertEqual(profile["mastery"][0]["name"], "AI Agent 开发")
        self.assertEqual(profile["mastery"][0]["children"], [])
        self.assertEqual(profile["weak_points"][0]["name"], "LangGraph State")
        # 首页抽屉直接读这份证据，因此仪表盘也要带作答与复习记录。
        self.assertEqual(len(profile["weak_points"][0]["evidence"]["recent_attempts"]), 1)
        self.assertEqual(len(profile["weak_points"][0]["evidence"]["recent_reviews"]), 1)
        self.assertIn("LangGraph State", profile["insight"]["text"])
        self.assertEqual(profile["recent_learning"][0]["label"], "今天")
        self.assertEqual(profile["recent_learning"][0]["minutes"], 30.0)


if __name__ == "__main__":
    unittest.main()
