"""Whole-branch regressions: exercise source, grading, and recovery behavior."""
import json
import unittest
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from sqlalchemy import select, func

from app.models.assessment import MistakeRecord, QuizAttempt, QuizRun, QuizSet
from app.models.chat import DocumentChunk
from app.models.learning import KnowledgePoint, QuizQuestion
from app.schemas.assessment import QuestionSubmitRequest
from app.services import assessment_service as service
from app.services.assessment_scoring import grade_objective
from tests import test_assessment_service as fixtures, test_assessment_api as api_fixtures
from tests.test_assessment_service import NOW, SETTINGS, _completion, _generated_question, _response


def evaluation(correct):
    return {"score": int(correct), "max_score": 1, "is_correct": correct,
            "feedback": "Reviewed", "error_reason": None if correct else "Missing sides",
            "matched_points": ["three sides"] if correct else [], "missing_points": [] if correct else ["three sides"]}


class FinalServiceFixTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AssessmentServiceTests.asyncSetUp
    asyncTearDown = fixtures.AssessmentServiceTests.asyncTearDown
    request = fixtures.AssessmentServiceTests.request
    make_set = fixtures.AssessmentServiceTests.make_set

    async def test_impossible_type_count_is_rejected_without_a_generation_record(self):
        # The provider raises if reached; validation must produce 422 beforehand.
        async def forbidden(**kwargs):
            raise AssertionError("Impossible request reached the provider")
        try:
            request = self.request(count=1, question_types=["single_choice", "fill_blank"])
            await service.generate_quiz_set(self.db, request, SETTINGS, forbidden)
        except Exception as exc:
            self.assertEqual(getattr(exc, "status_code", 422 if isinstance(exc, ValueError) else None), 422)
        else:
            self.fail("Impossible assessment accepted")
        self.assertEqual(await self.db.scalar(select(func.count(QuizSet.id))), 0)

    async def test_explicit_point_excludes_other_chapters_and_sends_point_context(self):
        self.point.source_page = 3
        self.point.summary = "Recognize a triangle by its three sides."
        self.db.add(DocumentChunk(id="unrelated", workspace_id=self.workspace.id,
            document_id=self.document.id, source_file="geometry.pdf", page_num=9,
            heading="Circles", section_path=["Circles"], chunk_index=1,
            content="SECRET_UNRELATED: circle circumference", tokenized_content="circle"))
        await self.db.commit()
        received = []
        async def complete(**kwargs):
            received.append(kwargs["messages"][0]["content"])
            return _response({"questions": [_generated_question()]})
        paper = await service.generate_quiz_set(self.db, self.request(section_filters=[]), SETTINGS, complete)
        self.assertNotIn("SECRET_UNRELATED", received[0])
        self.assertIn(self.point.title, received[0])
        self.assertIn(self.point.summary, received[0])
        self.assertIn(self.point.id, received[0])
        question = (await self.db.execute(select(QuizQuestion).where(QuizQuestion.quiz_set_id == paper.id))).scalar_one()
        self.assertEqual(question.knowledge_point_id, self.point.id)

    async def test_explicit_point_with_no_matching_source_is_rejected(self):
        self.point.source_page = 99
        await self.db.commit()
        with self.assertRaises(service.AssessmentValidationError):
            await service.generate_quiz_set(self.db, self.request(), SETTINGS,
                _completion({"questions": [_generated_question()]}))
        self.assertEqual(await self.db.scalar(select(func.count(QuizQuestion.id))), 0)

    async def test_explicit_points_in_one_document_use_question_citations_for_attribution(self):
        self.point.source_page = 3
        other = KnowledgePoint(workspace_id=self.workspace.id, document_id=self.document.id,
            title="Circles", source_page=9)
        self.db.add(other)
        self.db.add(DocumentChunk(id="circles", workspace_id=self.workspace.id, document_id=self.document.id,
            source_file="geometry.pdf", page_num=9, heading="Circles", section_path=["Circles"],
            chunk_index=1, content="Circles are round.", tokenized_content="circles"))
        await self.db.commit()
        paper = await service.generate_quiz_set(self.db,
            self.request(knowledge_point_ids=[self.point.id, other.id], section_filters=[], count=2), SETTINGS,
            _completion({"questions": [_generated_question(), _generated_question(prompt="Are circles round?",
                options=["Yes", "No"], answer_payload="Yes", source_chunk_ids=["circles"])]}))
        questions = (await self.db.execute(select(QuizQuestion).where(QuizQuestion.quiz_set_id == paper.id)
            .order_by(QuizQuestion.position))).scalars().all()
        self.assertEqual([q.knowledge_point_id for q in questions], [self.point.id, other.id])

    async def test_multi_blank_structure_is_visible_without_answer_or_alternatives(self):
        _, question = await self.make_set()
        question.question_type = "fill_blank"
        question.answer_payload = [["Paris", "巴黎"], "France"]
        question.answer = "SECRET_REFERENCE"
        payload = service.serialize_question(question)
        self.assertEqual(payload.get("blank_count"), 2)
        self.assertNotIn("answer_payload", payload)
        self.assertNotIn("SECRET_REFERENCE", json.dumps(payload))
        self.assertNotIn("Paris", json.dumps(payload))

    async def test_older_retry_preserves_newer_mastery_and_latest_compatibility_answer(self):
        paper, question = await self.make_set()
        question.question_type = "short_answer"
        question.grading_rubric = {"key_points": ["three sides"]}
        await self.db.commit()
        async def answer(text, seconds, *, correct=None, redo=False):
            run = await service.create_quiz_run(self.db, paper.id, question_ids=[question.id] if redo else None)
            await service.start_quiz_run(self.db, run.id, now=NOW + timedelta(seconds=seconds))
            async def failed(**kwargs):
                raise RuntimeError("offline")
            return await service.submit_question(self.db, run.id, question.id, QuestionSubmitRequest(answer=text), SETTINGS,
                completion=failed if correct is None else _completion(evaluation(correct)),
                now=NOW + timedelta(seconds=seconds + 1), is_redo=redo)
        await answer("initial wrong", 0, correct=False)
        old = await answer("older pending", 5, redo=True)
        await answer("correct one", 10, correct=True, redo=True)
        newest = await answer("correct two", 15, correct=True, redo=True)
        await service.retry_grading(self.db, old.id, SETTINGS, _completion(evaluation(False)))
        record = (await self.db.execute(select(MistakeRecord))).scalar_one()
        self.assertEqual(record.mastery_status, "mastered")
        self.assertEqual(record.wrong_count, 2)
        self.assertEqual(record.redo_count, 3)
        self.assertEqual(record.consecutive_correct, 2)
        self.assertEqual(record.latest_attempt_id, newest.id)
        self.assertEqual(record.user_answer_snapshot, "correct two")
        self.assertEqual(question.last_answer, "correct two")
        self.assertIs(question.last_correct, True)
        self.assertEqual(question.attempts, 4)
        self.assertEqual(question.correct_attempts, 2)

    async def test_latest_failed_answer_has_no_stale_correctness(self):
        paper, question = await self.make_set()
        first = await service.create_quiz_run(self.db, paper.id)
        await service.start_quiz_run(self.db, first.id, now=NOW)
        await service.submit_question(self.db, first.id, question.id, QuestionSubmitRequest(answer="Three"), SETTINGS, now=NOW)
        question.question_type = "short_answer"
        question.grading_rubric = {"key_points": ["three sides"]}
        await self.db.commit()
        second = await service.create_quiz_run(self.db, paper.id)
        await service.start_quiz_run(self.db, second.id, now=NOW + timedelta(seconds=5))
        async def failed(**kwargs):
            raise RuntimeError("offline")
        await service.submit_question(self.db, second.id, question.id, QuestionSubmitRequest(answer="new pending"), SETTINGS,
            completion=failed, now=NOW + timedelta(seconds=6))
        self.assertEqual(question.last_answer, "new pending")
        self.assertIsNone(question.last_correct)

    async def test_retry_preserves_mastered_legacy_mistake_without_durable_redo_history(self):
        paper, question = await self.make_set()
        question.question_type = "short_answer"
        question.grading_rubric = {"key_points": ["three sides"]}
        record = MistakeRecord(question_id=question.id, workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id, wrong_count=3, redo_count=4, consecutive_correct=2,
            mastery_status="mastered", first_wrong_at=NOW - timedelta(days=4),
            last_wrong_at=NOW - timedelta(days=3), last_redone_at=NOW - timedelta(days=1),
            resolved_at=NOW - timedelta(days=1))
        self.db.add(record)
        await self.db.commit()
        run = await service.create_quiz_run(self.db, paper.id)
        await service.start_quiz_run(self.db, run.id, now=NOW)
        async def failed(**kwargs):
            raise RuntimeError("offline")
        attempt = await service.submit_question(self.db, run.id, question.id, QuestionSubmitRequest(answer="correct new answer"),
            SETTINGS, completion=failed, now=NOW + timedelta(seconds=1))
        await service.retry_grading(self.db, attempt.id, SETTINGS, _completion(evaluation(True)))
        await self.db.refresh(record)
        self.assertEqual(record.mastery_status, "mastered")
        self.assertEqual((record.wrong_count, record.redo_count, record.consecutive_correct), (3, 4, 2))
        self.assertEqual(record.last_wrong_at.replace(tzinfo=NOW.tzinfo), NOW - timedelta(days=3))
        self.assertEqual(record.resolved_at.replace(tzinfo=NOW.tzinfo), NOW - timedelta(days=1))

    async def test_recommendation_drafts_name_the_selected_point_and_review_is_global(self):
        from app.services.weakness_service import _recommended_actions
        # The action producer receives a real validated point, independent of score setup.
        actions = _recommended_actions(self.point, type("Score", (), {"total": 90})())
        for action in actions:
            query = parse_qs(urlsplit(action["path"]).query)
            if action["type"] in {"plain_explanation", "new_example"}:
                self.assertIn(self.point.title, query["prompt"][0])
            if action["type"] == "review":
                self.assertEqual(action["path"], "/review")


class FinalScoringFixTests(unittest.TestCase):
    def test_a_wrong_redo_counts_as_a_redo(self):
        from app.services.assessment_scoring import MistakeState, next_mistake_state
        state = next_mistake_state(MistakeState(wrong_count=1), correct=False, is_redo=True, now=NOW)
        self.assertEqual(state.redo_count, 1)
        self.assertEqual(state.last_redone_at, NOW)
        self.assertEqual(state.wrong_count, 2)

    def test_semantic_signs_operators_and_identifier_punctuation_remain_distinct(self):
        for expected, answer in [("-1", "1"), ("+1", "1"), ("C++", "C"), ("C#", "C"),
                                 ("50%", "50"), ("x!", "x"), (".5", "5"), ("[1]", "1")]:
            with self.subTest(expected=expected, answer=answer):
                self.assertFalse(grade_objective("fill_blank", [expected], [answer]).is_correct)
        self.assertTrue(grade_objective("fill_blank", ["Paris"], ["  PARIS。 "]).is_correct)


class FinalRecoveryFixTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = api_fixtures.AssessmentAPITests.asyncSetUp
    asyncTearDown = api_fixtures.AssessmentAPITests.asyncTearDown
    request = api_fixtures.AssessmentAPITests.request
    paper = api_fixtures.AssessmentAPITests.paper
    started = api_fixtures.AssessmentAPITests.started

    async def test_failed_redo_is_recoverable_from_filtered_list_and_retries_original_round(self):
        paper, question = await self.paper(kind="short_answer")
        record = MistakeRecord(question_id=question.id, workspace_id=self.workspace.id,
            knowledge_point_id=self.point.id, correct_answer_snapshot="Three")
        self.db.add(record)
        await self.db.commit()
        with patch("app.services.assessment_ai.call_completion", side_effect=RuntimeError("offline")):
            response = await self.request("POST", f"/mistakes/{record.id}/redo", json={"answer": "saved original answer"})
        self.assertEqual(response.status_code, 200, response.text)
        attempt = response.json()["attempt"]
        listing = (await self.request("GET", "/mistakes", params={"mastery_status": "unresolved"})).json()
        recovered = listing["items"][0].get("recoverable_redo_attempt")
        self.assertIsNotNone(recovered)
        self.assertEqual(recovered["id"], attempt["id"])
        self.assertEqual(recovered["user_answer"], "saved original answer")
        with patch("app.services.assessment_ai.call_completion", return_value=_response(evaluation(True))):
            retried = await self.request("POST", f"/attempts/{recovered['id']}/retry-grading")
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(await self.db.scalar(select(func.count(QuizRun.id))), 1)
        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 1)
        refreshed = (await self.request("GET", "/mistakes")).json()["items"][0]
        self.assertIsNone(refreshed.get("recoverable_redo_attempt"))
