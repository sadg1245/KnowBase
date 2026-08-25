"""Evidence policy contracts for generated learning answers."""

import importlib
import unittest


def _module():
    try:
        return importlib.import_module("app.services.learning_answer")
    except ModuleNotFoundError:
        return None


class LearningAnswerPolicyTests(unittest.TestCase):
    def test_strict_mode_only_calls_model_for_supported_evidence(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        self.assertTrue(module.answer_requires_model(True, "supported"))
        self.assertFalse(module.answer_requires_model(True, "limited"))
        self.assertFalse(module.answer_requires_model(True, "insufficient"))
        self.assertTrue(module.answer_requires_model(False, "insufficient"))

    def test_strict_answer_removes_unreferenced_and_unknown_citations(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        answer = "资料支持的结论。[资料1]\n\n没有引用的扩写。\n\n伪造来源。[资料9]"
        filtered = module.filter_strict_answer(answer, source_count=2)

        self.assertEqual(filtered, "资料支持的结论。[资料1]")

    def test_deterministic_refusal_explains_limited_and_insufficient_evidence(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        limited = module.strict_refusal("limited")
        insufficient = module.strict_refusal("insufficient")

        self.assertIn("证据不足", limited)
        self.assertIn("相关文件", limited)
        self.assertIn("没有找到", insufficient)
        self.assertNotEqual(limited, insufficient)

    def test_follow_up_suggestions_are_bounded_and_mode_specific(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        direct = module.build_follow_up_suggestions("什么是向量检索", "direct")
        socratic = module.build_follow_up_suggestions("什么是向量检索", "socratic")

        self.assertEqual(len(direct), 3)
        self.assertEqual(len(socratic), 3)
        self.assertNotEqual(direct, socratic)


if __name__ == "__main__":
    unittest.main()
