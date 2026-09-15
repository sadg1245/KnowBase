"""HTTP contracts for phase-six learning insight endpoints."""

import unittest
from datetime import date

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_db
from app.main import app
from app.models.base import Base
from app.models.document import Document
from app.models.learning import StudyActivity
from app.models.workspace import Workspace


class LearningInsightsAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.workspace = Workspace(name="API", slug="phase-six-api")
        self.db.add(self.workspace)
        await self.db.flush()
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="api.pdf",
            file_path="api.pdf",
            file_type=".pdf",
        )
        self.db.add(self.document)
        await self.db.commit()

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def test_session_routes_validate_context_and_complete_idempotently(self):
        missing = await self.client.post("/api/learning/study-sessions/start", json={
            "id": "missing-session",
            "context_type": "document",
            "context_id": "missing-document",
            "workspace_id": self.workspace.id,
        })
        self.assertEqual(missing.status_code, 404)

        started = await self.client.post("/api/learning/study-sessions/start", json={
            "id": "api-session",
            "context_type": "document",
            "context_id": self.document.id,
            "workspace_id": self.workspace.id,
        })
        self.assertEqual(started.status_code, 201, started.text)
        self.assertEqual(started.json()["status"], "active")

        beat = await self.client.post(
            "/api/learning/study-sessions/api-session/heartbeat",
            json={"sequence": 1},
        )
        self.assertEqual(beat.status_code, 200, beat.text)

        first = await self.client.post(
            "/api/learning/study-sessions/api-session/finish",
            json={"sequence": 1},
        )
        second = await self.client.post(
            "/api/learning/study-sessions/api-session/finish",
            json={"sequence": 1},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.json()["activity"]["id"], first.json()["activity"]["id"])
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 1)

        late = await self.client.post(
            "/api/learning/study-sessions/api-session/heartbeat",
            json={"sequence": 2},
        )
        self.assertEqual(late.status_code, 409)

    async def test_activity_listing_filters_type_and_pages_with_cursor(self):
        for index in range(3):
            self.db.add(StudyActivity(
                event_key=f"activity:card:{index}",
                activity_type="card_created",
                title=f"卡片 {index}",
                source_type="flashcard",
                source_id=str(index),
            ))
        self.db.add(StudyActivity(activity_type="review", title="旧复习"))
        await self.db.commit()

        first = await self.client.get(
            "/api/learning/activities",
            params={"activity_type": "card_created", "limit": 2},
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(len(first.json()["items"]), 2)
        self.assertIsNotNone(first.json()["next_cursor"])
        second = await self.client.get(
            "/api/learning/activities",
            params={
                "activity_type": "card_created",
                "limit": 2,
                "cursor": first.json()["next_cursor"],
            },
        )
        self.assertEqual(len(second.json()["items"]), 1)
        self.assertIsNone(second.json()["next_cursor"])

    async def test_goal_routes_validate_update_list_and_preserve_deleted_workspace_goal(self):
        invalid = await self.client.put("/api/learning/goals/global", json={
            "daily_minutes": 40,
            "daily_reviews": 12,
            "weekly_days": 6,
            "target_completion_date": "2026-12-31",
            "timezone_name": "Invalid/Zone",
        })
        self.assertEqual(invalid.status_code, 422, invalid.text)

        updated = await self.client.put("/api/learning/goals/global", json={
            "daily_minutes": 40,
            "daily_reviews": 12,
            "weekly_days": 6,
            "target_completion_date": "2099-12-31",
            "timezone_name": "Asia/Shanghai",
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["global"]["daily_minutes"]["target"], 40)

        workspace_goal = await self.client.put(
            f"/api/learning/goals/workspaces/{self.workspace.id}",
            json={"target_mastery": 80, "target_date": "2099-12-31"},
        )
        self.assertEqual(workspace_goal.status_code, 200, workspace_goal.text)
        self.assertEqual(workspace_goal.json()["workspace_id"], self.workspace.id)
        deleted = await self.client.delete(f"/api/learning/goals/workspaces/{self.workspace.id}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertFalse(deleted.json()["is_active"])

        listed = await self.client.get("/api/learning/goals")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["timezone_name"], "Asia/Shanghai")

    async def test_legacy_profile_goal_fields_stay_in_sync(self):
        response = await self.client.put("/api/learning/profile", json={
            "daily_goal_minutes": 35,
            "daily_review_target": 9,
            "weekly_goal_days": 4,
            "timezone_name": "Asia/Tokyo",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["weekly_goal_days"], 4)
        self.assertEqual(response.json()["timezone_name"], "Asia/Tokyo")
        goals = (await self.client.get("/api/learning/goals")).json()
        self.assertEqual(goals["global"]["daily_minutes"]["target"], 35)
        self.assertEqual(goals["global"]["daily_reviews"]["target"], 9)
        self.assertEqual(goals["global"]["weekly_days"]["target"], 4)


if __name__ == "__main__":
    unittest.main()
