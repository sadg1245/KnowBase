"""Long-term memory generation, dedup, recall, and lifecycle."""

import math
import unittest
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.migrations import ensure_memory_index
from app.models.base import Base
from app.services import learning_memory
from tests.support import create_user


def _vector(token: float) -> list[float]:
    return [math.cos(token), math.sin(token)]


@dataclass
class FakeVectorStore:
    vectors: dict[str, list[float]] = field(default_factory=dict)
    metadata: dict[str, dict] = field(default_factory=dict)
    fail_on_query: bool = False

    def upsert(self, *, memory_id, embedding, metadata, document):
        self.vectors[memory_id] = list(embedding)
        self.metadata[memory_id] = dict(metadata)

    def query(self, *, embedding, top_k, where):
        if self.fail_on_query:
            raise RuntimeError("vector store offline")
        scored = []
        for memory_id, vector in self.vectors.items():
            meta = self.metadata.get(memory_id, {})
            if where.get("is_active") is not None and meta.get("is_active") != where["is_active"]:
                continue
            dot = sum(a * b for a, b in zip(embedding, vector))
            scored.append((memory_id, max(0.0, dot), meta))
        scored.sort(key=lambda item: -item[1])
        return scored[:top_k]

    def delete(self, *, memory_id):
        self.vectors.pop(memory_id, None)
        self.metadata.pop(memory_id, None)


class LearningMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await ensure_memory_index(connection)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.store = FakeVectorStore()
        self.vectors: dict[str, float] = {}

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def _service(self, *, fail_query=False):
        self.store.fail_on_query = fail_query

        def embed(texts):
            return [self._embedding_for(text) for text in texts]

        return learning_memory.LearningMemoryService(
            self.db, self.user.id, vector_store=self.store, embed=embed
        )

    def _embedding_for(self, text: str) -> list[float]:
        return _vector(self.vectors.get(text, float(len(text) % 7)))

    async def test_remember_without_source_refs_is_rejected(self):
        service = self._service()

        created = await service.remember(
            kind="session_summary", title="空来源", content="内容", source_refs={}
        )

        self.assertIsNone(created)

    async def test_remember_stores_embedding_and_keyword_document(self):
        service = self._service()

        memory = await service.remember(
            kind="manual",
            title="闭包要点",
            content="闭包捕获的是变量绑定而不是变量值",
            source_refs={"origin": "manual"},
        )

        self.assertIsNotNone(memory)
        self.assertEqual(memory.embedding_state, "ready")
        self.assertTrue(memory.tokenized_content.strip())
        self.assertIn(memory.id, self.store.vectors)
        self.assertTrue(self.store.metadata[memory.id]["is_active"])

    async def test_near_duplicate_updates_the_existing_memory(self):
        service = self._service()
        self.vectors["闭包要点\n闭包捕获变量绑定"] = 1.0
        first = await service.remember(
            kind="manual",
            title="闭包要点",
            content="闭包捕获变量绑定",
            source_refs={"origin": "manual"},
        )
        self.vectors["闭包要点\n闭包捕获变量绑定而不是值"] = 1.0
        second = await service.remember(
            kind="manual",
            title="闭包要点",
            content="闭包捕获变量绑定而不是值",
            source_refs={"origin": "manual"},
        )

        self.assertEqual(first.id, second.id)
        total = (await service.list_memories())[1]
        self.assertEqual(total, 1)

    async def test_recall_merges_semantic_and_keyword_hits(self):
        service = self._service()
        semantic_memory = await service.remember(
            kind="manual",
            title="RAG 重排",
            content="重排阶段使用确定性融合分数",
            source_refs={"origin": "manual"},
        )
        await self.db.commit()
        self.vectors["RAG 重排\n重排阶段使用确定性融合分数"] = 1.0
        self.vectors["重排阶段使用确定性融合分数"] = 1.0

        result = await service.recall(question="重排阶段使用确定性融合分数", workspace_id=None)

        self.assertIsNone(result.degraded_reason)
        self.assertEqual([hit.memory.id for hit in result.hits][0], semantic_memory.id)
        self.assertGreater(result.hits[0].score, 0)

    async def test_recall_degrades_to_keyword_only_when_vectors_fail(self):
        service = self._service()
        await service.remember(
            kind="manual",
            title="作用域链",
            content="作用域链决定了变量的查找顺序",
            source_refs={"origin": "manual"},
        )
        await self.db.commit()
        failing = self._service(fail_query=True)

        result = await failing.recall(question="作用域链决定变量查找顺序", workspace_id=None)

        self.assertEqual(result.degraded_reason, "vector_unavailable")
        self.assertEqual(len(result.hits), 1)

    async def test_inactive_memories_are_not_recalled(self):
        service = self._service()
        memory = await service.remember(
            kind="manual",
            title="临时偏好",
            content="先给例子再给定义",
            source_refs={"origin": "manual"},
        )
        await self.db.commit()
        await service.update_memory(memory.id, is_active=False)
        await self.db.commit()

        result = await service.recall(question="先给例子再给定义", workspace_id=None)

        self.assertEqual(result.hits, [])

    async def test_delete_removes_the_vector_entry(self):
        service = self._service()
        memory = await service.remember(
            kind="manual",
            title="待删除",
            content="这条记忆会被删除",
            source_refs={"origin": "manual"},
        )
        self.assertIn(memory.id, self.store.vectors)

        deleted = await service.delete_memory(memory.id)

        self.assertTrue(deleted)
        self.assertNotIn(memory.id, self.store.vectors)
        self.assertEqual(await service.list_memories(), ([], 0))

    async def test_record_usage_increments_counters(self):
        service = self._service()
        memory = await service.remember(
            kind="manual",
            title="计数",
            content="被使用次数应该增加",
            source_refs={"origin": "manual"},
        )

        await service.record_usage([memory])

        self.assertEqual(memory.use_count, 1)
        self.assertIsNotNone(memory.last_used_at)

    def test_memory_block_declares_it_is_not_evidence(self):
        class Row:
            id = "mem-1"
            kind = "mistake_pattern"
            title = "闭包"
            content = "循环变量绑定错误"

        block = learning_memory.format_memory_block(
            [learning_memory.MemoryHit(Row(), 0.9, 0.9, 0.5)]
        )

        self.assertIn("不是资料证据", block)
        self.assertNotIn("[资料", block)


if __name__ == "__main__":
    unittest.main()
