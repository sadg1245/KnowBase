"""阶段 5：检索调试端点默认关闭，开启后给出逐条分项打分。"""

import unittest
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.api.routes import search as search_routes
from app.config import settings as app_settings
from app.main import app
from app.models.base import Base
from tests.support import create_user, create_workspace


async def _fake_recall(**_kwargs):
    """模块级假召回：不能用类方法，否则会以 self 作为位置参数被调用。"""
    return [
        {
            "chunk_id": "doc_chunk_1",
            "content": "条件概率的定义",
            "source_file": "notes.md",
            "page_num": 3,
            "heading": "1.1 定义",
            "document_id": "doc",
            "workspace_id": "ws",
            "score": 0.82,
            "vector_kinds": ["content"],
            "content_type": "definition",
            "difficulty": 2,
        }
    ]


class RetrievalDebugEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(self.db, self.user, name="调试", slug="debug-retrieval")
        await self.db.commit()

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

    async def test_endpoint_is_hidden_by_default(self):
        response = await self.client.post("/api/debug/retrieval", json={"query": "条件概率"})
        self.assertEqual(response.status_code, 404)

    async def test_enabled_endpoint_returns_component_scores(self):
        with patch.object(search_routes, "_vector_recall", _fake_recall), \
                patch.object(app_settings, "RAG_DEBUG_ENDPOINT_ENABLED", True):
            response = await self.client.post(
                "/api/debug/retrieval",
                json={"query": "条件概率是什么", "workspace_id": self.workspace.id, "top_k": 3},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["query"], "条件概率是什么")
        self.assertIn("evidence_status", body)
        self.assertEqual(body["scope"]["workspace_ids"], [self.workspace.id])
        self.assertNotEqual(body["hits"], [], body)
        hit = body["hits"][0]
        for key in (
            "chunk_id", "vector_rank", "keyword_rank", "vector_score", "keyword_score",
            "fusion_score", "rerank_score", "profile_bonus", "vector_kinds",
            "content_type", "difficulty", "final_rank",
        ):
            self.assertIn(key, hit)
        self.assertEqual(hit["content_type"], "definition")
        self.assertLessEqual(hit["profile_bonus"], 0.1)
        self.assertEqual(hit["vector_kinds"], ["content"])

    async def test_missing_query_is_rejected_when_enabled(self):
        with patch.object(app_settings, "RAG_DEBUG_ENDPOINT_ENABLED", True):
            response = await self.client.post("/api/debug/retrieval", json={"query": "  "})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
