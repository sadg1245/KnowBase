"""Evidence policy contracts for generated learning answers."""

import importlib
import unittest


def _module():
    try:
        return importlib.import_module("app.services.learning_answer")
    except ModuleNotFoundError:
        return None


class LearningAnswerPolicyTests(unittest.TestCase):
    def test_follow_up_suggestions_are_bounded_and_mode_specific(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        direct = module.build_follow_up_suggestions("什么是向量检索", "direct")
        socratic = module.build_follow_up_suggestions("什么是向量检索", "socratic")

        self.assertEqual(len(direct), 3)
        self.assertEqual(len(socratic), 3)
        self.assertNotEqual(direct, socratic)

    def test_unknown_mode_still_returns_three_suggestions(self):
        module = _module()
        if module is None:
            self.fail("learning_answer service is missing")

        self.assertEqual(len(module.build_follow_up_suggestions("问题", "unknown")), 3)


if __name__ == "__main__":
    unittest.main()
