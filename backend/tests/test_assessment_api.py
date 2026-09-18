"""HTTP contracts exercise real grading/persistence with only the provider replaced."""
import asyncio
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_db, get_settings
from app.main import app
from app.models.base import Base
from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt, QuizRun, QuizSet
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.models.user import User
from tests.support import create_user, create_workspace
from app.models.workspace import Workspace
from app.models.document import Document
from app.models.chat import DocumentChunk
from app.config import Settings
from app.services import assessment_service as service
from app.schemas.assessment import QuestionSubmitRequest
from tests.test_assessment_service import SETTINGS, _completion, _generated_question


class AssessmentAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(
            self.db, self.user, name="Test", slug="api-test"
        )
        self.point = KnowledgePoint(workspace_id=self.workspace.id, title="Triangles", mastery=0.5)
        self.db.add(self.point)
        await self.db.commit()

        async def database():
            yield self.db
            await self.db.commit()
        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_settings] = lambda: SETTINGS
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def request(self, method, path, **kwargs):
        return await self.client.request(method, "/api/learning" + path, **kwargs)

    async def paper(self, mode="sequential", kind="single_choice"):
        paper = QuizSet(workspace_id=self.workspace.id, title="Paper", question_count=1,
                        status="ready", answer_mode=mode, question_types=[kind])
        self.db.add(paper)
        await self.db.flush()
        question = QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=paper.id,
            knowledge_point_id=self.point.id, question_type=kind, prompt="How many sides?",
            options=["Two", "Three"], answer="Three", answer_payload="Three",
            explanation="Secret explanation", grading_rubric={"key_points": ["three sides"]})
        self.db.add(question)
        await self.db.commit()
        return paper, question

    async def started(self, paper):
        response = await self.request("POST", f"/quiz-sets/{paper.id}/runs")
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()
        response = await self.request("POST", f"/quiz-runs/{run['id']}/start")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_phase_five_routes_are_registered(self):
        paths = {route.path for route in app.routes}
        for path in ["/quiz-sets", "/quiz-sets/generate", "/quiz-sets/{quiz_set_id}", "/quiz-sets/{quiz_set_id}/runs",
                     "/quiz-runs/{run_id}/start", "/quiz-runs/{run_id}/questions/{question_id}/submit",
                     "/quiz-runs/{run_id}/submit", "/quiz-runs/{run_id}/retry",
                     "/attempts/{attempt_id}/retry-grading", "/mistakes", "/mistakes/{mistake_id}/redo",
                     "/weak-knowledge", "/weak-knowledge/recalculate", "/tasks", "/tasks/{task_id}/complete"]:
            self.assertIn("/api/learning" + path, paths)

    async def test_quiz_history_splits_answer_modes_and_reports_run_progress(self):
        document = Document(workspace_id=self.workspace.id, filename="geometry.pdf", file_path="geometry.pdf",
            file_type="pdf", status="ready")
        self.db.add(document)
        await self.db.flush()
        sequential = QuizSet(workspace_id=self.workspace.id, title="逐题卷", question_count=1, status="ready",
            answer_mode="sequential", question_types=["single_choice"], document_ids=[document.id],
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        full_paper = QuizSet(workspace_id=self.workspace.id, title="整卷卷", question_count=2, status="ready",
            answer_mode="full_paper", question_types=["single_choice", "short_answer"],
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc))
        self.db.add_all([sequential, full_paper])
        await self.db.flush()
        question = QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=sequential.id, document_id=document.id,
            knowledge_point_id=self.point.id, question_type="single_choice", prompt="How many sides?",
            options=["Two", "Three"], answer="Three", answer_payload="Three", explanation="Three sides.",
            grading_rubric={})
        self.db.add(question)
        await self.db.commit()

        listing = (await self.request("GET", "/quiz-sets", params={"workspace_id": self.workspace.id})).json()
        self.assertEqual(listing["total"], 2)
        self.assertEqual(listing["mode_counts"], {"sequential": 1, "full_paper": 1})
        self.assertEqual([item["id"] for item in listing["items"]], [full_paper.id, sequential.id])
        newest, older = listing["items"]
        self.assertEqual(newest["answer_mode"], "full_paper")
        self.assertEqual(newest["question_types"], ["single_choice", "short_answer"])
        self.assertIsNone(newest["run"])
        self.assertEqual(older["documents"], [{"id": document.id, "filename": "geometry.pdf"}])
        self.assertIsNone(older["run"])

        run = await self.started(sequential)
        filtered = (await self.request("GET", "/quiz-sets", params={
            "workspace_id": self.workspace.id, "answer_mode": "sequential",
        })).json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["mode_counts"], {"sequential": 1, "full_paper": 1})
        active = filtered["items"][0]
        self.assertEqual(active["id"], sequential.id)
        self.assertEqual(active["round_count"], 1)
        self.assertEqual(active["run"]["status"], "in_progress")
        self.assertEqual(active["run"]["answered_count"], 0)
        self.assertEqual(active["run"]["total_questions"], 1)

        submit = await self.request("POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit",
                                    json={"answer": "Three"})
        self.assertEqual(submit.status_code, 200, submit.text)
        answered = (await self.request("GET", "/quiz-sets", params={
            "workspace_id": self.workspace.id, "answer_mode": "sequential",
        })).json()["items"][0]["run"]
        self.assertEqual(answered["status"], "submitted")
        self.assertEqual(answered["answered_count"], 1)
        self.assertEqual(answered["score"], 1)
        self.assertEqual(answered["max_score"], 1)

    async def test_quiz_history_filters_by_document_and_hides_legacy_carriers(self):
        document = Document(workspace_id=self.workspace.id, filename="geometry.pdf", file_path="geometry.pdf",
            file_type="pdf", status="ready")
        self.db.add(document)
        await self.db.flush()
        generated = QuizSet(workspace_id=self.workspace.id, title="几何卷", question_count=1, status="ready",
            answer_mode="sequential", question_types=["single_choice"], document_ids=[document.id])
        legacy = QuizSet(workspace_id=self.workspace.id, title="Legacy practice", question_count=1, status="ready",
            answer_mode="sequential", question_types=["single_choice"], generation_model="legacy")
        self.db.add_all([generated, legacy])
        await self.db.flush()
        self.db.add(QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=generated.id, document_id=document.id,
            question_type="single_choice", prompt="Sides?", options=["Two", "Three"], answer="Three",
            answer_payload="Three", explanation="Three sides.", grading_rubric={}))
        await self.db.commit()

        scoped = (await self.request("GET", "/quiz-sets", params={"document_id": document.id})).json()
        self.assertEqual([item["id"] for item in scoped["items"]], [generated.id])
        self.assertEqual(scoped["total"], 1)
        unscoped = (await self.request("GET", "/quiz-sets", params={"workspace_id": self.workspace.id})).json()
        self.assertNotIn(legacy.id, [item["id"] for item in unscoped["items"]])

    async def test_quiz_history_is_scoped_to_owned_workspaces(self):
        other_user = await create_user(self.db)
        other_workspace = await create_workspace(self.db, other_user, name="Other", slug="other-ws")
        foreign = QuizSet(workspace_id=other_workspace.id, title="别人的卷", question_count=1, status="ready",
            answer_mode="full_paper", question_types=["single_choice"])
        self.db.add(foreign)
        await self.db.commit()

        listing = (await self.request("GET", "/quiz-sets")).json()
        self.assertEqual(listing["items"], [])
        self.assertEqual(listing["total"], 0)
        self.assertEqual(listing["mode_counts"], {"sequential": 0, "full_paper": 0})
        forbidden = await self.request("GET", "/quiz-sets", params={"workspace_id": other_workspace.id})
        self.assertEqual(forbidden.status_code, 404)
        self.assertEqual((await self.request("GET", "/quiz-sets", params={"limit": 0})).status_code, 422)

    async def test_unsubmitted_paper_and_legacy_list_hide_result_material(self):
        paper, question = await self.paper("full_paper")
        question.last_answer = "old answer"
        await self.db.commit()
        response = await self.request("GET", f"/quiz-sets/{paper.id}")
        self.assertEqual(response.status_code, 200, response.text)
        for key in ["answer", "answer_payload", "grading_rubric", "explanation", "last_answer"]:
            self.assertNotIn(key, response.json()["questions"][0])
            self.assertNotIn(key, (await self.request("GET", "/quizzes")).json()[0])
        await self.started(paper)
        active = await self.request("GET", "/quizzes")
        for key in ["answer", "answer_payload", "grading_rubric", "explanation", "last_answer", "last_correct"]:
            self.assertNotIn(key, active.json()[0])

    async def test_sequential_submit_resume_retry_and_answer_hiding(self):
        paper, question = await self.paper()
        run = await self.started(paper)
        again = (await self.request("POST", f"/quiz-runs/{run['id']}/start")).json()
        self.assertEqual(again["started_at"], run["started_at"])
        resumed = await self.request("POST", f"/quiz-sets/{paper.id}/runs", json={"resume_unsubmitted": True})
        self.assertEqual(resumed.json()["id"], run["id"])
        result = await self.request("POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit", json={"answer": "Three"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["attempt"]["is_correct"])
        self.assertEqual(result.json()["run"]["status"], "submitted")
        self.assertEqual((await self.request("GET", f"/quiz-sets/{paper.id}")).json()["questions"][0]["answer_payload"], "Three")
        duplicate = await self.request("POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit", json={"answer": "Two"})
        self.assertEqual(duplicate.status_code, 409)
        retry = await self.request("POST", f"/quiz-runs/{run['id']}/retry")
        self.assertEqual(retry.json()["round_number"], 2)
        self.assertNotIn("answer_payload", (await self.request("GET", f"/quiz-sets/{paper.id}")).json()["questions"][0])

    async def test_full_paper_and_invalid_http_inputs(self):
        paper, question = await self.paper("full_paper")
        run = await self.started(paper)
        url = f"/quiz-runs/{run['id']}/submit"
        self.assertEqual((await self.request("POST", url, json={"answers": {"foreign": "x"}})).status_code, 400)
        self.assertEqual((await self.request("POST", url, json={"duration_seconds": -1})).status_code, 422)
        self.assertEqual((await self.request("GET", "/quiz-sets/missing")).status_code, 404)
        response = await self.request("POST", url, json={"answers": {question.id: "Two"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["correct_count"], 0)
        self.assertEqual(response.json()["quiz_set"]["questions"][0]["answer_payload"], "Three")

    async def test_mistake_filters_redo_and_mastery(self):
        paper, question = await self.paper()
        run = await self.started(paper)
        await self.request("POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit", json={"answer": "Two"})
        listing = await self.request("GET", "/mistakes", params={"workspace_id": self.workspace.id, "knowledge_point_id": self.point.id, "mastery_status": "unresolved", "limit": 1})
        self.assertEqual(listing.status_code, 200, listing.text)
        data = listing.json()
        self.assertEqual(data["total"], 1)
        mistake = data["items"][0]
        self.assertEqual(mistake["knowledge_point_title"], "Triangles")
        self.assertIn("source_label", mistake)
        for expected in ["improving", "mastered"]:
            response = await self.request("POST", f"/mistakes/{mistake['id']}/redo", json={"answer": "Three"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["mistake"]["mastery_status"], expected)
        self.assertEqual(response.json()["mistake"]["redo_count"], 2)
        self.assertEqual((await self.request("GET", "/mistakes", params={"offset": 1})).json()["items"], [])

    async def test_task_completion_is_idempotent_and_recalculates(self):
        task = LearningTask(workspace_id=self.workspace.id, knowledge_point_id=self.point.id, task_type="review", title="Review", due_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.db.add(task)
        await self.db.commit()
        listing = await self.request("GET", "/tasks", params={"due_before": "2026-09-02T00:00:00Z", "status": "pending"})
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertEqual(listing.json()["total"], 1)
        first = await self.request("POST", f"/tasks/{task.id}/complete")
        self.assertEqual(first.status_code, 200, first.text)
        second = await self.request("POST", f"/tasks/{task.id}/complete")
        self.assertEqual(first.json()["completed_at"], second.json()["completed_at"])
        self.assertEqual(await self.db.scalar(select(func.count(StudyActivity.id)).where(
            StudyActivity.activity_type == "learning_task"
        )), 1)
        state = (await self.request("GET", "/weak-knowledge")).json()["items"][0]
        self.assertEqual(state["recency_component"], 0)
        self.assertIn("evidence", state)
        self.assertIn("recommended_actions", state)
        recalculated = await self.request("POST", "/weak-knowledge/recalculate", json={"workspace_id": self.workspace.id})
        self.assertEqual(recalculated.status_code, 200, recalculated.text)

    async def test_export_on_empty_profile_is_read_only_and_retains_old_fields(self):
        response = await self.request("GET", "/export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(await self.db.scalar(select(func.count(User.id))), 1)
        for field in ["quiz_sets", "quiz_runs", "quiz_attempts", "mistakes", "weak_knowledge", "learning_tasks", "profile", "quizzes", "flashcards", "activities"]:
            self.assertIn(field, response.json())

    async def test_legacy_orphan_submission_creates_shared_attempt_and_mistake(self):
        question = QuizQuestion(workspace_id=self.workspace.id, question_type="choice", prompt="Pick", answer="A", options=["A", "B"])
        self.db.add(question)
        await self.db.commit()
        response = await self.request("POST", f"/quizzes/{question.id}/submit", json={"answer": "B"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["correct"])
        self.assertEqual(response.json()["question"]["question_type"], "choice")
        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 1)
        self.assertEqual(await self.db.scalar(select(func.count(MistakeRecord.id))), 1)
        self.assertEqual(response.json()["question"]["id"], question.id)

    async def test_bridged_legacy_history_remains_visible_without_ordinary_run(self):
        question = QuizQuestion(workspace_id=self.workspace.id, question_type="choice", prompt="Pick",
            answer="A", options=["A", "B"], explanation="Legacy explanation", last_answer="B", last_correct=False)
        self.db.add(question)
        await self.db.commit()
        before = (await self.request("GET", "/quizzes", params={"wrong_only": True})).json()[0]
        self.assertEqual(before["explanation"], "Legacy explanation")
        self.assertEqual(before["last_answer"], "B")
        self.assertIs(before["last_correct"], False)
        response = await self.request("POST", f"/quizzes/{question.id}/submit", json={"answer": "B"})
        self.assertEqual(response.status_code, 200, response.text)
        history = (await self.request("GET", "/quizzes", params={"wrong_only": True})).json()[0]
        self.assertEqual(history.get("explanation"), "Legacy explanation")
        self.assertEqual(history.get("last_answer"), "B")
        self.assertIs(history.get("last_correct"), False)
        self.assertNotIn("answer", history)  # Preserve the old list contract, not a new answer reveal.
        # An explicit ordinary round must still govern visibility, including for
        # an attached legacy set, rather than exempting its questions forever.
        run = await self.request("POST", f"/quiz-sets/{question.quiz_set_id}/runs", json={"answer_mode": "full_paper"})
        self.assertEqual(run.status_code, 200, run.text)
        hidden = (await self.request("GET", "/quizzes")).json()[0]
        for key in ("explanation", "last_answer", "last_correct", "answer"):
            self.assertNotIn(key, hidden)

    async def test_task_due_filters_normalize_offset_bounds_and_remain_inclusive(self):
        self.db.add(LearningTask(workspace_id=self.workspace.id, task_type="review", title="Noon UTC",
            due_at=datetime(2026, 9, 1, 12, tzinfo=timezone.utc)))
        await self.db.commit()
        cases = [
            ("due_before", "2026-09-01T08:00:00Z", 0),
            ("due_before", "2026-09-01T16:00:00+08:00", 0),
            ("due_after", "2026-09-01T16:00:00Z", 0),
            ("due_after", "2026-09-02T00:00:00+08:00", 0),
            ("due_before", "2026-09-01T12:00:00Z", 1),
            ("due_before", "2026-09-01T20:00:00+08:00", 1),
            ("due_after", "2026-09-01T12:00:00Z", 1),
            ("due_after", "2026-09-01T20:00:00+08:00", 1),
            ("due_after", "2026-09-01T08:00:00Z", 1),
            ("due_after", "2026-09-01T16:00:00+08:00", 1),
        ]
        for parameter, bound, expected in cases:
            with self.subTest(parameter=parameter, bound=bound):
                response = await self.request("GET", "/tasks", params={parameter: bound})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["total"], expected)

    async def test_retry_grading_preserves_answer_and_applies_side_effects_once(self):
        paper, question = await self.paper(kind="short_answer")
        run = await self.started(paper)
        async def unavailable(**kwargs):
            raise RuntimeError("provider down")
        with patch("litellm.acompletion", unavailable):
            response = await self.request("POST", f"/quiz-runs/{run['id']}/questions/{question.id}/submit", json={"answer": "three sides"})
        self.assertEqual(response.status_code, 200, response.text)
        attempt = response.json()["attempt"]
        self.assertEqual(attempt["evaluation_status"], "grading_failed")
        self.assertEqual(question.attempts, 0)
        evaluation = {"score": 1, "max_score": 1, "is_correct": True, "feedback": "Correct", "matched_points": ["three sides"], "missing_points": [], "error_reason": None}
        with patch("litellm.acompletion", _completion(evaluation)):
            retry = await self.request("POST", f"/attempts/{attempt['id']}/retry-grading")
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["attempt"]["user_answer"], "three sides")
        self.assertEqual(question.attempts, 1)
        self.assertEqual(self.point.mastery, 0.62)
        self.assertEqual((await self.request("POST", f"/attempts/{attempt['id']}/retry-grading")).status_code, 409)
        self.assertEqual(await self.db.scalar(select(func.count(QuizAttempt.id))), 1)

    async def test_legacy_point_question_has_structured_fields_and_source(self):
        response = await self.request("POST", f"/knowledge-points/{self.point.id}/quiz")
        self.assertEqual(response.status_code, 201, response.text)
        question = await self.db.get(QuizQuestion, response.json()["id"])
        self.assertIsNotNone(question.answer_payload)
        self.assertIsNotNone(question.grading_rubric)
        self.assertEqual(question.source_snapshot[0]["heading"], self.point.source_heading)

    async def test_generate_provider_status_mapping_and_atomic_failed_sets(self):
        document = Document(workspace_id=self.workspace.id, filename="geometry.pdf", file_path="x", file_type="pdf", status="ready")
        self.db.add(document)
        await self.db.flush()
        self.db.add(DocumentChunk(id="chunk-1", workspace_id=self.workspace.id, document_id=document.id,
            source_file="geometry.pdf", chunk_index=0, content="A triangle has three sides.", tokenized_content="triangle"))
        await self.db.commit()
        request = {"workspace_id": self.workspace.id, "document_ids": [document.id], "count": 1}
        app.dependency_overrides[get_settings] = lambda: Settings.model_construct(DEFAULT_LLM_PROVIDER="", DEFAULT_LLM_MODEL="")
        response = await self.request("POST", "/quiz-sets/generate", json=request)
        self.assertEqual(response.status_code, 409, response.text)
        app.dependency_overrides[get_settings] = lambda: SETTINGS
        async def unavailable(**kwargs):
            raise RuntimeError("provider down")
        with patch("litellm.acompletion", unavailable):
            response = await self.request("POST", "/quiz-sets/generate", json=request)
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(await self.db.scalar(select(func.count(QuizQuestion.id))), 0)
        with patch("litellm.acompletion", _completion({"questions": [_generated_question()]})):
            response = await self.request("POST", "/quiz-sets/generate", json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["question_count"], 1)
        self.assertNotIn("answer_payload", response.json()["questions"][0])
        self.assertEqual((await self.request("POST", "/quiz-sets/generate", json={**request, "count": 0})).status_code, 422)
        self.assertEqual((await self.request("POST", "/quiz-sets/generate", json={**request, "workspace_id": "missing"})).status_code, 404)

    async def test_redo_cannot_reveal_other_questions_or_replace_active_paper(self):
        paper, question = await self.paper("full_paper")
        paper.question_count = 2
        other = QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=paper.id, prompt="Private", answer="SECRET",
            answer_payload="SECRET", explanation="PRIVATE explanation", question_type="single_choice", options=["SECRET", "wrong"])
        self.db.add(other)
        self.db.add(MistakeRecord(question_id=question.id, workspace_id=self.workspace.id))
        await self.db.commit()
        active = await self.started(paper)
        mistake = (await self.db.execute(select(MistakeRecord))).scalar_one()
        response = await self.request("POST", f"/mistakes/{mistake.id}/redo", json={"answer": "Three"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("PRIVATE explanation", response.text)
        view = (await self.request("GET", f"/quiz-sets/{paper.id}")).json()
        self.assertEqual(view["latest_run"]["id"], active["id"])
        resumed = await self.request("POST", f"/quiz-sets/{paper.id}/runs", json={"resume_unsubmitted": True})
        self.assertEqual(resumed.json()["id"], active["id"])
        self.assertNotIn("answer_payload", view["questions"][1])
        retry = await self.request("POST", f"/quiz-runs/{response.json()['run']['id']}/retry")
        scoped = retry.json()
        self.assertEqual(scoped["question_ids"], [question.id])
        await self.request("POST", f"/quiz-runs/{scoped['id']}/start")
        denied = await self.request("POST", f"/quiz-runs/{scoped['id']}/questions/{other.id}/submit", json={"answer": "SECRET"})
        self.assertEqual(denied.status_code, 400, denied.text)
        allowed = await self.request("POST", f"/quiz-runs/{scoped['id']}/questions/{question.id}/submit", json={"answer": "Three"})
        self.assertEqual(allowed.status_code, 200, allowed.text)
        await self.db.refresh(mistake)
        self.assertEqual(mistake.redo_count, 2)
        self.assertEqual(mistake.mastery_status, "mastered")

    async def test_retired_migration_preserves_legacy_run_scope_rows(self):
        """`question_ids` 现在由 Alembic 基线负责，运行时入口不再补列。"""
        from app.core.migrations import run_compat_migrations
        paper, _ = await self.paper()
        await self.db.commit()
        async with self.engine.begin() as conn:
            await conn.execute(text("INSERT INTO quiz_runs (id, quiz_set_id, round_number, answer_mode, status, elapsed_seconds, score, max_score, correct_count, graded_count) VALUES ('legacy-run', :paper, 1, 'sequential', 'not_started', 0, 0, 0, 0, 0)"), {"paper": paper.id})
            await run_compat_migrations(conn)
            await run_compat_migrations(conn)
            columns = (await conn.execute(text("PRAGMA table_info(quiz_runs)"))).all()
            self.assertIn("question_ids", [row[1] for row in columns])
            self.assertIsNone((await conn.execute(text("SELECT question_ids FROM quiz_runs WHERE id='legacy-run'"))).scalar_one())

    async def test_run_mode_override_and_invalid_status_filters(self):
        paper, _ = await self.paper()
        response = await self.request("POST", f"/quiz-sets/{paper.id}/runs", json={"answer_mode": "full_paper"})
        self.assertEqual(response.json()["answer_mode"], "full_paper")
        for path in ["/tasks?status=invalid", "/mistakes?mastery_status=invalid", "/weak-knowledge?limit=0", "/tasks?due_before=nonsense"]:
            self.assertEqual((await self.request("GET", path)).status_code, 422)
        self.assertEqual((await self.request("POST", "/weak-knowledge/recalculate", json={"knowledge_point_id": "missing"})).status_code, 404)

    async def test_chat_mistake_http_is_idempotent_and_uses_message_snapshot(self):
        from app.models.chat import ChatSession
        from app.models.conversation import Conversation
        document = Document(workspace_id=self.workspace.id, filename="geometry.pdf", file_path="x", file_type="pdf")
        self.db.add(document)
        await self.db.flush()
        session = ChatSession(user_id=self.user.id, workspace_id=self.workspace.id)
        self.db.add(session)
        await self.db.flush()
        message = Conversation(workspace_id=self.workspace.id, session_id=session.id, user_id=self.user.id,
            role="assistant", content="Three sides", sources=[{"document_id": document.id, "source_file": "geometry.pdf", "excerpt": "three"}])
        self.db.add(message)
        await self.db.commit()
        first = await self.client.post(f"/api/chat/messages/{message.id}/mistake")
        self.assertEqual(first.status_code, 201, first.text)
        second = await self.client.post(f"/api/chat/messages/{message.id}/mistake")
        self.assertEqual(first.json()["mistake_id"], second.json()["mistake_id"])
        items = (await self.request("GET", "/mistakes")).json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source_type"], "chat")
        self.assertEqual(items[0]["source_snapshot"], message.sources)
        self.assertEqual(items[0]["mastery_status"], "unresolved")
        filtered = await self.request("GET", "/mistakes", params={"document_id": document.id})
        self.assertEqual(filtered.json()["total"], 1)

    async def test_regrading_concurrency_has_one_winner_without_ai_write_lock(self):
        # Independent SQLite connections prove neither a Python lock nor a DB write
        # transaction is held while both provider calls are awaiting responses.
        with TemporaryDirectory() as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'regrade.db'}"
            engine = create_async_engine(url, connect_args={"timeout": 1})
            other_engine = create_async_engine(url, connect_args={"timeout": 1})
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            others = async_sessionmaker(other_engine, expire_on_commit=False)
            jobs = []
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                async with sessions() as db:
                    db.add(User(id="u-regrade", username="u-regrade"))
                    db.add_all([
                        Workspace(id="w", owner_id="u-regrade", name="w", slug="w"),
                        KnowledgePoint(id="p", workspace_id="w", title="p", mastery=0.5),
                        QuizSet(id="s", workspace_id="w", status="ready", question_count=1),
                        QuizQuestion(id="q", workspace_id="w", quiz_set_id="s", knowledge_point_id="p",
                            prompt="Explain", answer="Three", answer_payload="Three", question_type="short_answer", grading_rubric={"key_points": ["three"]}),
                        QuizRun(id="r", quiz_set_id="s", round_number=1, status="submitted"),
                        QuizAttempt(id="a", quiz_set_id="s", quiz_run_id="r", question_id="q", attempt_number=1,
                            user_answer="original", evaluation_status="grading_failed"),
                    ])
                    await db.commit()
                arrivals = [asyncio.Event(), asyncio.Event()]
                release = asyncio.Event()
                result = {"score": 1, "max_score": 1, "is_correct": True, "feedback": "Correct",
                    "matched_points": ["three"], "missing_points": [], "error_reason": None}
                async def retry(factory, index):
                    async with factory() as db:
                        async def provider(**kwargs):
                            self.assertFalse(db.in_transaction())
                            arrivals[index].set()
                            await release.wait()
                            return await _completion(result)(**kwargs)
                        return await service.retry_grading(db, "a", SETTINGS, provider)
                jobs = [asyncio.create_task(retry(sessions, 0)), asyncio.create_task(retry(others, 1))]
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in arrivals)), 5)
                async with others() as writer:
                    writer.add(StudyActivity(
                        user_id="u-regrade", workspace_id="w", activity_type="test",
                        title="Independent write",
                    ))
                    await asyncio.wait_for(writer.commit(), 3)
                release.set()
                outcomes = await asyncio.wait_for(asyncio.gather(*jobs, return_exceptions=True), 8)
                self.assertEqual(sum(isinstance(row, QuizAttempt) for row in outcomes), 1, outcomes)
                self.assertEqual(sum(isinstance(row, service.AssessmentStateError) for row in outcomes), 1, outcomes)
                async with sessions() as db:
                    self.assertEqual((await db.get(QuizQuestion, "q")).attempts, 1)
                    self.assertEqual((await db.get(KnowledgePoint, "p")).mastery, 0.62)
                    self.assertEqual((await db.get(QuizAttempt, "a")).user_answer, "original")
                    self.assertEqual((await db.get(QuizRun, "r")).graded_count, 1)
                    self.assertEqual(await db.scalar(select(func.count(QuizAttempt.id))), 1)
            finally:
                for job in jobs:
                    if not job.done():
                        job.cancel()
                if jobs:
                    await asyncio.gather(*jobs, return_exceptions=True)
                await engine.dispose()
                await other_engine.dispose()

    async def test_scoped_paper_submission_rejects_other_question_and_counts_subset(self):
        paper, question = await self.paper("full_paper")
        paper.question_count = 2
        other = QuizQuestion(workspace_id=self.workspace.id, quiz_set_id=paper.id, prompt="Other", answer="B",
            answer_payload="B", question_type="single_choice", options=["A", "B"])
        self.db.add(other)
        await self.db.commit()
        run = await service.create_quiz_run(self.db, paper.id, question_ids=[question.id, question.id])
        await service.start_quiz_run(self.db, run.id)
        url = f"/quiz-runs/{run.id}/submit"
        self.assertEqual((await self.request("POST", url, json={"answers": {other.id: "B"}})).status_code, 400)
        response = await self.request("POST", url, json={"answers": {question.id: "Three"}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["graded_count"], 1)
        self.assertEqual(response.json()["quiz_set"]["question_count"], 1)
        self.assertEqual(len(response.json()["quiz_set"]["questions"]), 1)
        with self.assertRaises(service.AssessmentValidationError):
            await service.create_quiz_run(self.db, paper.id, question_ids=[])

    async def test_scoped_subjective_paper_regrading_retains_redo_semantics(self):
        paper, question = await self.paper("full_paper", "short_answer")
        mistake = MistakeRecord(question_id=question.id, workspace_id=self.workspace.id)
        self.db.add(mistake)
        await self.db.commit()
        run = await service.create_quiz_run(self.db, paper.id, question_ids=[question.id])
        await service.start_quiz_run(self.db, run.id)
        async def unavailable(**kwargs):
            raise RuntimeError("provider down")
        with patch("litellm.acompletion", unavailable):
            response = await self.request("POST", f"/quiz-runs/{run.id}/submit", json={"answers": {question.id: "three"}})
        attempt = response.json()["attempts"][0]
        self.assertEqual(attempt["evaluation_status"], "grading_failed")
        result = {"score": 1, "max_score": 1, "is_correct": True, "feedback": "Correct",
            "matched_points": ["three"], "missing_points": [], "error_reason": None}
        with patch("litellm.acompletion", _completion(result)):
            response = await self.request("POST", f"/attempts/{attempt['id']}/retry-grading")
        self.assertEqual(response.status_code, 200, response.text)
        await self.db.refresh(mistake)
        self.assertEqual(mistake.redo_count, 1)
