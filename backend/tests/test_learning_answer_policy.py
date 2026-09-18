"""Answer layering and citation contracts for the source-first tutor policy."""

import unittest

from app.services import learning_answer_service as service


class LayeredAnswerTests(unittest.TestCase):
    def test_valid_citations_are_kept_in_source_layer(self):
        answer = (
            "## 来自私人资料\n"
            "向量检索用余弦相似度排序。[资料1]\n\n"
            "## AI 补充（模型记忆）\n"
            "这部分来自模型通用知识。"
        )
        parsed = service.parse_layered_answer(answer, source_count=2)

        self.assertEqual(parsed.answer_layers, ["sources", "model"])
        self.assertEqual(parsed.layers[0].citations, [1])
        self.assertIn("[资料1]", parsed.content)
        self.assertFalse(parsed.unstructured)

    def test_unknown_citation_is_removed_and_counted(self):
        answer = "## 来自私人资料\n支持的结论。[资料1] 越界引用。[资料9]"
        parsed = service.parse_layered_answer(answer, source_count=2)

        self.assertNotIn("[资料9]", parsed.content)
        self.assertIn("[资料1]", parsed.content)
        self.assertEqual(parsed.invalid_citations, 1)

    def test_model_layer_never_keeps_citations(self):
        answer = "## AI 补充（模型记忆）\n模型补充了一条事实。[资料1]"
        parsed = service.parse_layered_answer(answer, source_count=3)

        self.assertNotIn("[资料", parsed.content)
        self.assertEqual(parsed.layers[0].citations, [])
        self.assertEqual(parsed.invalid_citations, 1)

    def test_unstructured_answer_is_flagged_and_still_sanitized(self):
        parsed = service.parse_layered_answer("没有标题的回答。[资料7]", source_count=1)

        self.assertTrue(parsed.unstructured)
        self.assertEqual(parsed.answer_layers, ["mixed"])
        self.assertNotIn("[资料7]", parsed.content)
        self.assertEqual(parsed.invalid_citations, 1)

    def test_empty_answer_yields_no_layers(self):
        parsed = service.parse_layered_answer("   ", source_count=2)

        self.assertEqual(parsed.layers, [])
        self.assertEqual(parsed.content, "")
        self.assertTrue(service.sources_layer_empty(parsed))

    def test_evidence_status_becomes_model_only_without_cited_sources(self):
        model_only = service.parse_layered_answer("## AI 补充（模型记忆）\n只有模型知识。", 2)
        supported = service.parse_layered_answer("## 来自私人资料\n结论。[资料1]", 2)

        self.assertEqual(service.merged_evidence_status("insufficient", model_only), "model_only")
        self.assertEqual(service.merged_evidence_status("supported", supported), "supported")
        self.assertEqual(service.merged_evidence_status("error", model_only), "error")


if __name__ == "__main__":
    unittest.main()
