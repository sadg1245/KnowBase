"""Conversation lifecycle operations shared by chat and REST endpoints."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.models.conversation import Conversation
from app.services.activity_service import append_activity


SESSION_MODES = {"direct", "simple", "deep", "socratic", "feynman", "quiz"}
SESSION_SCOPE_MODES = {"strict", "focused", "smart", "global"}


def build_session_title(question: str) -> str:
    """Create a stable fallback title without requiring an LLM call."""
    normalized = re.sub(r"\s+", " ", question).strip()
    return normalized[:24] if normalized else "新学习会话"


class ConversationService:
    def __init__(self, db: AsyncSession, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    async def create_session(
        self,
        *,
        workspace_id: str | None,
        document_ids: list[str],
        mode: str,
        strict_sources: bool,
        title: str = "新学习会话",
        scope_mode: str = "strict",
        scope_config: dict | None = None,
    ) -> ChatSession:
        session = ChatSession(
            user_id=self.user_id,
            workspace_id=workspace_id,
            title=title.strip() or "新学习会话",
            selected_document_ids=list(dict.fromkeys(document_ids)),
            scope_mode=scope_mode if scope_mode in SESSION_SCOPE_MODES else "strict",
            scope_config=dict(scope_config or {}),
            preferred_mode=mode if mode in SESSION_MODES else "simple",
            strict_sources=strict_sources,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def list_sessions(
        self,
        *,
        workspace_id: str | None = None,
        favorite: bool | None = None,
    ) -> list[ChatSession]:
        stmt = select(ChatSession).where(ChatSession.user_id == self.user_id)
        if workspace_id is not None:
            stmt = stmt.where(ChatSession.workspace_id == workspace_id)
        if favorite is not None:
            stmt = stmt.where(ChatSession.is_favorite.is_(favorite))
        stmt = stmt.order_by(ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_session(self, session_id: str) -> ChatSession | None:
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == self.user_id,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def update_session(self, session_id: str, **changes) -> ChatSession | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        allowed = {
            "title",
            "workspace_id",
            "selected_document_ids",
            "scope_mode",
            "scope_config",
            "preferred_mode",
            "strict_sources",
            "is_favorite",
            "summary",
        }
        for key, value in changes.items():
            if key not in allowed or value is None:
                continue
            if key == "title":
                value = str(value).strip() or "新学习会话"
            elif key == "selected_document_ids":
                value = list(dict.fromkeys(value))
            elif key == "scope_config":
                value = dict(value)
            elif key == "scope_mode" and value not in SESSION_SCOPE_MODES:
                continue
            elif key == "preferred_mode" and value not in SESSION_MODES:
                continue
            setattr(session, key, value)
        session.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def touch_session(self, session: ChatSession, question: str) -> bool:
        """Update activity and assign the first-question fallback title."""
        title_changed = False
        if session.title == "新学习会话":
            session.title = build_session_title(question)
            title_changed = True
        now = datetime.now(timezone.utc)
        session.last_message_at = now
        session.updated_at = now
        await self.db.flush()
        return title_changed

    async def record_question(self, session: ChatSession, message: Conversation):
        """Record one persisted user question without copying its content."""
        return await append_activity(
            self.db,
            user_id=self.user_id,
            event_key=f"activity:question:{message.id}",
            activity_type="question_asked",
            title="发起了一次学习提问",
            workspace_id=session.workspace_id,
            source_type="conversation_message",
            source_id=message.id,
            payload={
                "question_length": len(message.content),
                "mode": message.mode or session.preferred_mode,
                "session_id": session.id,
                "document_ids": list(session.selected_document_ids or []),
            },
            occurred_at=message.created_at,
        )

    async def messages(self, session_id: str) -> list[Conversation]:
        if await self.get_session(session_id) is None:
            return []
        stmt = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
            .order_by(Conversation.created_at.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def message_count(self, session_id: str) -> int:
        stmt = select(func.count(Conversation.id)).where(Conversation.session_id == session_id)
        return int((await self.db.execute(stmt)).scalar() or 0)

    async def delete_session(self, session_id: str) -> bool:
        session = await self.get_session(session_id)
        if session is None:
            return False
        await self.db.execute(delete(Conversation).where(Conversation.session_id == session_id))
        await self.db.delete(session)
        await self.db.flush()
        return True
