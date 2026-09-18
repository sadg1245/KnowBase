"""The chat route must answer source-first without a strict-mode branch."""

import importlib
import unittest
from pathlib import Path

from app.services import learning_answer_service as service


ROUTE_SOURCE = Path("backend/app/api/routes/search.py")


class ChatPolicyTests(unittest.TestCase):
    def test_strict_mode_helpers_are_removed(self):
        module = importlib.import_module("app.services.learning_answer")

        for name in ("answer_requires_model", "strict_refusal", "filter_strict_answer"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(module, name))

    def test_chat_route_no_longer_branches_on_strict_sources(self):
        source = ROUTE_SOURCE.read_text(encoding="utf-8")

        for forbidden in ("answer_requires_model", "strict_refusal", "filter_strict_answer"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("build_learning_prompt", source)
        self.assertIn("parse_layered_answer", source)

    def test_model_fallback_only_needs_one_working_retriever(self):
        self.assertFalse(service.retrieval_available(vector_succeeded=False, keyword_succeeded=False))
        self.assertTrue(service.retrieval_available(vector_succeeded=True, keyword_succeeded=False))
        self.assertTrue(service.retrieval_available(vector_succeeded=False, keyword_succeeded=True))

    def test_empty_answer_fallback_text_is_deterministic(self):
        self.assertEqual(service.deterministic_empty_answer(), service.deterministic_empty_answer())
        self.assertIn("没有相关内容", service.deterministic_empty_answer())

    def test_retrieval_outage_is_not_reported_as_model_fallback(self):
        source = ROUTE_SOURCE.read_text(encoding="utf-8")

        self.assertIn("retrievers_ok=retrievers_ok", source)
        self.assertIn('"model_fallback": retrievers_ok and', source)

    def test_outage_status_wins_over_missing_citations(self):
        parsed = service.parse_layered_answer(service.DETERMINISTIC_RETRIEVAL_ERROR, 0)

        self.assertEqual(
            service.merged_evidence_status("insufficient", parsed, retrievers_ok=False),
            "error",
        )


if __name__ == "__main__":
    unittest.main()
