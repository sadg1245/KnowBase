"""阶段 4 编排：练习模式过滤、父块扩展与引用编号、降级留痕。"""

import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.rag.retrieval.orchestrator import prepare_retrieval_context
from app.rag.retrieval.reranker import Reranker


class _Candidate:
    def __init__(self, chunk_id: str, content: str, *, content_type: str | None = None,
                 score: float = 0.5, source_file: str = "notes.md"):
        self.chunk_id = chunk_id
        self.content = content
        self.content_type = content_type
        self.rerank_score = score
        self.source_file = source_file
        self.page_num = None
        self.heading = None
        self.document_id = "doc"


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _seed_parent(self, parent_id: str, parent_content: str, children: list[tuple[str, str]]):
        self.db.add(DocumentChunk(
            id=parent_id, workspace_id="ws", document_id="doc", source_file="notes.md",
            chunk_index=0, content=parent_content, tokenized_content="",
            chunk_level="parent", content_type="note",
        ))
        for index, (child_id, content) in enumerate(children, start=1):
            self.db.add(DocumentChunk(
                id=child_id, workspace_id="ws", document_id="doc", source_file="notes.md",
                chunk_index=index, content=content, tokenized_content="",
                chunk_level="child", parent_id=parent_id, content_type="concept",
            ))
        await self.db.commit()

    async def test_practice_mode_drops_answer_candidates(self):
        items = [
            _Candidate("c1", "题干：求条件概率。", content_type="question"),
            _Candidate("c2", "答案：0.4", content_type="answer"),
        ]
        prepared = await prepare_retrieval_context(
            self.db, items, question="这道题答案是什么", mode="practice"
        )

        self.assertEqual([source["chunk_id"] for source in prepared.sources], ["c1"])
        self.assertEqual(prepared.excluded_for_mode, 1)
        self.assertIn("practice_mode_excludes_answers", prepared.plan.reasons)

    async def test_parent_expansion_dedupes_and_keeps_citation_numbering(self):
        await self._seed_parent(
            "doc_parent_0",
            "小节完整正文，包含定义与推导。",
            [("doc_chunk_1", "子块一"), ("doc_chunk_2", "子块二")],
        )
        items = [
            _Candidate("doc_chunk_1", "子块一"),
            _Candidate("doc_chunk_2", "子块二"),
        ]
        prepared = await prepare_retrieval_context(self.db, items, question="条件概率是什么")

        # 引用列表仍是两条子块命中（编号不变）
        self.assertEqual(len(prepared.sources), 2)
        self.assertEqual([source["chunk_id"] for source in prepared.sources], ["doc_chunk_1", "doc_chunk_2"])
        # 上下文只保留父块一次，且编号沿用首个命中的子块
        self.assertEqual(len(prepared.context_chunks), 1)
        self.assertTrue(prepared.context_chunks[0].startswith("[资料1] "))
        self.assertIn("小节完整正文", prepared.context_chunks[0])
        self.assertEqual(prepared.expanded_parents, 1)
        self.assertTrue(any(note.startswith("shared_parent") for note in prepared.notes))

    async def test_reranker_degradation_is_recorded_without_reordering(self):
        items = [_Candidate("c1", "甲"), _Candidate("c2", "乙")]
        prepared = await prepare_retrieval_context(
            self.db,
            items,
            question="条件概率是什么",
            reranker=Reranker(mode="api"),   # 缺少 scorer → 明确降级
        )

        self.assertEqual(prepared.rerank_degraded, "reranker_unavailable")
        self.assertIn("rerank_degraded:reranker_unavailable", prepared.notes)
        self.assertEqual([source["chunk_id"] for source in prepared.sources], ["c1", "c2"])

    async def test_context_notes_surface_budget_and_duplicates(self):
        items = [
            _Candidate("c1", "甲" * 8000),
            _Candidate("c1", "甲" * 8000),
            _Candidate("c2", "乙" * 10),
        ]
        prepared = await prepare_retrieval_context(self.db, items, question="总结一下")

        self.assertTrue(any(note.startswith("duplicate_chunk") for note in prepared.notes))
        self.assertTrue(all(len(chunk) > 0 for chunk in prepared.context_chunks))
        self.assertEqual(len(prepared.sources), 3)   # sources 不做去重，审计仍逐条记录


if __name__ == "__main__":
    unittest.main()
