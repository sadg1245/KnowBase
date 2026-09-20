"""范围所有权收敛与 fail-closed 契约。"""

import json
import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.api.deps import get_current_user, get_db
from app.core.migrations import run_compat_migrations
from app.main import app
from app.models.base import Base
from app.models.document import Document
from app.models.learning import KnowledgePoint
from app.schemas.scope import RetrievalScope
from app.services.ownership import resolve_owned_scope
from app.services.scope_resolver import ScopeResolver
from tests.support import create_user, create_workspace


def _silent_llm():
    """Stub the outer LLM stream so scope contract tests never hit a provider."""

    async def stream(_prompt, _settings):
        if False:  # pragma: no cover - keeps this an async generator
            yield ""

    return stream


class _FakeRecall:
    hits: list = []
    degraded_reason: str | None = None


class _FakeMemoryService:
    """记忆召回会加载本地 embedding 模型；范围契约测试不需要它。"""

    def __init__(self, _db, _user_id):
        pass

    async def recall(self, *, question, workspace_id):
        return _FakeRecall()

    async def record_usage(self, memories):
        return None


async def _no_vectors(**_kwargs):
    """向量召回会加载本地 embedding 模型；范围契约测试直接跳过它。"""
    return []


class ScopeOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        self.owner = await create_user(self.db, username="owner-scope", password=None)
        self.intruder = await create_user(self.db, username="intruder-scope", password=None)
        self.owned_workspace = await create_workspace(
            self.db, self.owner, name="Owned", slug="owned-scope"
        )
        self.foreign_workspace = await create_workspace(
            self.db, self.intruder, name="Foreign", slug="foreign-scope"
        )
        self.owned_document = Document(
            workspace_id=self.owned_workspace.id, filename="owned.pdf",
            file_path="/tmp/owned.pdf", file_type="pdf", status="ready",
        )
        self.foreign_document = Document(
            workspace_id=self.foreign_workspace.id, filename="secret.pdf",
            file_path="/tmp/secret.pdf", file_type="pdf", status="ready",
        )
        self.db.add_all([self.owned_document, self.foreign_document])
        await self.db.flush()
        self.foreign_point = KnowledgePoint(
            workspace_id=self.foreign_workspace.id,
            document_id=self.foreign_document.id,
            title="他人知识点",
        )
        self.db.add(self.foreign_point)
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_resolve_owned_scope_drops_every_foreign_id(self):
        resolved = await resolve_owned_scope(
            self.db,
            self.owner,
            workspace_ids=[self.owned_workspace.id, self.foreign_workspace.id],
            document_ids=[self.owned_document.id, self.foreign_document.id],
            knowledge_point_ids=[self.foreign_point.id],
        )

        self.assertEqual(resolved.workspace_ids, [self.owned_workspace.id])
        self.assertEqual(resolved.document_ids, [self.owned_document.id])
        self.assertEqual(resolved.knowledge_point_ids, [])
        self.assertEqual(
            set(resolved.dropped_ids),
            {self.foreign_workspace.id, self.foreign_document.id, self.foreign_point.id},
        )

    async def test_resolver_reports_dropped_ids_and_stays_inside_ownership(self):
        resolver = ScopeResolver(
            self.db, user=self.owner, owned_workspaces=[self.owned_workspace.id]
        )

        resolved = await resolver.resolve(
            query="越权查询",
            scope=RetrievalScope(
                mode="global",
                workspace_ids=[self.foreign_workspace.id],
                document_ids=[self.foreign_document.id],
            ),
        )

        self.assertEqual(resolved.hard_workspace_ids, [self.owned_workspace.id])
        self.assertIn(self.foreign_workspace.id, resolved.dropped_ids)
        self.assertIn(self.foreign_document.id, resolved.dropped_ids)

    async def test_user_without_workspaces_resolves_to_empty_scope(self):
        lonely = await create_user(self.db, username="lonely-scope", password=None)
        resolver = ScopeResolver(self.db, user=lonely, owned_workspaces=[])

        resolved = await resolver.resolve(
            query="没有知识库", scope=RetrievalScope(mode="smart")
        )

        self.assertEqual(resolved.hard_workspace_ids, [])
        self.assertFalse(resolved.expansion_enabled)


class ChatScopeContractTests(unittest.IsolatedAsyncioTestCase):
    """`/api/chat` 不再强制要求工作空间；范围信息通过 SSE 首帧下发。"""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await run_compat_migrations(connection)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, username="chat-scope", password=None)
        self.workspace = await create_workspace(
            self.db, self.user, name="AI", slug="chat-scope-ws"
        )

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

    async def _first_events(self, payload: dict) -> tuple[int, list[dict]]:
        events: list[dict] = []
        with (
            patch("app.api.routes.search._call_llm_streaming", _silent_llm()),
            patch("app.api.routes.search.LearningMemoryService", _FakeMemoryService),
            patch("app.api.routes.search._vector_recall", _no_vectors),
        ):
            async with self.client.stream("POST", "/api/chat", json=payload) as response:
                status = response.status_code
                if status != 200:
                    return status, events
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    events.append(json.loads(line[5:].strip()))
                    if "scope" in events[-1]:
                        break
        return status, events

    async def test_chat_accepts_request_without_workspace(self):
        status, events = await self._first_events({
            "question": "什么是向量检索",
            "scope_mode": "global",
        })

        self.assertEqual(status, 200)
        scope_event = next((item["scope"] for item in events if "scope" in item), None)
        self.assertIsNotNone(scope_event)
        self.assertEqual(scope_event["mode"], "global")
        self.assertEqual(scope_event["workspace_ids"], [self.workspace.id])

    async def test_chat_rejects_foreign_workspace_before_streaming(self):
        intruder = await create_user(self.db, username="chat-intruder", password=None)
        foreign = await create_workspace(self.db, intruder, name="Foreign", slug="chat-foreign")

        response = await self.client.post("/api/chat", json={
            "question": "越权尝试",
            "workspace_id": foreign.id,
        })

        self.assertEqual(response.status_code, 404)

    async def test_scope_endpoints_round_trip_and_drop_foreign_ids(self):
        created = await self.client.post("/api/chat/sessions", json={
            "scope_mode": "smart",
            "scope_config": {"workspace_ids": [self.workspace.id]},
        })
        self.assertEqual(created.status_code, 201, created.text)
        session_id = created.json()["id"]
        self.assertEqual(created.json()["scope"]["mode"], "smart")

        intruder = await create_user(self.db, username="scope-foreign", password=None)
        foreign = await create_workspace(self.db, intruder, name="Foreign", slug="scope-foreign-ws")
        patched = await self.client.patch(f"/api/chat/sessions/{session_id}/scope", json={
            "mode": "strict",
            "workspace_ids": [self.workspace.id, foreign.id],
            "document_ids": [],
        })
        self.assertEqual(patched.status_code, 200, patched.text)
        body = patched.json()
        self.assertEqual(body["scope"]["mode"], "strict")
        self.assertEqual(body["scope"]["workspace_ids"], [self.workspace.id])
        self.assertEqual(body["dropped_ids"], [foreign.id])

        fetched = await self.client.get(f"/api/chat/sessions/{session_id}/scope")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["mode"], "strict")


if __name__ == "__main__":
    unittest.main()
