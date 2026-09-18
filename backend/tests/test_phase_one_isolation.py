"""第一阶段：双用户数据隔离。直接构造第二个用户验证所有权边界。"""

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.models.assessment import (
    LearningTask,
    MistakeRecord,
    QuizAttempt,
    QuizRun,
    QuizSet,
    WeakKnowledgeState,
)
from app.models.base import Base
from app.models.chat import ChatSession
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.learning import Flashcard, KnowledgePoint, LearningGoal, QuizQuestion, StudyActivity
from tests.support import TEST_PASSWORD, create_user, create_workspace, login, wire_test_app


NOW = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)


class CrossUserIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        self.alice = await create_user(self.db, username="alice", display_name="Alice")
        self.bob = await create_user(self.db, username="bob", display_name="Bob")
        await self._seed(self.alice, "alice")
        await self._seed(self.bob, "bob")
        await self.db.commit()

        self.app, self.client = wire_test_app(self.sessions, self.db)
        self.alice_headers = await login(self.client, "alice")
        self.bob_headers = await login(self.client, "bob")

    async def asyncTearDown(self):
        self.app.dependency_overrides.clear()
        if hasattr(self.app.state, "session_factory"):
            del self.app.state.session_factory
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def _seed(self, user, prefix: str) -> None:
        workspace = await create_workspace(
            self.db, user, name=f"{prefix}-kb", slug=f"{prefix}-kb"
        )
        document = Document(
            workspace_id=workspace.id,
            filename=f"{prefix}.pdf",
            file_path=f"{prefix}.pdf",
            file_type=".pdf",
            status="ready",
        )
        self.db.add(document)
        await self.db.flush()
        point = KnowledgePoint(
            workspace_id=workspace.id, document_id=document.id,
            title=f"{prefix}-point", mastery=0.5,
        )
        self.db.add(point)
        await self.db.flush()
        card = Flashcard(
            workspace_id=workspace.id, knowledge_point_id=point.id,
            front=f"{prefix}-front", back=f"{prefix}-back",
        )
        session = ChatSession(user_id=user.id, workspace_id=workspace.id, title=f"{prefix}-session")
        self.db.add_all([card, session])
        await self.db.flush()
        message = Conversation(
            user_id=user.id, workspace_id=workspace.id, session_id=session.id,
            role="assistant", content=f"{prefix}-answer", sources=[],
        )
        self.db.add_all([
            message,
            StudyActivity(
                user_id=user.id, workspace_id=workspace.id,
                activity_type="document_read", title=f"{prefix}-activity",
                duration_seconds=600, occurred_at=NOW - timedelta(minutes=5),
            ),
            LearningGoal(user_id=user.id, scope_type="global", metric="daily_minutes", target_value=30),
        ])
        await self.db.flush()
        quiz_set = QuizSet(workspace_id=workspace.id, title=f"{prefix}-set", question_count=1, status="ready")
        self.db.add(quiz_set)
        await self.db.flush()
        question = QuizQuestion(
            workspace_id=workspace.id, quiz_set_id=quiz_set.id,
            knowledge_point_id=point.id, prompt=f"{prefix}-q", answer="A",
        )
        self.db.add(question)
        await self.db.flush()
        run = QuizRun(quiz_set_id=quiz_set.id, round_number=1, status="not_started")
        self.db.add(run)
        await self.db.flush()
        attempt = QuizAttempt(
            quiz_set_id=quiz_set.id, quiz_run_id=run.id, question_id=question.id,
            attempt_number=1, user_answer={"value": "A"}, evaluation_status="pending_ai",
        )
        self.db.add_all([
            attempt,
            MistakeRecord(
                question_id=question.id, workspace_id=workspace.id,
                knowledge_point_id=point.id, mastery_status="unresolved",
            ),
            WeakKnowledgeState(
                knowledge_point_id=point.id, workspace_id=workspace.id, weakness_score=70,
            ),
            LearningTask(
                workspace_id=workspace.id, knowledge_point_id=point.id,
                task_type="review", title=f"{prefix}-task", due_at=NOW,
            ),
        ])
        await self.db.flush()
        setattr(self, f"{prefix}_ids", {
            "workspace": workspace.id, "document": document.id, "point": point.id,
            "card": card.id, "session": session.id, "message": message.id,
            "quiz_set": quiz_set.id, "question": question.id, "run": run.id,
            "attempt": attempt.id, "mistake": question.id,
        })

    async def test_knowledge_bases_and_documents_are_scoped(self):
        mine = await self.client.get("/api/workspaces", headers=self.alice_headers)
        self.assertEqual([row["id"] for row in mine.json()], [self.alice_ids["workspace"]])

        foreign = await self.client.get(
            f"/api/workspaces/{self.bob_ids['workspace']}", headers=self.alice_headers
        )
        self.assertEqual(foreign.status_code, 404)

        foreign_docs = await self.client.get(
            f"/api/workspaces/{self.bob_ids['workspace']}/documents", headers=self.alice_headers
        )
        self.assertEqual(foreign_docs.status_code, 404)

        for path in (
            f"/api/documents/{self.bob_ids['document']}",
            f"/api/documents/{self.bob_ids['document']}/sections",
            f"/api/documents/{self.bob_ids['document']}/status",
            f"/api/documents/{self.bob_ids['document']}/content",
        ):
            with self.subTest(path=path):
                response = await self.client.get(path, headers=self.alice_headers)
                self.assertEqual(response.status_code, 404, path)

        renamed = await self.client.patch(
            f"/api/documents/{self.bob_ids['document']}",
            headers=self.alice_headers, json={"filename": "stolen.pdf"},
        )
        self.assertEqual(renamed.status_code, 404)
        deleted = await self.client.delete(
            f"/api/documents/{self.bob_ids['document']}", headers=self.alice_headers
        )
        self.assertEqual(deleted.status_code, 404)

    async def test_knowledge_points_and_cards_are_scoped(self):
        point = self.bob_ids["point"]
        for path, method, payload in (
            (f"/api/learning/knowledge-points/{point}", "put", {"title": "x"}),
            (f"/api/learning/knowledge-points/{point}", "delete", None),
            (f"/api/learning/knowledge-points/{point}/quiz", "post", None),
            (f"/api/learning/knowledge-points/{point}/card", "post", None),
        ):
            with self.subTest(path=path):
                response = await self.client.request(
                    method, path, headers=self.alice_headers, json=payload
                )
                self.assertEqual(response.status_code, 404, path)

        listed = await self.client.get(
            f"/api/learning/knowledge-points?workspace_id={self.bob_ids['workspace']}",
            headers=self.alice_headers,
        )
        self.assertEqual(listed.status_code, 404)

        cards = await self.client.get("/api/learning/cards", headers=self.alice_headers)
        self.assertEqual([row["id"] for row in cards.json()], [self.alice_ids["card"]])
        foreign_card = await self.client.put(
            f"/api/learning/cards/{self.bob_ids['card']}",
            headers=self.alice_headers, json={"front": "stolen"},
        )
        self.assertEqual(foreign_card.status_code, 404)
        reviewed = await self.client.post(
            f"/api/learning/cards/{self.bob_ids['card']}/review",
            headers=self.alice_headers, json={"rating": 3, "duration_seconds": 5},
        )
        self.assertEqual(reviewed.status_code, 404)

    async def test_conversations_and_message_actions_are_scoped(self):
        sessions = await self.client.get("/api/chat/sessions", headers=self.alice_headers)
        self.assertEqual([row["id"] for row in sessions.json()], [self.alice_ids["session"]])

        foreign_session = await self.client.get(
            f"/api/chat/sessions/{self.bob_ids['session']}", headers=self.alice_headers
        )
        self.assertEqual(foreign_session.status_code, 404)
        foreign_delete = await self.client.delete(
            f"/api/chat/sessions/{self.bob_ids['session']}", headers=self.alice_headers
        )
        self.assertEqual(foreign_delete.status_code, 404)

        for action in ("card", "note", "mistake"):
            with self.subTest(action=action):
                response = await self.client.post(
                    f"/api/chat/messages/{self.bob_ids['message']}/{action}",
                    headers=self.alice_headers, json={"content": "x"},
                )
                self.assertEqual(response.status_code, 404, action)
        feedback = await self.client.put(
            f"/api/chat/messages/{self.bob_ids['message']}/feedback",
            headers=self.alice_headers, json={"helpful": True},
        )
        self.assertEqual(feedback.status_code, 404)

    async def test_assessments_goals_reports_and_activities_are_scoped(self):
        foreign_set = await self.client.get(
            f"/api/learning/quiz-sets/{self.bob_ids['quiz_set']}", headers=self.alice_headers
        )
        self.assertEqual(foreign_set.status_code, 404)
        for path in (
            f"/api/learning/quiz-runs/{self.bob_ids['run']}/start",
            f"/api/learning/quiz-runs/{self.bob_ids['run']}/submit",
            f"/api/learning/quiz-runs/{self.bob_ids['run']}/retry",
        ):
            with self.subTest(path=path):
                response = await self.client.post(
                    path, headers=self.alice_headers, json={"answers": {}, "duration_seconds": 1}
                )
                self.assertEqual(response.status_code, 404, path)
        retry = await self.client.post(
            f"/api/learning/attempts/{self.bob_ids['attempt']}/retry-grading",
            headers=self.alice_headers,
        )
        self.assertEqual(retry.status_code, 404)
        redo = await self.client.post(
            f"/api/learning/mistakes/{self.bob_ids['mistake']}/redo",
            headers=self.alice_headers, json={"answer": "A"},
        )
        self.assertEqual(redo.status_code, 404)
        tasks = await self.client.get("/api/learning/tasks", headers=self.alice_headers)
        self.assertEqual([row["title"] for row in tasks.json()["items"]], ["alice-task"])
        foreign_task = await self.client.post(
            f"/api/learning/tasks/{self.bob_ids['mistake']}/complete", headers=self.alice_headers
        )
        self.assertEqual(foreign_task.status_code, 404)
        mistakes = await self.client.get("/api/learning/mistakes", headers=self.alice_headers)
        self.assertEqual(mistakes.json()["total"], 1)
        weak = await self.client.get("/api/learning/weak-knowledge", headers=self.alice_headers)
        self.assertEqual(
            [row["knowledge_point_id"] for row in weak.json()["items"]], [self.alice_ids["point"]]
        )

        foreign_goal = await self.client.put(
            f"/api/learning/goals/workspaces/{self.bob_ids['workspace']}",
            headers=self.alice_headers,
            json={"target_mastery": 90, "target_date": "2026-12-31"},
        )
        self.assertEqual(foreign_goal.status_code, 404)

        activities = await self.client.get("/api/learning/activities", headers=self.alice_headers)
        self.assertEqual(
            [row["title"] for row in activities.json()["items"]], ["alice-activity"]
        )

        report = await self.client.get(
            "/api/learning/reports/day?anchor_date=2026-09-16", headers=self.alice_headers
        )
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["activity_count"], 1)

        export = await self.client.get("/api/learning/export", headers=self.alice_headers)
        payload = export.json()
        self.assertIn("alice-kb", [row["name"] for row in payload["knowledge_bases"]])
        self.assertNotIn("bob-kb", [row["name"] for row in payload["knowledge_bases"]])
        self.assertEqual(len(payload["activities"]), 1)

    async def test_search_and_chat_scope_to_owned_knowledge_bases(self):
        foreign_chat = await self.client.post(
            "/api/chat",
            headers=self.alice_headers,
            json={"question": "hi", "workspace_id": self.bob_ids["workspace"]},
        )
        self.assertEqual(foreign_chat.status_code, 404)

        foreign_start = await self.client.post(
            "/api/learning/study-sessions/start",
            headers=self.alice_headers,
            json={
                "id": "foreign", "context_type": "document",
                "context_id": self.bob_ids["document"], "workspace_id": self.alice_ids["workspace"],
            },
        )
        self.assertEqual(foreign_start.status_code, 404)

    async def test_forged_user_ids_are_ignored_by_the_server(self):
        created = await self.client.post(
            "/api/workspaces",
            headers=self.alice_headers,
            json={"name": "注入尝试", "description": "", "owner_id": self.bob.id},
        )
        self.assertEqual(created.status_code, 201, created.text)

        rows = await self.client.get("/api/workspaces", headers=self.bob_headers)
        self.assertNotIn(created.json()["id"], [row["id"] for row in rows.json()])

        chat = await self.client.post(
            "/api/chat/sessions",
            headers=self.alice_headers,
            json={"workspace_id": self.alice_ids["workspace"], "user_id": self.bob.id},
        )
        self.assertEqual(chat.status_code, 201, chat.text)
        sessions = await self.client.get("/api/chat/sessions", headers=self.bob_headers)
        self.assertNotIn(chat.json()["id"], [row["id"] for row in sessions.json()])


if __name__ == "__main__":
    unittest.main()
