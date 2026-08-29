"""Behavior tests for the learning conversation lifecycle."""

import importlib
import unittest

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.conversation import Conversation
from app.models.chat import ChatFeedback
from app.models.workspace import Workspace


def _load_service():
    try:
        return importlib.import_module("app.services.conversation_service")
    except ModuleNotFoundError:
        return None


class ConversationTitleTests(unittest.TestCase):
    def test_title_uses_normalized_first_question_and_limits_length(self):
        module = _load_service()
        if module is None:
            self.fail("conversation_service is missing")

        self.assertEqual(module.build_session_title("  什么是   向量检索？  "), "什么是 向量检索？")
        self.assertEqual(module.build_session_title("甲" * 30), "甲" * 24)
        self.assertEqual(module.build_session_title("   "), "新学习会话")

    def test_session_api_contract_is_registered(self):
        try:
            routes = importlib.import_module("app.api.routes.chat_sessions")
            schemas = importlib.import_module("app.schemas.chat")
        except ModuleNotFoundError as exc:
            self.fail(f"session API module is missing: {exc}")

        paths = {route.path for route in routes.router.routes}
        self.assertTrue({
            "/chat/sessions",
            "/chat/sessions/{session_id}",
            "/chat/sessions/{session_id}/summary-note",
            "/chat/messages/{message_id}/card",
            "/chat/messages/{message_id}/note",
            "/chat/messages/{message_id}/mistake",
            "/chat/messages/{message_id}/feedback",
        }.issubset(paths))
        request = schemas.ChatSessionCreate(
            workspace_id="workspace",
            document_ids=["doc-a"],
            mode="deep",
            strict_sources=False,
        )
        self.assertEqual(request.document_ids, ["doc-a"])
        self.assertEqual(request.mode, "deep")


class ConversationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_create_update_filter_and_delete_session(self):
        module = _load_service()
        if module is None:
            self.fail("conversation_service is missing")

        async with self.session_factory() as db:
            service = module.ConversationService(db, user_id="default")
            first = await service.create_session(
                workspace_id=None,
                document_ids=["doc-a"],
                mode="simple",
                strict_sources=True,
            )
            second = await service.create_session(
                workspace_id=None,
                document_ids=[],
                mode="deep",
                strict_sources=False,
            )
            await service.update_session(first.id, title="重点复习", is_favorite=True)
            db.add(Conversation(
                user_id="default:legacy",
                session_id=first.id,
                role="user",
                content="问题",
            ))
            await db.commit()

            favorites = await service.list_sessions(favorite=True)
            self.assertEqual([item.id for item in favorites], [first.id])
            self.assertEqual(favorites[0].title, "重点复习")
            self.assertEqual(favorites[0].selected_document_ids, ["doc-a"])

            await service.delete_session(first.id)
            self.assertIsNone(await service.get_session(first.id))
            self.assertEqual(await service.message_count(first.id), 0)
            self.assertIsNotNone(await service.get_session(second.id))

    async def test_message_learning_actions_are_idempotent(self):
        routes = importlib.import_module("app.api.routes.chat_sessions")
        schemas = importlib.import_module("app.schemas.chat")

        async with self.session_factory() as db:
            workspace = Workspace(name="测试", slug="test")
            db.add(workspace)
            await db.flush()
            service = importlib.import_module("app.services.conversation_service").ConversationService(db)
            chat_session = await service.create_session(
                workspace_id=workspace.id,
                document_ids=[],
                mode="simple",
                strict_sources=True,
            )
            user_message = Conversation(
                user_id="default",
                session_id=chat_session.id,
                workspace_id=workspace.id,
                role="user",
                content="什么是混合检索？",
            )
            assistant_message = Conversation(
                user_id="default",
                session_id=chat_session.id,
                workspace_id=workspace.id,
                role="assistant",
                content="混合检索会组合关键词与向量召回。",
                sources=[{"source_file": "资料.pdf"}],
            )
            db.add_all([user_message, assistant_message])
            await db.flush()

            note_a = await routes.create_message_note(assistant_message.id, schemas.MessageNoteCreate(), db)
            note_b = await routes.create_message_note(assistant_message.id, schemas.MessageNoteCreate(), db)
            card_a = await routes.create_message_card(assistant_message.id, db)
            card_b = await routes.create_message_card(assistant_message.id, db)
            mistake_a = await routes.create_message_mistake(assistant_message.id, db)
            mistake_b = await routes.create_message_mistake(assistant_message.id, db)
            await routes.update_message_feedback(assistant_message.id, schemas.FeedbackUpdate(helpful=True), db)
            feedback = await routes.update_message_feedback(
                assistant_message.id,
                schemas.FeedbackUpdate(helpful=False, category="unsupported"),
                db,
            )

            self.assertEqual(note_a["id"], note_b["id"])
            self.assertEqual(card_a["id"], card_b["id"])
            self.assertEqual(card_a["source_type"], "answer")
            self.assertEqual(card_a["source_snapshot"], [{"source_file": "资料.pdf"}])
            self.assertEqual(mistake_a["id"], mistake_b["id"])
            self.assertFalse(feedback["helpful"])
            feedback_count = (await db.execute(select(func.count(ChatFeedback.id)))).scalar()
            self.assertEqual(feedback_count, 1)


if __name__ == "__main__":
    unittest.main()
