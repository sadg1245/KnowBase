"""阶段 3：切分策略、路由、语义分块与大小校验。"""

import unittest

from app.rag.chunking.base import Chunk, ChunkingContext, ChunkStrategy, estimate_tokens
from app.rag.chunking.router import ChunkRouter
from app.rag.chunking.semantic import SemanticChunkStrategy, cosine_similarity, split_sentences
from app.rag.chunking.strategies import (
    CodeChunkStrategy,
    ExamChunkStrategy,
    FallbackChunkStrategy,
    StructureChunkStrategy,
)
from app.rag.chunking.validator import ChunkValidator, normalize_text
from app.rag.contracts import Block


def block(order: int, block_type: str, content: str, *, level: int | None = None,
          path: list[str] | None = None, page: int | None = None) -> Block:
    return Block(
        block_id=f"doc:b{order}",
        type=block_type,  # type: ignore[arg-type]
        content=content,
        order=order,
        heading_level=level,
        section_path=list(path or []),
        page=page,
    )


def context(blocks: list[Block], document_type: str = "textbook") -> ChunkingContext:
    return ChunkingContext(
        document_id="doc",
        workspace_id="ws",
        document_type=document_type,
        blocks=blocks,
        filename="chapter.md",
    )


class TokenEstimatorTests(unittest.TestCase):
    def test_cjk_and_latin_word_accounting(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("条件概率"), 4)
        # 拉丁词按 1.3 token/词估算，标点按 0.3 计
        self.assertEqual(estimate_tokens("retrieval augmented"), 3)
        self.assertGreater(estimate_tokens("条件概率 retrieval"), estimate_tokens("条件概率"))


class ValidatorTests(unittest.TestCase):
    def test_normalize_collapses_blank_lines_and_trailing_spaces(self):
        self.assertEqual(normalize_text("a  \n\n\n\nb\r\n"), "a\n\nb")

    def test_atomic_blocks_are_never_split_or_merged(self):
        validator = ChunkValidator(min_tokens=10, max_tokens=20)
        formula = Chunk(
            chunk_id="doc_chunk_0", document_id="doc", workspace_id="ws",
            content="x = " + "y " * 200, content_type="formula", parent_id="p1",
        )
        split = validator.split_oversized(formula)
        self.assertEqual(len(split), 1)
        self.assertTrue(split[0].metadata["oversized_ok"])
        self.assertGreater(split[0].tokens, 20)

    def test_undersized_chunks_merge_only_within_the_same_parent(self):
        validator = ChunkValidator(min_tokens=50, max_tokens=400)
        chunks = [
            Chunk(chunk_id="a", document_id="doc", workspace_id="ws", content="短句一。", parent_id="p1"),
            Chunk(chunk_id="b", document_id="doc", workspace_id="ws", content="短句二。", parent_id="p1"),
            Chunk(chunk_id="c", document_id="doc", workspace_id="ws", content="别的父块。", parent_id="p2"),
        ]
        merged = validator.merge_undersized(chunks)
        self.assertEqual(len(merged), 2)
        self.assertIn("短句一。", merged[0].content)
        self.assertIn("短句二。", merged[0].content)
        self.assertEqual(merged[0].metadata["merge_reason"], "below_min_tokens")
        self.assertEqual(merged[1].parent_id, "p2")
        self.assertEqual(merged[1].metadata["merge_reason"], "below_min_tokens_no_sibling")


class StrategyTests(unittest.IsolatedAsyncioTestCase):
    async def test_structure_strategy_builds_parent_and_typed_children(self):
        blocks = [
            block(0, "heading", "第 1 章 概率", level=1, path=["第 1 章 概率"]),
            block(1, "paragraph", "条件概率是指已知 B 发生时 A 的概率。" * 12,
                  path=["第 1 章 概率"]),
            block(2, "formula", "P(A|B)=P(AB)/P(B)", path=["第 1 章 概率"]),
            block(3, "heading", "1.1 例题", level=2, path=["第 1 章 概率", "1.1 例题"]),
            block(4, "code", "def solve():\n    return 1", path=["第 1 章 概率", "1.1 例题"]),
        ]
        chunks = await StructureChunkStrategy().chunk(context(blocks))

        parents = [chunk for chunk in chunks if chunk.chunk_level == "parent"]
        children = [chunk for chunk in chunks if chunk.chunk_level == "child"]
        self.assertEqual(len(parents), 2)
        self.assertEqual(parents[0].section_path, ["第 1 章 概率"])
        self.assertIn("1.1 例题", parents[1].section_path)
        self.assertTrue(all(child.parent_id for child in children))
        types = {child.content_type for child in children}
        self.assertIn("definition", types)
        self.assertIn("formula", types)
        self.assertIn("code", types)
        # 每个 child 都归属到真实存在的 parent
        parent_ids = {parent.chunk_id for parent in parents}
        self.assertTrue({child.parent_id for child in children} <= parent_ids)

    async def test_exam_strategy_keeps_the_stem_and_answer_in_separate_children(self):
        blocks = [
            block(0, "question", "1. 求条件概率 P(A|B)。"),
            block(1, "answer", "解答：使用定义式，答案是 0.4。"),
        ]
        chunks = await ExamChunkStrategy().chunk(context(blocks, "exam"))

        parent = next(chunk for chunk in chunks if chunk.chunk_level == "parent")
        children = [chunk for chunk in chunks if chunk.chunk_level == "child"]
        self.assertEqual(parent.content_type, "question")
        stem = next(child for child in children if child.content_type == "question")
        answer = next(child for child in children if child.content_type == "answer")
        self.assertIn("求条件概率", stem.content)
        self.assertNotIn("0.4", stem.content)          # 练习模式只召回题干
        self.assertEqual(stem.parent_id, answer.parent_id)

    async def test_code_strategy_splits_on_function_boundaries(self):
        blocks = [
            block(0, "paragraph", "下面两个函数分别处理召回与重排。"),
            block(1, "code", "def recall(q):\n    return []\n\ndef rerank(items):\n    return items"),
        ]
        chunks = await CodeChunkStrategy().chunk(context(blocks, "code_document"))

        children = [chunk for chunk in chunks if chunk.chunk_level == "child"]
        code_children = [chunk for chunk in children if chunk.content_type == "code"]
        self.assertEqual(len(code_children), 2)
        self.assertEqual(code_children[0].metadata["code_segment"], 0)
        self.assertTrue(any(chunk.content_type == "concept" for chunk in children))

    async def test_fallback_strategy_keeps_all_content(self):
        blocks = [block(0, "paragraph", "第一段。" * 80), block(1, "paragraph", "第二段。" * 80)]
        chunks = await FallbackChunkStrategy().chunk(context(blocks, "unstructured"))
        self.assertTrue(chunks)
        joined = "".join(chunk.content for chunk in chunks)
        self.assertIn("第一段。", joined)
        self.assertIn("第二段。", joined)
        self.assertTrue(all(chunk.chunk_level == "child" for chunk in chunks))

    async def test_semantic_strategy_uses_similarity_and_degrades_without_embedding(self):
        text = block(0, "paragraph", "条件概率的定义。贝叶斯公式。完全无关的天气话题。")
        context_ = context([text], "unstructured")

        async def embedder(sentences):
            # 前两句相似，第三句与第二句差异大 → 在第三句前切开
            return [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]][: len(sentences)]

        permissive = ChunkValidator(min_tokens=1, max_tokens=1200)
        chunks = await SemanticChunkStrategy(threshold=0.62, validator=permissive).chunk(
            context_, embed=embedder
        )
        self.assertEqual(len(chunks), 2)
        self.assertIn("条件概率", chunks[0].content)
        self.assertIn("天气", chunks[1].content)

        degraded = await SemanticChunkStrategy(validator=permissive).chunk(context_, embed=None)
        self.assertTrue(degraded)

    async def test_similarity_and_sentence_helpers(self):
        self.assertEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertEqual(cosine_similarity([1, 0], [0, 1]), 0.0)
        self.assertEqual(cosine_similarity([], []), 0.0)
        self.assertEqual(split_sentences("甲。乙！丙"), ["甲。", "乙！", "丙"])


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_type_and_failures_fall_back(self):
        router = ChunkRouter()
        self.assertEqual(router.get_strategy("nonsense").name, "fallback")
        self.assertEqual(router.get_strategy("textbook").name, "structure")
        self.assertEqual(router.get_strategy("exam").name, "exam")
        self.assertEqual(router.get_strategy("code_document").name, "code")

        chunked = await router.chunk(context([block(0, "paragraph", "内容。" * 30)], "nonsense"))
        self.assertTrue(chunked)

        class Exploding(ChunkStrategy):
            name = "exploding"

            async def chunk(self, context, *, embed=None):
                raise RuntimeError("boom")

        router._mapping["exploding"] = Exploding()
        recovered = await router.chunk(context([block(0, "paragraph", "内容。" * 30)], "exploding"))
        self.assertTrue(recovered)
        self.assertEqual(recovered[0].metadata["strategy_fallback_from"], "exploding")

        empty = await router.chunk(context([block(0, "paragraph", "内容。" * 30)], "exam"))
        self.assertTrue(empty)


if __name__ == "__main__":
    unittest.main()
