"""HTTP contracts for the tutor profile and memory endpoints."""

import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db
from app.api.routes.learning import get_memory_service, get_profile_service
from app.main import app
from app.models.base import Base
from app.models.learning import LearningMemory
from app.services.learner_profile import LearnerProfileSnapshot
from tests.support import create_user, create_workspace


class FakeMemory:
    def __init__(self, memory_id: str = "mem-1"):
        self.id = memory_id
        self.kind = "manual"
        self.title = "闭包要点"
        self.content = "闭包捕获变量绑定"
        self.workspace_id = None
        self.source_refs = {"origin": "manual"}
        self.importance = 0.9
        self.is_active = True
        self.embedding_state = "ready"
        self.use_count = 0
        self.last_used_at = None
        self.created_at = None
        self.updated_at = None


class FakeMemoryService:
    def __init__(self):
        self.items: dict[str, FakeMemory] = {}

    async def remember(self, **kwargs):
        memory = FakeMemory(f"mem-{len(self.items) + 1}")
        memory.kind = kwargs["kind"]
        memory.title = kwargs["title"]
        memory.content = kwargs["content"]
        memory.workspace_id = kwargs.get("workspace_id")
        self.items[memory.id] = memory
        return memory

    async def list_memories(self, **kwargs):
        items = list(self.items.values())
        return items, len(items)

    async def update_memory(self, memory_id, **changes):
        memory = self.items.get(memory_id)
        if memory is None:
            return None
        if changes.get("is_active") is not None:
            memory.is_active = changes["is_active"]
        return memory

    async def delete_memory(self, memory_id):
        return self.items.pop(memory_id, None) is not None


class TutorAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(self.db, self.user, slug="tutor-api")
        self.memory_service = FakeMemoryService()

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_memory_service] = lambda: self.memory_service

        async def profile_service():
            class StubProfileService:
                async def build(self, **kwargs):
                    return LearnerProfileSnapshot(
                        display_name="学习者",
                        preferred_mode="simple",
                        goal_summary="日目标 30 分钟",
                    )

            return StubProfileService()

        app.dependency_overrides[get_profile_service] = profile_service
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def test_manual_memory_crud_round_trip(self):
        created = await self.client.post("/api/learning/memories", json={
            "kind": "manual", "title": "闭包要点", "content": "闭包捕获变量绑定",
        })
        self.assertEqual(created.status_code, 201, created.text)
        memory_id = created.json()["id"]

        listed = await self.client.get("/api/learning/memories")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)

        patched = await self.client.patch(
            f"/api/learning/memories/{memory_id}", json={"is_active": False}
        )
        self.assertEqual(patched.status_code, 200)
        self.assertFalse(patched.json()["is_active"])

        deleted = await self.client.delete(f"/api/learning/memories/{memory_id}")
        self.assertEqual(deleted.status_code, 204)
        # Deleting twice is not idempotent by design: the second call reports the missing record.
        self.assertEqual(
            (await self.client.delete(f"/api/learning/memories/{memory_id}")).status_code, 404
        )

    async def test_memory_payload_is_validated(self):
        response = await self.client.post("/api/learning/memories", json={"title": "缺内容"})

        self.assertEqual(response.status_code, 422)

    async def test_learner_profile_endpoint_returns_snapshot_shape(self):
        response = await self.client.get("/api/learning/learner-profile")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["display_name"], "学习者")
        self.assertEqual(payload["weak_points"], [])
        self.assertIn("generated_at", payload)

    async def test_export_includes_learning_memories(self):
        # The memory endpoints are exercised through a fake service in this suite, so the export
        # test seeds the row directly to isolate the export wiring from the service under test.
        self.db.add(LearningMemory(
            user_id=self.user.id,
            kind="manual",
            title="导出检查",
            content="这条记忆必须出现在导出里",
            source_refs={"origin": "manual"},
        ))
        await self.db.flush()

        response = await self.client.get("/api/learning/export")

        self.assertEqual(response.status_code, 200)
        exported = response.json()["learning_memories"]
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["title"], "导出检查")


if __name__ == "__main__":
    unittest.main()
