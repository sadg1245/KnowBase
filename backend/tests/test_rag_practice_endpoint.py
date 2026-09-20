"""§16.2 / §22.1：练习检索端点只返回资料原题，答案与解答不进入结果集。"""

import unittest

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.main import app
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint
from app.models.rag import KnowledgeUnit
from tests.support import create_user, create_workspace


def chunk(chunk_id: str, workspace_id: str, document_id: str, *, content_type: str,
          chunk_index: int, chunk_level: str = "child", unit_id: str | None = None,
          difficulty: int | None = None) -> DocumentChunk:
    return DocumentChunk(
        id=chunk_id,
        workspace_id=workspace_id,
        document_id=document_id,
        source_file="exam.pdf",
        chunk_index=chunk_index,
        chunk_level=chunk_level,
        content=f"{chunk_id} 的正文",
        tokenized_content=chunk_id,
        content_type=content_type,
        unit_id=unit_id,
        difficulty=difficulty,
    )


class PracticeQuestionEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(
            self.db, self.user, name="练习", slug="rag-practice"
        )
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="exam.pdf",
            file_path="x",
            file_type="pdf",
            status="ready",
        )
        self.db.add(self.document)
        await self.db.flush()
        self.unit = KnowledgeUnit(
            id="unit-1",
            document_id=self.document.id,
            workspace_id=self.workspace.id,
            unit_type="question",
            title="题 1",
            content="题干",
        )
        self.db.add(self.unit)
        self.point = KnowledgePoint(
            workspace_id=self.workspace.id,
            document_id=self.document.id,
            title="条件概率",
            unit_id="unit-1",
        )
        self.db.add(self.point)
        self.db.add_all([
            chunk("q1", self.workspace.id, self.document.id, content_type="question",
                  chunk_index=0, unit_id="unit-1", difficulty=2),
            chunk("q2", self.workspace.id, self.document.id, content_type="question",
                  chunk_index=1, unit_id=None, difficulty=4),
            chunk("s1", self.workspace.id, self.document.id, content_type="solution",
                  chunk_index=2, unit_id="unit-1"),
            chunk("a1", self.workspace.id, self.document.id, content_type="answer",
                  chunk_index=3, unit_id="unit-1"),
            chunk("p1", self.workspace.id, self.document.id, content_type="question",
                  chunk_index=4, chunk_level="parent", unit_id="unit-1"),
        ])
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

    async def practice(self, **payload):
        body = {"workspace_id": self.workspace.id}
        body.update(payload)
        return await self.client.post("/api/rag/practice", json=body)

    async def test_returns_only_child_question_chunks(self):
        response = await self.practice()

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([item["chunk_id"] for item in body["items"]], ["q1", "q2"])
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["excluded_content_types"], ["solution", "answer"])
        self.assertIn("practice_mode_excludes_answers", body["reasons"])
        question = body["items"][0]
        self.assertEqual(question["content_type"], "question")
        self.assertEqual(question["difficulty"], 2)
        self.assertEqual(question["unit_id"], "unit-1")
        self.assertEqual(question["source_file"], "exam.pdf")
        self.assertNotIn("tokenized_content", response.text)

    async def test_knowledge_point_filter_uses_its_unit(self):
        response = await self.practice(knowledge_point_ids=[self.point.id])

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item["chunk_id"] for item in response.json()["items"]], ["q1"])

    async def test_unknown_knowledge_point_fails_closed(self):
        response = await self.practice(knowledge_point_ids=["missing-point"])

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["reasons"], ["knowledge_points_have_no_question_units"])

    async def test_difficulty_and_limit_are_applied_without_losing_the_total(self):
        filtered = await self.practice(difficulty_min=3)
        self.assertEqual([item["chunk_id"] for item in filtered.json()["items"]], ["q2"])

        limited = await self.practice(limit=1)
        body = limited.json()
        self.assertEqual([item["chunk_id"] for item in body["items"]], ["q1"])
        self.assertEqual(body["total"], 2)

    async def test_foreign_or_unknown_workspace_is_hidden(self):
        other = await create_workspace(self.db, await create_user(self.db), name="别人的")
        await self.db.commit()

        self.assertEqual((await self.practice(workspace_id=other.id)).status_code, 404)
        self.assertEqual((await self.practice(workspace_id="missing")).status_code, 404)

    async def test_limit_bounds_are_validated(self):
        self.assertEqual((await self.practice(limit=0)).status_code, 422)
        self.assertEqual((await self.practice(limit=999)).status_code, 422)


if __name__ == "__main__":
    unittest.main()
