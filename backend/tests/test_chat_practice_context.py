"""§16.2：练习语境要能从 HTTP 契约一路走到检索与提示词。"""

import unittest

from pydantic import ValidationError

from app.rag.query.analyzer import analyze_query
from app.rag.query.router import plan_query
from app.schemas.schemas import ChatRequest
from app.services import learning_answer_service


class ChatPracticeModeTests(unittest.TestCase):
    def test_chat_request_accepts_practice_mode(self):
        payload = ChatRequest(question="这道题怎么做", mode="practice")

        self.assertEqual(payload.mode, "practice")

    def test_chat_request_still_rejects_unknown_modes(self):
        with self.assertRaises(ValidationError):
            ChatRequest(question="这道题怎么做", mode="exam")

    def test_practice_mode_excludes_answers_at_recall(self):
        plan = plan_query(analyze_query("这道题怎么做"), mode="practice")

        self.assertEqual(sorted(plan.exclude_content_types), ["answer", "solution"])
        self.assertIn("question", plan.prefer_content_types)
        self.assertIn("practice_mode_excludes_answers", plan.reasons)

    def test_practice_prompt_forbids_revealing_the_answer(self):
        prompt = learning_answer_service.build_learning_prompt(
            question="这道题怎么做",
            mode="practice",
            context_blocks=["[资料1] 来源：exam.pdf\n已知 P(A)=0.3，求 P(B)。"],
        )

        self.assertIn("练习语境", prompt)
        self.assertIn("不要直接给出最终答案", prompt)
        self.assertNotIn("默认读者是初学者", prompt)


if __name__ == "__main__":
    unittest.main()
