"""Transactional orchestration contracts for phase-five assessments."""

from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register complete SQLAlchemy metadata
from app.config import Settings
from app.models.assessment import MistakeRecord, QuizAttempt, QuizRun, QuizSet
from app.models.base import Base
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.models.workspace import Workspace
from app.schemas.assessment import PaperSubmitRequest, QuestionSubmitRequest, QuizSetGenerateRequest
from app.services.assessment_service import (
    AssessmentScopeError,
    AssessmentStateError,
    create_quiz_run,
    generate_quiz_set,
    serialize_question,
    serialize_quiz_run,
    serialize_quiz_set,
    start_quiz_run,
    submit_paper,
    submit_question,
)


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
SETTINGS = Settings.model_construct(
    DEFAULT_LLM_PROVIDER="ollama",
    DEFAULT_LLM_MODEL="test-model",
    OLLAMA_BASE_URL="http://ollama.test",
)


def _response(payload: dict) -> object:
    message = type("Message", (), {"content": json.dumps(payload)})()
    return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()


def _completion(*payloads: dict):
    remaining = iter(payloads)

    async def complete(**_kwargs):
        return _response(next(remaining))

    return complete


def _generated_question(**overrides) -> dict:
    question = {
        "question_type": "single_choice",
        "prompt": "How many sides does a triangle have?",
        "options": ["Two", "Three"],
        "answer_payload": "Three",
        "explanation": "A triangle is a three-sided polygon.",
        "grading_rubric": {},
        "source_chunk_ids": ["chunk-1"],
        "difficulty": "medium",
    }
    question.update(overrides)
    return question


class AssessmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        self.workspace = Workspace(name="Geometry", slug="geometry")
        self.db.add(self.workspace)
        await self.db.flush()
        self.document = Document(
            workspace_id=self.workspace.id,
            filename="geometry.pdf",
            file_path="geometry.pdf",
            file_type="pdf",
            status="ready",
        )
        self.db.add(self.document)
        await self.db.flush()
        self.point = KnowledgePoint(
            workspace_id=self.workspace.id,
            document_id=self.document.id,
            title="Triangles",
            mastery=0.5,
            mastery_status="learning",
        )
        self.chunk = DocumentChunk(
            id="chunk-1",
            workspace_id=self.workspace.id,
            document_id=self.document.id,
            source_file=self.document.filename,
            page_num=3,
            heading="Foundations",
            section_path=["Geometry", "Foundations"],
            chunk_index=0,
            content="A triangle has three sides.",
            tokenized_content="triangle three sides",
        )
        self.db.add_all([self.point, self.chunk])
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def request(self, **overrides) -> QuizSetGenerateRequest:
        values = {
            "workspace_id": self.workspace.id,
            "document_ids": [self.document.id],
            "knowledge_point_ids": [self.point.id],
            "section_filters": ["Foundations"],
            "count": 1,
            "difficulty": "medium",
            "question_types": ["single_choice"],
            "strict_sources": True,
            "answer_mode": "sequential",
        }
        values.update(overrides)
        return QuizSetGenerateRequest(**values)

    async def make_set(self, *, answer_mode="sequential") -> tuple[QuizSet, QuizQuestion]:
        quiz_set = QuizSet(
            workspace_id=self.workspace.id,
            title="Triangles",
            document_ids=[self.document.id],
            knowledge_point_ids=[self.point.id],
            question_count=1,
            difficulty="medium",
            question_types=["single_choice"],
            strict_sources=True,
            answer_mode=answer_mode,
            duration_limit_seconds=60,
            status="ready",
        )
        self.db.add(quiz_set)
        await self.db.flush()
        question = QuizQuestion(
            workspace_id=self.workspace.id,
            quiz_set_id=quiz_set.id,
            document_id=self.document.id,
            knowledge_point_id=self.point.id,
            question_type="single_choice",
            prompt="How many sides?",
            options=["Two", "Three"],
            answer="Three",
            answer_payload="Three",
            explanation="Triangles have three sides.",
            source_snapshot=[{"chunk_id": self.chunk.id, "document_id": self.document.id}],
            strict_sources=True,
            generation_model="test-model",
            position=1,
        )
        self.db.add(question)
        await self.db.commit()
        return quiz_set, question

    async def add_question(
        self,
        quiz_set: QuizSet,
        *,
        position: int,
        question_type: str = "true_false",
    ) -> QuizQuestion:
        question = QuizQuestion(
            workspace_id=self.workspace.id,
            quiz_set_id=quiz_set.id,
            document_id=self.document.id,
            knowledge_point_id=self.point.id,
            question_type=question_type,
            prompt=f"Question {position}",
            options=["True", "False"] if question_type == "true_false" else None,
            answer="True",
            answer_payload="True",
            explanation="Because it is true.",
            grading_rubric={"key_points": ["true"]} if question_type == "short_answer" else {},
            source_snapshot=[{"chunk_id": self.chunk.id, "document_id": self.document.id}],
            position=position,
        )
        self.db.add(question)
        quiz_set.question_count = max(quiz_set.question_count, position)
        await self.db.commit()
        return question

    async def test_generation_validates_cross_scope_documents_before_calling_ai(self):
        other_workspace = Workspace(name="Other", slug="other")
        self.db.add(other_workspace)
        await self.db.flush()
        other_document = Document(
            workspace_id=other_workspace.id,
            filename="other.pdf",
            file_path="other.pdf",
            file_type="pdf",
            status="ready",
        )
        self.db.add(other_document)
        await self.db.commit()
        called = False

        async def must_not_run(**_kwargs):
            nonlocal called
            called = True
            raise AssertionError("AI must not run for invalid scope")

        with self.assertRaises(AssessmentScopeError):
            await generate_quiz_set(
                self.db,
                self.request(document_ids=[other_document.id], knowledge_point_ids=[], section_filters=[]),
                SETTINGS,
                must_not_run,
            )

        self.assertFalse(called)
        self.assertEqual((await self.db.scalar(select(func.count(QuizSet.id)))), 0)

    async def test_generation_persists_complete_paper_and_synchronizes_legacy_answers(self):
        request = self.request(
            count=2,
            question_types=["single_choice", "multiple_choice"],
        )
        paper = {
            "questions": [
                _generated_question(),
                _generated_question(
                    question_type="multiple_choice",
                    prompt="Which descriptions are true?",
                    options=["Three sides", "Three angles", "Four sides"],
                    answer_payload=["Three sides", "Three angles"],
                ),
            ]
        }

        quiz_set = await generate_quiz_set(self.db, request, SETTINGS, _completion(paper))
        questions = (
            await self.db.execute(
                select(QuizQuestion)
                .where(QuizQuestion.quiz_set_id == quiz_set.id)
                .order_by(QuizQuestion.position)
            )
        ).scalars().all()

        self.assertEqual(quiz_set.status, "ready")
        self.assertEqual(quiz_set.question_count, 2)
        self.assertEqual([question.position for question in questions], [1, 2])
        self.assertEqual(questions[0].answer, "Three")
        self.assertEqual(json.loads(questions[1].answer), ["Three sides", "Three angles"])
        self.assertEqual(questions[1].answer_payload, ["Three sides", "Three angles"])
        self.assertEqual(questions[0].knowledge_point_id, self.point.id)
        self.assertEqual(questions[0].document_id, self.document.id)

    async def test_generation_releases_write_transaction_while_waiting_for_ai(self):
        async def complete_without_open_transaction(**_kwargs):
            self.assertFalse(self.db.in_transaction())
            return _response({"questions": [_generated_question()]})

        generated = await generate_quiz_set(
            self.db,
            self.request(),
            SETTINGS,
            complete_without_open_transaction,
        )

        self.assertEqual(generated.status, "ready")

    async def test_failed_generation_persists_failed_set_without_partial_questions(self):
        async def unavailable(**_kwargs):
            raise RuntimeError("offline")

        with self.assertRaisesRegex(RuntimeError, "provider"):
            await generate_quiz_set(self.db, self.request(), SETTINGS, unavailable)

        quiz_set = (await self.db.execute(select(QuizSet))).scalar_one()
        self.assertEqual(quiz_set.status, "failed")
        self.assertIn("unavailable", quiz_set.generation_error.lower())
        self.assertEqual((await self.db.scalar(select(func.count(QuizQuestion.id)))), 0)

    async def test_retry_creates_a_new_run_without_overwriting_history(self):
        quiz_set, _ = await self.make_set()
        first_run = await create_quiz_run(self.db, quiz_set.id)
        retry = await create_quiz_run(self.db, quiz_set.id)

        self.assertEqual(first_run.round_number, 1)
        self.assertEqual(retry.round_number, 2)
        self.assertNotEqual(retry.id, first_run.id)
        self.assertEqual((await self.db.scalar(select(func.count(QuizRun.id)))), 2)

    async def test_resume_returns_latest_unsubmitted_run_and_start_is_idempotent(self):
        quiz_set, _ = await self.make_set()
        run = await create_quiz_run(self.db, quiz_set.id)

        resumed = await create_quiz_run(self.db, quiz_set.id, resume=True)
        first_start = await start_quiz_run(self.db, run.id, NOW)
        second_start = await start_quiz_run(self.db, run.id, NOW + timedelta(seconds=30))

        self.assertEqual(resumed.id, run.id)
        self.assertEqual(first_start.status, "in_progress")
        self.assertEqual(second_start.started_at, NOW)

    async def test_answers_are_hidden_until_sequential_reveal_or_paper_submission(self):
        quiz_set, question = await self.make_set()
        question.grading_rubric = {"key_points": ["three sides"]}
        question.source_snapshot = [{
            "chunk_id": self.chunk.id,
            "document_id": self.document.id,
            "source_file": self.document.filename,
            "page": 3,
            "section_path": ["Geometry", "Foundations"],
            "excerpt": "A triangle has three sides.",
        }]
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        hidden = serialize_quiz_set(quiz_set, questions=[question], run=run, attempts=[])
        hidden_question = hidden["questions"][0]
        self.assertNotIn("answer", hidden_question)
        self.assertNotIn("answer_payload", hidden_question)
        self.assertNotIn("grading_rubric", hidden_question)
        self.assertNotIn("explanation", hidden_question)
        self.assertEqual(
            hidden_question["source_snapshot"],
            [{
                "chunk_id": self.chunk.id,
                "document_id": self.document.id,
                "source_file": self.document.filename,
                "page": 3,
            }],
        )

        attempt = await submit_question(
            self.db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer="Three", duration_seconds=4),
            SETTINGS,
            now=NOW + timedelta(seconds=4),
        )
        revealed = serialize_quiz_set(quiz_set, questions=[question], run=run, attempts=[attempt])
        self.assertEqual(revealed["questions"][0]["answer_payload"], "Three")
        self.assertEqual(revealed["questions"][0]["answer"], "Three")

        paper_set, paper_question = await self.make_set(answer_mode="full_paper")
        paper_run = await create_quiz_run(self.db, paper_set.id)
        await start_quiz_run(self.db, paper_run.id, NOW)
        paper_attempt = QuizAttempt(
            quiz_set_id=paper_set.id,
            quiz_run_id=paper_run.id,
            question_id=paper_question.id,
            attempt_number=1,
            user_answer="Three",
            is_correct=True,
            score=1,
            max_score=1,
        )
        self.db.add(paper_attempt)
        await self.db.flush()
        still_hidden = serialize_quiz_set(
            paper_set,
            questions=[paper_question],
            run=paper_run,
            attempts=[paper_attempt],
        )
        self.assertNotIn("answer_payload", still_hidden["questions"][0])
        paper_run.status = "submitted"
        revealed_paper = serialize_quiz_set(
            paper_set,
            questions=[paper_question],
            run=paper_run,
            attempts=[paper_attempt],
        )
        self.assertEqual(revealed_paper["questions"][0]["answer_payload"], "Three")

    async def test_serializer_rejects_cross_scope_run_questions_and_attempts(self):
        quiz_set, question = await self.make_set()
        other_set, other_question = await self.make_set()
        run = await create_quiz_run(self.db, quiz_set.id)
        other_run = await create_quiz_run(self.db, other_set.id)
        cross_set_attempt = QuizAttempt(
            quiz_set_id=other_set.id,
            quiz_run_id=other_run.id,
            question_id=other_question.id,
            attempt_number=1,
            user_answer="Three",
            is_correct=True,
            score=1,
            max_score=1,
        )
        wrong_question_attempt = QuizAttempt(
            quiz_set_id=quiz_set.id,
            quiz_run_id=run.id,
            question_id=other_question.id,
            attempt_number=1,
            user_answer="Three",
            is_correct=True,
            score=1,
            max_score=1,
        )

        invalid_calls = [
            lambda: serialize_quiz_set(other_set, questions=[other_question], run=run),
            lambda: serialize_quiz_set(quiz_set, questions=[other_question], run=run),
            lambda: serialize_quiz_set(
                quiz_set,
                questions=[question],
                run=run,
                attempts=[cross_set_attempt],
            ),
            lambda: serialize_question(question, attempt=cross_set_attempt),
            lambda: serialize_quiz_run(
                run,
                quiz_set=quiz_set,
                questions=[other_question],
            ),
            lambda: serialize_quiz_run(
                run,
                questions=[question],
                attempts=[wrong_question_attempt],
            ),
        ]
        for invalid_call in invalid_calls:
            with self.subTest(call=invalid_call):
                with self.assertRaises(AssessmentScopeError):
                    invalid_call()

    async def test_retry_round_does_not_reveal_from_an_older_run_attempt(self):
        quiz_set, question = await self.make_set()
        first_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, first_run.id, NOW)
        old_attempt = await submit_question(
            self.db,
            first_run.id,
            question.id,
            QuestionSubmitRequest(answer="Three"),
            SETTINGS,
            now=NOW,
        )
        retry = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, retry.id, NOW + timedelta(seconds=1))

        serialized = serialize_quiz_set(
            quiz_set,
            questions=[question],
            run=retry,
            attempts=[old_attempt],
        )

        self.assertNotIn("answer", serialized["questions"][0])
        self.assertNotIn("answer_payload", serialized["questions"][0])
        self.assertNotIn("attempt", serialized["questions"][0])

    async def test_wrong_submission_creates_attempt_mistake_and_updates_compatibility_fields(self):
        quiz_set, question = await self.make_set()
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        attempt = await submit_question(
            self.db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer="Two", duration_seconds=12),
            SETTINGS,
            now=NOW + timedelta(seconds=12),
        )
        mistake = (await self.db.execute(select(MistakeRecord))).scalar_one()
        activity = (await self.db.execute(select(StudyActivity))).scalar_one()

        self.assertFalse(attempt.is_correct)
        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(mistake.wrong_count, 1)
        self.assertEqual(mistake.latest_attempt_id, attempt.id)
        self.assertEqual(question.attempts, 1)
        self.assertEqual(question.correct_attempts, 0)
        self.assertEqual(question.last_answer, "Two")
        self.assertFalse(question.last_correct)
        self.assertEqual(self.point.mastery, 0.42)
        self.assertEqual(self.point.mastery_status, "learning")
        self.assertEqual(activity.duration_seconds, 12)
        self.assertEqual(run.graded_count, 1)
        self.assertEqual(run.max_score, 1)

    async def test_same_run_question_can_only_be_submitted_once(self):
        quiz_set, question = await self.make_set()
        await self.add_question(quiz_set, position=2)
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        await submit_question(
            self.db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer="Two", duration_seconds=4),
            SETTINGS,
            now=NOW + timedelta(seconds=4),
        )
        with self.assertRaises(AssessmentStateError):
            await submit_question(
                self.db,
                run.id,
                question.id,
                QuestionSubmitRequest(answer="Three", duration_seconds=5),
                SETTINGS,
                now=NOW + timedelta(seconds=5),
            )

        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 1)
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 1)
        await self.db.refresh(question)
        self.assertEqual(question.attempts, 1)
        self.assertEqual(question.correct_attempts, 0)

    async def test_concurrent_duplicate_submission_has_one_persisted_winner(self):
        quiz_set, question = await self.make_set()
        await self.add_question(quiz_set, position=2)
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)
        await self.db.commit()

        async def submit_once(answer: str):
            async with self.sessions() as session:
                return await submit_question(
                    session,
                    run.id,
                    question.id,
                    QuestionSubmitRequest(answer=answer, duration_seconds=4),
                    SETTINGS,
                    now=NOW + timedelta(seconds=4),
                )

        results = await asyncio.gather(submit_once("Two"), submit_once("Three"), return_exceptions=True)

        self.assertEqual(sum(isinstance(result, QuizAttempt) for result in results), 1)
        self.assertEqual(sum(isinstance(result, AssessmentStateError) for result in results), 1)
        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 1)
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id))), 1)

    async def test_concurrent_round_creation_is_monotonic_without_integrity_errors(self):
        quiz_set, _ = await self.make_set()

        async def create_once():
            async with self.sessions() as session:
                return await create_quiz_run(session, quiz_set.id)

        results = await asyncio.gather(create_once(), create_once(), return_exceptions=True)

        self.assertTrue(all(isinstance(result, QuizRun) for result in results), results)
        self.assertEqual(sorted(result.round_number for result in results), [1, 2])

    async def test_concurrent_runs_update_one_mistake_and_question_counters_without_lost_writes(self):
        quiz_set, question = await self.make_set()
        first_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, first_run.id, NOW)
        second_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, second_run.id, NOW)
        await self.db.commit()

        async def submit_wrong(run_id: str):
            async with self.sessions() as session:
                return await submit_question(
                    session,
                    run_id,
                    question.id,
                    QuestionSubmitRequest(answer="Two", duration_seconds=1),
                    SETTINGS,
                    now=NOW + timedelta(seconds=1),
                )

        results = await asyncio.gather(
            submit_wrong(first_run.id),
            submit_wrong(second_run.id),
            return_exceptions=True,
        )

        self.assertTrue(all(isinstance(result, QuizAttempt) for result in results), results)
        async with self.sessions() as verifier:
            persisted_question = await verifier.get(QuizQuestion, question.id)
            persisted_point = await verifier.get(KnowledgePoint, self.point.id)
            mistake = (await verifier.execute(select(MistakeRecord))).scalar_one()
            self.assertEqual(mistake.wrong_count, 2)
            self.assertEqual(persisted_question.attempts, 2)
            self.assertEqual(persisted_question.correct_attempts, 0)
            self.assertEqual(persisted_point.mastery, 0.34)
            self.assertEqual(await verifier.scalar(select(func.count(StudyActivity.id))), 2)

    async def test_question_duration_cannot_exceed_server_elapsed_or_remaining_time(self):
        quiz_set, first = await self.make_set()
        second = await self.add_question(quiz_set, position=2)
        await self.add_question(quiz_set, position=3)
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        first_attempt = await submit_question(
            self.db,
            run.id,
            first.id,
            QuestionSubmitRequest(answer="Three", duration_seconds=999),
            SETTINGS,
            now=NOW + timedelta(seconds=12),
        )
        second_attempt = await submit_question(
            self.db,
            run.id,
            second.id,
            QuestionSubmitRequest(answer="True", duration_seconds=999),
            SETTINGS,
            now=NOW + timedelta(seconds=15),
        )
        activities = (
            await self.db.execute(select(StudyActivity).order_by(StudyActivity.created_at))
        ).scalars().all()

        self.assertEqual(first_attempt.duration_seconds, 12)
        self.assertEqual(second_attempt.duration_seconds, 3)
        self.assertEqual([activity.duration_seconds for activity in activities], [12, 3])
        self.assertLessEqual(sum(activity.duration_seconds for activity in activities), 15)

    async def test_two_correct_redos_master_the_existing_mistake(self):
        quiz_set, question = await self.make_set()
        first_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, first_run.id, NOW)
        await submit_question(
            self.db,
            first_run.id,
            question.id,
            QuestionSubmitRequest(answer="Two"),
            SETTINGS,
            now=NOW,
        )
        second_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, second_run.id, NOW + timedelta(seconds=1))
        await submit_question(
            self.db,
            second_run.id,
            question.id,
            QuestionSubmitRequest(answer="Three"),
            SETTINGS,
            now=NOW + timedelta(seconds=1),
            is_redo=True,
        )
        third_run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, third_run.id, NOW + timedelta(seconds=2))
        await submit_question(
            self.db,
            third_run.id,
            question.id,
            QuestionSubmitRequest(answer="Three"),
            SETTINGS,
            now=NOW + timedelta(seconds=2),
            is_redo=True,
        )

        mistake = (await self.db.execute(select(MistakeRecord))).scalar_one()
        self.assertEqual(mistake.mastery_status, "mastered")
        self.assertEqual(mistake.redo_count, 2)
        self.assertEqual(mistake.consecutive_correct, 2)
        self.assertEqual(
            (await self.db.scalar(select(func.count(QuizAttempt.id)))),
            3,
        )

    async def test_subjective_grading_failure_preserves_attempt_without_changing_accuracy(self):
        quiz_set, question = await self.make_set()
        question.question_type = "short_answer"
        question.options = None
        question.answer = "A triangle has three sides."
        question.answer_payload = "A triangle has three sides."
        question.grading_rubric = {"key_points": ["three sides"]}
        await self.db.commit()
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        async def unavailable(**_kwargs):
            raise RuntimeError("offline")

        attempt = await submit_question(
            self.db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer="My explanation", duration_seconds=9),
            SETTINGS,
            unavailable,
            now=NOW + timedelta(seconds=9),
        )

        self.assertEqual(attempt.user_answer, "My explanation")
        self.assertEqual(attempt.evaluation_status, "grading_failed")
        self.assertIsNone(attempt.is_correct)
        self.assertIsNone(attempt.score)
        self.assertEqual((await self.db.scalar(select(func.count(MistakeRecord.id)))), 0)
        self.assertEqual(question.attempts, 0)
        self.assertEqual(question.correct_attempts, 0)
        self.assertEqual(question.last_answer, "My explanation")
        self.assertIsNone(question.last_correct)
        self.assertEqual(run.graded_count, 0)
        self.assertEqual(run.correct_count, 0)
        self.assertEqual(run.score, 0)
        self.assertEqual(run.max_score, 0)

    async def test_subjective_grading_waits_without_a_write_transaction(self):
        quiz_set, question = await self.make_set()
        question.question_type = "short_answer"
        question.options = None
        question.answer_payload = "A triangle has three sides."
        question.grading_rubric = {"key_points": ["three sides"]}
        await self.db.commit()
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        async def complete_without_open_transaction(**_kwargs):
            self.assertFalse(self.db.in_transaction())
            return _response({
                "score": 1,
                "max_score": 1,
                "is_correct": True,
                "feedback": "Correct",
                "error_reason": None,
                "matched_points": ["three sides"],
                "missing_points": [],
            })

        attempt = await submit_question(
            self.db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer="It has three sides."),
            SETTINGS,
            complete_without_open_transaction,
            now=NOW + timedelta(seconds=2),
        )

        self.assertEqual(attempt.evaluation_status, "graded")

    async def test_paper_collects_all_ai_grades_before_persisting_and_revalidates_run(self):
        quiz_set, first = await self.make_set(answer_mode="full_paper")
        first.question_type = "short_answer"
        first.options = None
        first.grading_rubric = {"key_points": ["three sides"]}
        second = await self.add_question(quiz_set, position=2, question_type="short_answer")
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)
        await self.db.commit()
        completion_count = 0

        async def complete_then_invalidate(**_kwargs):
            nonlocal completion_count
            completion_count += 1
            self.assertFalse(self.db.in_transaction())
            async with self.sessions() as other:
                self.assertEqual(await other.scalar(select(func.count(QuizAttempt.id))), 0)
                if completion_count == 2:
                    persisted_run = await other.get(QuizRun, run.id)
                    persisted_run.status = "submitted"
                    await other.commit()
            return _response({
                "score": 1,
                "max_score": 1,
                "is_correct": True,
                "feedback": "Correct",
                "error_reason": None,
                "matched_points": ["true"],
                "missing_points": [],
            })

        with self.assertRaises(AssessmentStateError):
            await submit_paper(
                self.db,
                run.id,
                {first.id: "Three sides", second.id: "True"},
                SETTINGS,
                complete_then_invalidate,
                now=NOW + timedelta(seconds=5),
            )

        self.assertEqual(completion_count, 2)
        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 0)

    async def test_full_paper_grades_supplied_answers_and_uses_server_elapsed_time(self):
        quiz_set, question = await self.make_set(answer_mode="full_paper")
        second = QuizQuestion(
            workspace_id=self.workspace.id,
            quiz_set_id=quiz_set.id,
            document_id=self.document.id,
            knowledge_point_id=self.point.id,
            question_type="true_false",
            prompt="A triangle has four sides.",
            options=["True", "False"],
            answer="False",
            answer_payload="False",
            explanation="It has three sides.",
            source_snapshot=[],
            position=2,
        )
        self.db.add(second)
        quiz_set.question_count = 2
        await self.db.commit()
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        submitted = await submit_paper(
            self.db,
            run.id,
            PaperSubmitRequest(answers={question.id: "Three"}, duration_seconds=1),
            SETTINGS,
            now=NOW + timedelta(seconds=70),
        )

        self.assertEqual(submitted.status, "submitted")
        self.assertEqual(submitted.elapsed_seconds, 60)
        self.assertEqual(submitted.graded_count, 1)
        self.assertEqual(submitted.correct_count, 1)
        self.assertEqual(submitted.score, 1)
        self.assertEqual(submitted.max_score, 1)
        attempts = (await self.db.execute(select(QuizAttempt))).scalars().all()
        self.assertEqual([attempt.question_id for attempt in attempts], [question.id])

    async def test_server_timer_survives_sqlite_timestamp_reload(self):
        quiz_set, question = await self.make_set(answer_mode="full_paper")
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)
        run_id = run.id
        question_id = question.id
        await self.db.commit()
        await self.db.close()
        self.db = self.sessions()

        submitted = await submit_paper(
            self.db,
            run_id,
            {question_id: "Three"},
            SETTINGS,
            now=NOW + timedelta(seconds=12),
        )

        self.assertEqual(submitted.elapsed_seconds, 12)

    async def test_submission_rejects_question_from_another_quiz_set(self):
        quiz_set, _ = await self.make_set()
        other_set, other_question = await self.make_set()
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        with self.assertRaises(AssessmentScopeError):
            await submit_question(
                self.db,
                run.id,
                other_question.id,
                QuestionSubmitRequest(answer="Three"),
                SETTINGS,
                now=NOW,
            )
        self.assertNotEqual(other_set.id, quiz_set.id)

    async def test_cannot_submit_before_start_or_after_submission(self):
        quiz_set, question = await self.make_set()
        run = await create_quiz_run(self.db, quiz_set.id)
        with self.assertRaises(AssessmentStateError):
            await submit_question(
                self.db,
                run.id,
                question.id,
                QuestionSubmitRequest(answer="Three"),
                SETTINGS,
                now=NOW,
            )

        await start_quiz_run(self.db, run.id, NOW)
        run.status = "submitted"
        await self.db.flush()
        with self.assertRaises(AssessmentStateError):
            await submit_question(
                self.db,
                run.id,
                question.id,
                QuestionSubmitRequest(answer="Three"),
                SETTINGS,
                now=NOW,
            )

    async def test_full_paper_rejects_per_question_submission(self):
        quiz_set, question = await self.make_set(answer_mode="full_paper")
        run = await create_quiz_run(self.db, quiz_set.id)
        await start_quiz_run(self.db, run.id, NOW)

        with self.assertRaises(AssessmentStateError):
            await submit_question(
                self.db,
                run.id,
                question.id,
                QuestionSubmitRequest(answer="Three"),
                SETTINGS,
                now=NOW,
            )

        self.assertEqual((await self.db.scalar(select(func.count(QuizAttempt.id)))), 0)


if __name__ == "__main__":
    unittest.main()
