"""阶段 4：查询理解、重排三态、上下文构建与 Parent Expansion。"""

import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.rag.query.analyzer import analyze_query
from app.rag.query.rewriter import rewrite_queries
from app.rag.query.router import plan_query
from app.rag.retrieval.context import build_context_blocks, render_context
from app.rag.retrieval.parent import expand_parents
from app.rag.retrieval.reranker import Reranker


class _Item:
    def __init__(self, chunk_id: str, content: str, **extra):
        self.chunk_id = chunk_id
        self.content = content
        self.source_file = extra.get("source_file", "notes.md")
        self.page_num = extra.get("page_num")
        self.heading = extra.get("heading")


class QueryAnalyzerTests(unittest.TestCase):
    def test_intents_language_and_clues(self):
        exercise = analyze_query("第 3 题怎么算？求条件概率的答案")
        self.assertEqual(exercise.intent, "exercise")
        self.assertEqual(exercise.language, "zh")
        self.assertEqual(analyze_query("RAG 是什么").language, "mixed")

        self.assertEqual(analyze_query("RAG 是什么？").intent, "concept")
        self.assertEqual(analyze_query("如何实现混合检索").intent, "howto")
        self.assertEqual(analyze_query("向量召回和关键词召回的区别").intent, "compare")
        self.assertEqual(analyze_query("总结这一章").intent, "summary")
        self.assertEqual(analyze_query("LangGraph").intent, "lookup")

        formula = analyze_query("贝叶斯公式是怎么推导的？")
        self.assertTrue(formula.wants_formula)
        self.assertTrue(analyze_query("给出 Python 代码实现").wants_code)
        self.assertIn("RAG", analyze_query("RAG 是什么").entities)

    def test_rewrite_only_expands_when_enabled(self):
        analysis = analyze_query("RAG 是什么")
        self.assertEqual(rewrite_queries(analysis), ["RAG 是什么"])
        self.assertGreaterEqual(len(rewrite_queries(analysis, enabled=True)), 1)
        self.assertLessEqual(len(rewrite_queries(analysis, enabled=True, limit=1)), 1)


class QueryRouterTests(unittest.TestCase):
    def test_practice_mode_excludes_answers_and_prefers_questions(self):
        plan = plan_query(analyze_query("这道题怎么做"), mode="practice")
        self.assertIn("answer", plan.exclude_content_types)
        self.assertIn("question", plan.prefer_content_types)
        self.assertIn("practice_mode_excludes_answers", plan.reasons)

    def test_explain_mode_keeps_answers_and_uses_multivector_for_concepts(self):
        plan = plan_query(analyze_query("条件概率是什么"))
        self.assertEqual(plan.exclude_content_types, [])
        self.assertEqual(plan.vector_kinds[:1], ["content"])
        self.assertIn("summary", plan.vector_kinds)
        self.assertIn("concept_intent_uses_multivector", plan.reasons)

        formula_plan = plan_query(analyze_query("推导条件概率公式"))
        self.assertIn("formula", formula_plan.prefer_content_types)


class RerankerTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_and_local_modes_keep_hybrid_order(self):
        items = [_Item("a", "甲"), _Item("b", "乙")]
        self.assertEqual((await Reranker(mode="none").rerank("q", items)).items, items)
        outcome = await Reranker(mode="local").rerank("q", items)
        self.assertEqual(outcome.items, items)
        self.assertIsNone(outcome.degraded_reason)

    async def test_api_mode_reorders_and_reports_unavailable(self):
        items = [_Item("a", "甲"), _Item("b", "乙")]

        async def scorer(query, contents):
            return [0.1, 0.9]

        outcome = await Reranker(mode="api", scorer=scorer).rerank("q", items)
        self.assertTrue(outcome.reordered)
        self.assertEqual([item.chunk_id for item in outcome.items], ["b", "a"])

        unavailable = await Reranker(mode="api").rerank("q", items)
        self.assertEqual(unavailable.degraded_reason, "reranker_unavailable")
        self.assertEqual(unavailable.items, items)

    async def test_timeout_and_score_mismatch_degrade_without_losing_items(self):
        items = [_Item("a", "甲")]

        async def slow(query, contents):
            import asyncio

            await asyncio.sleep(0.05)
            return [1.0]

        timed_out = await Reranker(mode="api", scorer=slow, timeout_seconds=0.001).rerank("q", items)
        self.assertEqual(timed_out.degraded_reason, "reranker_timeout")
        self.assertEqual(timed_out.items, items)

        async def wrong_length(query, contents):
            return [1.0, 2.0]

        mismatch = await Reranker(mode="api", scorer=wrong_length).rerank("q", items)
        self.assertEqual(mismatch.degraded_reason, "reranker_score_mismatch")
        self.assertEqual(mismatch.items, items)


class ContextBuilderTests(unittest.TestCase):
    def test_numbering_matches_existing_prompt_format(self):
        items = [
            _Item("c1", "条件概率的定义。", page_num=12, heading="1.1 定义"),
            _Item("c2", "贝叶斯公式。"),
        ]
        blocks, notes = build_context_blocks(items)
        rendered = render_context(blocks)

        self.assertEqual(blocks[0].index, 1)
        self.assertEqual(notes, [])
        self.assertEqual(
            rendered[0],
            "[资料1] 来源：notes.md，第 12 页，章节：1.1 定义\n条件概率的定义。",
        )
        self.assertTrue(rendered[1].startswith("[资料2] 来源：notes.md\n"))

    def test_duplicates_are_skipped_and_budget_is_enforced(self):
        items = [
            _Item("c1", "甲" * 40),
            _Item("c1", "甲" * 40),
            _Item("c2", "乙" * 4000),
            _Item("c3", "丙" * 10),
        ]
        blocks, notes = build_context_blocks(items, token_budget=100)

        # 超预算的 c2 被丢弃，c1 与 c3 仍在预算内
        self.assertEqual([block.chunk_id for block in blocks], ["c1", "c3"])
        self.assertIn("duplicate_chunk:c1", notes)
        self.assertTrue(any("context_budget_exceeded:dropped:c2" == note for note in notes))


class ParentExpansionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _seed(self, *, parent_content: str, children: list[tuple[str, str]]) -> str:
        parent_id = "doc_parent_0"
        self.db.add(DocumentChunk(
            id=parent_id,
            workspace_id="ws",
            document_id="doc",
            source_file="notes.md",
            chunk_index=0,
            content=parent_content,
            tokenized_content="",
            chunk_level="parent",
            content_type="note",
        ))
        for index, (child_id, content) in enumerate(children, start=1):
            self.db.add(DocumentChunk(
                id=child_id,
                workspace_id="ws",
                document_id="doc",
                source_file="notes.md",
                chunk_index=index,
                content=content,
                tokenized_content="",
                chunk_level="child",
                parent_id=parent_id,
                content_type="concept",
            ))
        await self.db.commit()
        return parent_id

    async def test_child_hit_expands_to_parent_and_deduplicates(self):
        parent_id = await self._seed(
            parent_content="小节完整正文。",
            children=[("doc_chunk_1", "子块一"), ("doc_chunk_2", "子块二")],
        )
        outcome = await expand_parents(self.db, [_Item("doc_chunk_1", "子块一"), _Item("doc_chunk_2", "子块二")])

        self.assertEqual(len(outcome.items), 1)
        self.assertEqual(outcome.items[0].chunk_id, parent_id)
        self.assertEqual(outcome.items[0].content, "小节完整正文。")
        self.assertEqual(outcome.items[0].expanded_from, "doc_chunk_1")
        self.assertEqual(outcome.shared_parents, 1)
        self.assertTrue(any(reason.startswith("shared_parent") for reason in outcome.reasons))

    async def test_oversized_parent_falls_back_to_child_with_neighbors(self):
        parent_id = await self._seed(
            parent_content="甲" * 3000,
            children=[("doc_chunk_1", "子块"), ("doc_chunk_2", "相邻块")],
        )
        outcome = await expand_parents(self.db, [_Item("doc_chunk_1", "子块")], max_parent_tokens=100)

        item = outcome.items[0]
        self.assertEqual(item.chunk_id, "doc_chunk_1")
        self.assertIn("parent_over_budget", item.notes)
        self.assertEqual(item.neighbors, ["doc_chunk_2"])
        self.assertTrue(any(reason.startswith(f"parent_over_budget:{parent_id}") for reason in outcome.reasons))

    async def test_items_without_parent_pass_through_unchanged(self):
        outcome = await expand_parents(self.db, [_Item("missing", "自由文本")])
        self.assertEqual(len(outcome.items), 1)
        self.assertEqual(outcome.items[0].content, "自由文本")


if __name__ == "__main__":
    unittest.main()
