"""Contracts for AI-backed assessment generation and subjective grading."""

import json
import unittest

from app.config import Settings
from app.schemas.assessment import QuizSetGenerateRequest
from app.services.assessment_ai import (
    AssessmentAIError,
    build_generated_paper,
    evaluate_subjective,
)


EVIDENCE = [{
    "chunk_id": "chunk-1",
    "document_id": "document-1",
    "page_num": 3,
    "heading": "Foundations",
    "content": "A triangle has three sides.",
}]
REQUEST = QuizSetGenerateRequest(
    workspace_id="workspace-1",
    count=1,
    difficulty="medium",
    question_types=["single_choice"],
    strict_sources=True,
)
SETTINGS = Settings.model_construct(
    DEFAULT_LLM_PROVIDER="ollama",
    DEFAULT_LLM_MODEL="test-model",
    OLLAMA_BASE_URL="http://ollama.test",
)


def response(payload):
    """Return the smallest LiteLLM-shaped response used by the real boundary."""
    message = type("Message", (), {"content": json.dumps(payload)})()
    return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()


def fake_completion(*payloads):
    payloads = iter(payloads)

    async def complete(**_kwargs):
        return response(next(payloads))

    return complete


def generated_question(**overrides):
    payload = {
        "question_type": "single_choice",
        "prompt": "How many sides does a triangle have?",
        "options": ["Two", "Three"],
        "answer_payload": "Three",
        "explanation": "A triangle is a three-sided polygon.",
        "grading_rubric": {},
        "source_chunk_ids": ["chunk-1"],
        "difficulty": "medium",
    }
    payload.update(overrides)
    return payload


class AssessmentGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_rejects_unknown_source_chunks(self):
        completion = fake_completion({"questions": [generated_question(source_chunk_ids=["not-retrieved"])]})

        with self.assertRaisesRegex(AssessmentAIError, "unknown source") as raised:
            await build_generated_paper(EVIDENCE, REQUEST, SETTINGS, completion)

        self.assertEqual(raised.exception.status_code, 502)

    async def test_missing_provider_is_a_409_without_template_fallback(self):
        missing_provider = Settings.model_construct(
            DEFAULT_LLM_PROVIDER="ollama",
            DEFAULT_LLM_MODEL="",
            OLLAMA_BASE_URL="http://ollama.test",
        )

        with self.assertRaises(AssessmentAIError) as raised:
            await build_generated_paper(EVIDENCE, REQUEST, missing_provider)

        self.assertEqual(raised.exception.status_code, 409)

    async def test_strict_generation_requires_evidence(self):
        with self.assertRaises(AssessmentAIError) as raised:
            await build_generated_paper([], REQUEST, SETTINGS, fake_completion({"questions": []}))

        self.assertEqual(raised.exception.status_code, 422)

    async def test_invalid_structured_output_is_repaired_once_then_rejected(self):
        completion = fake_completion({"questions": []}, {"questions": []})

        with self.assertRaises(AssessmentAIError) as raised:
            await build_generated_paper(EVIDENCE, REQUEST, SETTINGS, completion)

        self.assertEqual(raised.exception.status_code, 502)

    async def test_provider_failure_is_a_503(self):
        async def unavailable(**_kwargs):
            raise RuntimeError("offline")

        with self.assertRaises(AssessmentAIError) as raised:
            await build_generated_paper(EVIDENCE, REQUEST, SETTINGS, unavailable)

        self.assertEqual(raised.exception.status_code, 503)

    async def test_generation_accepts_all_question_types_with_their_required_answers(self):
        request = REQUEST.model_copy(update={
            "count": 6,
            "question_types": [
                "single_choice", "multiple_choice", "true_false", "fill_blank",
                "short_answer", "concept_explanation",
            ],
        })
        questions = [
            generated_question(),
            generated_question(question_type="multiple_choice", answer_payload=["Two", "Three"]),
            generated_question(question_type="true_false", options=["True", "False"], answer_payload="True"),
            generated_question(question_type="fill_blank", options=[], answer_payload=["Three"]),
            generated_question(question_type="short_answer", options=[], answer_payload="Three", grading_rubric={"points": ["States three"]}),
            generated_question(question_type="concept_explanation", options=[], answer_payload="Three sides", grading_rubric={"points": ["Explains three sides"]}),
        ]

        paper = await build_generated_paper(EVIDENCE, request, SETTINGS, fake_completion({"questions": questions}))

        self.assertEqual([question.question_type for question in paper.questions], request.question_types)
        self.assertEqual(paper.questions[4].grading_rubric, {"points": ["States three"]})


class SubjectiveEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_evaluation_requires_complete_structured_result(self):
        question = generated_question(
            question_type="short_answer",
            options=[],
            answer_payload="Three",
            grading_rubric={"points": ["States three"]},
            source_snapshot=EVIDENCE,
        )
        completion = fake_completion({
            "score": 1,
            "max_score": 1,
            "is_correct": True,
            "feedback": "Correct.",
            "error_reason": None,
            "matched_points": ["States three"],
        }, {
            "score": 1,
            "max_score": 1,
            "is_correct": True,
            "feedback": "Correct.",
            "error_reason": None,
            "matched_points": ["States three"],
        })

        with self.assertRaises(AssessmentAIError) as raised:
            await evaluate_subjective(question, "A triangle has three sides.", SETTINGS, completion)

        self.assertEqual(raised.exception.status_code, 502)

    async def test_evaluation_returns_validated_feedback(self):
        question = generated_question(
            question_type="short_answer",
            options=[],
            answer_payload="Three",
            grading_rubric={"points": ["States three"]},
            source_snapshot=EVIDENCE,
        )
        completion = fake_completion({
            "score": 1,
            "max_score": 1,
            "is_correct": True,
            "feedback": "Correct.",
            "error_reason": None,
            "matched_points": ["States three"],
            "missing_points": [],
        })

        result = await evaluate_subjective(question, "A triangle has three sides.", SETTINGS, completion)

        self.assertTrue(result.is_correct)
        self.assertEqual(result.score, 1)


if __name__ == "__main__":
    unittest.main()
