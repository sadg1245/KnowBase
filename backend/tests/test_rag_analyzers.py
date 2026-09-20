"""阶段 2：文档分类、结构树与知识单元抽取的确定性规则。"""

import unittest

from app.rag.analyzers.document_classifier import classify_document
from app.rag.analyzers.knowledge_extractor import extract_units
from app.rag.analyzers.structure_analyzer import build_structure
from app.rag.contracts import Block


def block(order: int, block_type: str, content: str, *, level: int | None = None, page: int | None = None) -> Block:
    return Block(
        block_id=f"doc:b{order}",
        type=block_type,  # type: ignore[arg-type]
        content=content,
        order=order,
        heading_level=level,
        page=page,
    )


class DocumentClassifierTests(unittest.TestCase):
    def test_structural_file_types_are_classified_without_llm(self):
        self.assertEqual(classify_document([], file_type="pptx").document_type, "slides")
        self.assertEqual(classify_document([], file_type="xlsx").document_type, "documentation")
        self.assertEqual(classify_document([], file_type="csv").document_type, "documentation")
        code = classify_document(
            [block(0, "paragraph", '{"a": 1}')], file_type="txt", filename="config.json"
        )
        self.assertEqual(code.document_type, "code_document")
        self.assertGreaterEqual(code.confidence, 0.8)

    def test_textbook_exam_and_paper_rules(self):
        textbook = classify_document([
            block(0, "heading", "第 1 章 概率论", level=1),
            block(1, "paragraph", "本章介绍条件概率。"),
            block(2, "paragraph", "习题：求 P(A|B)。"),
        ])
        self.assertEqual(textbook.document_type, "textbook")
        self.assertGreaterEqual(textbook.confidence, 0.8)
        self.assertTrue(textbook.reasons)

        exam = classify_document([
            block(0, "paragraph", "一、选择题（大题）"),
            block(1, "paragraph", "1. 条件概率的定义是什么？"),
            block(2, "paragraph", "参考答案：P(A|B)=P(AB)/P(B)"),
        ])
        self.assertEqual(exam.document_type, "exam")
        self.assertEqual(exam.source, "rules")

        paper = classify_document([
            block(0, "heading", "Abstract", level=1),
            block(1, "paragraph", "We study retrieval."),
            block(2, "heading", "Method", level=1),
            block(3, "heading", "Conclusion", level=1),
        ])
        self.assertEqual(paper.document_type, "paper")

    def test_heading_density_distinguishes_tutorial_and_notes(self):
        headings = [block(index, "heading", f"小节 {index}", level=2) for index in range(3)]
        notes = classify_document(headings + [block(3, "paragraph", "普通笔记内容。")])
        self.assertEqual(notes.document_type, "notes")

        tutorial = classify_document(headings + [block(3, "code", "print(1)")])
        self.assertEqual(tutorial.document_type, "tutorial")
        self.assertGreaterEqual(tutorial.confidence, 0.8)

    def test_llm_fallback_and_unstructured_degradation(self):
        blocks = [block(0, "paragraph", "一段没有明显结构的文字。")]

        degraded = classify_document(blocks)
        self.assertEqual(degraded.document_type, "unstructured")
        self.assertEqual(degraded.confidence, 0.0)
        self.assertEqual(degraded.source, "fallback")

        def good_llm(_prompt: str) -> str:
            return '{"document_type": "notes", "confidence": 0.71, "reasons": ["段落为主"]}'

        from_llm = classify_document(blocks, llm=good_llm)
        self.assertEqual(from_llm.document_type, "notes")
        self.assertEqual(from_llm.source, "llm")

        def broken_llm(_prompt: str) -> str:
            raise RuntimeError("provider offline")

        still_degraded = classify_document(blocks, llm=broken_llm)
        self.assertEqual(still_degraded.document_type, "unstructured")
        self.assertEqual(still_degraded.source, "fallback")


class StructureAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [
            block(0, "heading", "第一章 概率", level=1),
            block(1, "paragraph", "条件概率是指已知 B 发生时 A 的概率。"),
            block(2, "heading", "1.1 定义", level=2),
            block(3, "formula", "P(A|B)=\\frac{P(AB)}{P(B)}"),
            block(4, "heading", "1.2 例题", level=2),
            block(5, "code", "p = ab / b"),
        ]

    def test_heading_tree_covers_every_block_with_valid_parents(self):
        nodes = build_structure(self.blocks, document_type="textbook", document_id="doc")

        kinds = [node.node_type for node in nodes]
        self.assertEqual(kinds[0], "document")
        self.assertIn("chapter", kinds)
        self.assertEqual(kinds.count("section"), 2)

        covered = {
            index
            for node in nodes
            for index in range(node.block_start, node.block_end + 1)
        }
        self.assertEqual(covered, set(range(len(self.blocks))))

        leaves = [node for node in nodes if node.node_type not in {"document", "chapter", "section"}]
        spans = [(node.block_start, node.block_end) for node in leaves]
        for left, right in zip(sorted(spans), sorted(spans)[1:]):
            self.assertLess(left[1], right[0], f"叶子节点重叠：{left} / {right}")

        by_id = {node.node_id: node for node in nodes}
        for node in nodes:
            if node.parent_node_id is not None:
                parent = by_id[node.parent_node_id]
                self.assertLess(parent.level, node.level)

        chapter = next(node for node in nodes if node.node_type == "chapter")
        # 父节点跨度覆盖其全部子节点，便于 Parent Expansion 取整节原文
        self.assertEqual(chapter.block_end, 5)

    def test_question_tree_pairs_stem_with_solution(self):
        blocks = [
            block(0, "question", "1. 求条件概率 P(A|B)。"),
            block(1, "answer", "解答：使用定义式。"),
            block(2, "answer", "答案：0.4"),
        ]
        nodes = build_structure(blocks, document_type="exam", document_id="doc")

        question = next(node for node in nodes if node.node_type == "question")
        children = [node for node in nodes if node.parent_node_id == question.node_id]
        self.assertEqual({child.node_type for child in children}, {"answer"})
        self.assertEqual(question.block_start, 0)
        self.assertEqual(question.block_end, 2)

    def test_structure_degrades_to_empty_without_headings(self):
        blocks = [block(0, "paragraph", "没有标题的一段文字。")]
        self.assertEqual(build_structure(blocks, document_type="notes", document_id="doc"), [])


class KnowledgeExtractorTests(unittest.TestCase):
    def test_structure_nodes_become_typed_units(self):
        blocks = [
            block(0, "heading", "第一章 概率", level=1),
            block(1, "heading", "1.1 定义", level=2),
            block(2, "paragraph", "条件概率是指已知 B 发生时 A 的概率。"),
            block(3, "formula", "P(A|B)=\\frac{P(AB)}{P(B)}"),
        ]
        nodes = build_structure(blocks, document_type="textbook", document_id="doc")
        units = extract_units(blocks, nodes, document_id="doc", workspace_id="ws")

        types = [unit.unit_type for unit in units]
        self.assertIn("chapter", types)
        self.assertIn("section", types)
        self.assertIn("definition", types)
        self.assertIn("formula", types)

        chapter = next(unit for unit in units if unit.unit_type == "chapter")
        section = next(unit for unit in units if unit.unit_type == "section")
        definition = next(unit for unit in units if unit.unit_type == "definition")
        self.assertEqual(chapter.title, "第一章 概率")
        self.assertEqual(chapter.chapter, "第一章 概率")
        self.assertEqual(section.parent_id, chapter.unit_id)
        self.assertEqual(definition.section, "1.1 定义")
        self.assertIn("条件概率", definition.content)
        self.assertEqual([unit.unit_id for unit in units], [f"doc:u{i}" for i in range(len(units))])

    def test_block_level_rules_work_without_structure(self):
        blocks = [
            block(0, "paragraph", "闭包是指捕获外部变量的函数。"),
            block(1, "paragraph", "例 1：写出一个闭包。"),
            block(2, "question", "2. 闭包和普通函数的区别？"),
            block(3, "answer", "答案：闭包保留外部作用域。"),
            block(4, "code", "def outer(): pass"),
        ]
        units = extract_units(blocks, [], document_id="doc", workspace_id="ws")

        self.assertEqual(
            [unit.unit_type for unit in units],
            ["definition", "example", "question", "answer", "code"],
        )
        self.assertTrue(all(unit.document_id == "doc" and unit.workspace_id == "ws" for unit in units))


if __name__ == "__main__":
    unittest.main()
