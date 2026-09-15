"""REST endpoints for persistent learning sessions and message actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.chat import ChatFeedback, ChatSession, LearningNote
from app.models.conversation import Conversation
from app.models.learning import Flashcard, QuizQuestion
from app.schemas.chat import ChatSessionCreate, ChatSessionUpdate, FeedbackUpdate, MessageNoteCreate, SummaryNoteCreate
from app.services.conversation_service import ConversationService
from app.services.activity_service import append_card_created


router = APIRouter(prefix="/chat", tags=["chat sessions"])


def _iso(value):
    return value.isoformat() if value else None


def _session(row: ChatSession) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "document_ids": row.selected_document_ids or [],
        "mode": row.preferred_mode,
        "strict_sources": row.strict_sources,
        "is_favorite": row.is_favorite,
        "summary": row.summary,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "last_message_at": _iso(row.last_message_at),
    }


def _message(row: Conversation) -> dict:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "role": row.role,
        "content": row.content,
        "sources": row.sources or [],
        "mode": row.mode,
        "evidence_status": row.evidence_status,
        "follow_up_questions": row.follow_up_questions or [],
        "generation_status": row.generation_status,
        "created_at": _iso(row.created_at),
    }


async def _owned_assistant_message(db: AsyncSession, message_id: str, user_id: str = "default") -> tuple[Conversation, ChatSession]:
    stmt = (
        select(Conversation, ChatSession)
        .join(ChatSession, Conversation.session_id == ChatSession.id)
        .where(Conversation.id == message_id, Conversation.role == "assistant", ChatSession.user_id == user_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(404, "Assistant message not found")
    return row[0], row[1]


async def _previous_question(db: AsyncSession, message: Conversation) -> str:
    stmt = (
        select(Conversation.content)
        .where(
            Conversation.session_id == message.session_id,
            Conversation.role == "user",
            Conversation.created_at <= message.created_at,
        )
        .order_by(Conversation.created_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() or "这段回答解决了什么问题？"


@router.get("/sessions")
async def list_sessions(
    workspace_id: str | None = None,
    favorite: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    rows = await ConversationService(db).list_sessions(workspace_id=workspace_id, favorite=favorite)
    return [_session(row) for row in rows]


@router.post("/sessions", status_code=201)
async def create_session(payload: ChatSessionCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = await ConversationService(db).create_session(
        workspace_id=payload.workspace_id,
        document_ids=payload.document_ids,
        mode=payload.mode,
        strict_sources=payload.strict_sources,
        title=payload.title,
    )
    return _session(row)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    service = ConversationService(db)
    row = await service.get_session(session_id)
    if row is None:
        raise HTTPException(404, "Learning session not found")
    return {**_session(row), "messages": [_message(item) for item in await service.messages(session_id)]}


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, payload: ChatSessionUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if "document_ids" in changes:
        changes["selected_document_ids"] = changes.pop("document_ids")
    if "mode" in changes:
        changes["preferred_mode"] = changes.pop("mode")
    row = await ConversationService(db).update_session(session_id, **changes)
    if row is None:
        raise HTTPException(404, "Learning session not found")
    return _session(row)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    if not await ConversationService(db).delete_session(session_id):
        raise HTTPException(404, "Learning session not found")
    return Response(status_code=204)


@router.post("/sessions/{session_id}/summary-note", status_code=201)
async def create_summary_note(session_id: str, payload: SummaryNoteCreate, db: AsyncSession = Depends(get_db)) -> dict:
    service = ConversationService(db)
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(404, "Learning session not found")
    messages = await service.messages(session_id)
    content = payload.content or "\n\n".join(f"{'我' if item.role == 'user' else 'AI'}：{item.content}" for item in messages[-12:])
    if not content.strip():
        raise HTTPException(400, "The session has no content to summarize")
    note = LearningNote(
        workspace_id=session.workspace_id,
        session_id=session.id,
        title=payload.title or f"{session.title} · 会话笔记",
        content=content,
        source_snapshot=[source for item in messages for source in (item.sources or [])],
    )
    db.add(note)
    await db.flush()
    return {"id": note.id, "title": note.title, "content": note.content}


@router.post("/messages/{message_id}/card", status_code=201)
async def create_message_card(message_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    message, session = await _owned_assistant_message(db, message_id)
    existing = (await db.execute(select(Flashcard).where(Flashcard.origin_message_id == message_id))).scalar_one_or_none()
    if existing is None:
        if not session.workspace_id:
            raise HTTPException(400, "This session is not associated with a knowledge base")
        existing = Flashcard(
            workspace_id=session.workspace_id,
            origin_message_id=message.id,
            front=await _previous_question(db, message),
            back=message.content,
            source_label=(message.sources or [{}])[0].get("source_file") if message.sources else None,
            source_type="answer",
            source_snapshot=message.sources or [],
        )
        db.add(existing)
        await db.flush()
        await append_card_created(db, existing)
    elif existing.source_type == "manual":
        existing.source_type = "answer"
        existing.source_snapshot = message.sources or []
    return {
        "id": existing.id,
        "front": existing.front,
        "back": existing.back,
        "source_label": existing.source_label,
        "source_type": existing.source_type,
        "source_snapshot": existing.source_snapshot,
    }


@router.post("/messages/{message_id}/note", status_code=201)
async def create_message_note(message_id: str, payload: MessageNoteCreate, db: AsyncSession = Depends(get_db)) -> dict:
    message, session = await _owned_assistant_message(db, message_id)
    note = (await db.execute(select(LearningNote).where(LearningNote.message_id == message_id))).scalar_one_or_none()
    if note is None:
        note = LearningNote(
            workspace_id=session.workspace_id,
            session_id=session.id,
            message_id=message.id,
            title=payload.title or (await _previous_question(db, message))[:80],
            content=payload.content or message.content,
            source_snapshot=message.sources or [],
        )
        db.add(note)
        await db.flush()
    return {"id": note.id, "title": note.title, "content": note.content}


@router.post("/messages/{message_id}/mistake", status_code=201)
async def create_message_mistake(message_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    message, session = await _owned_assistant_message(db, message_id)
    quiz = (await db.execute(select(QuizQuestion).where(QuizQuestion.origin_message_id == message_id))).scalar_one_or_none()
    if quiz is None:
        if not session.workspace_id:
            raise HTTPException(400, "This session is not associated with a knowledge base")
        quiz = QuizQuestion(
            workspace_id=session.workspace_id,
            origin_message_id=message.id,
            question_type="short",
            prompt=await _previous_question(db, message),
            answer=message.content,
            explanation="来自 AI 学习会话，可在错题中心继续作答。",
            source_label=(message.sources or [{}])[0].get("source_file") if message.sources else None,
            last_correct=False,
        )
        db.add(quiz)
        await db.flush()
    from app.services.assessment_workflows import ensure_chat_mistake
    mistake = await ensure_chat_mistake(db, quiz, message.sources)
    return {"id": quiz.id, "prompt": quiz.prompt, "question_type": quiz.question_type, "mistake_id": mistake.id}


@router.put("/messages/{message_id}/feedback")
async def update_message_feedback(message_id: str, payload: FeedbackUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    await _owned_assistant_message(db, message_id)
    feedback = (await db.execute(select(ChatFeedback).where(ChatFeedback.message_id == message_id, ChatFeedback.user_id == "default"))).scalar_one_or_none()
    if feedback is None:
        feedback = ChatFeedback(message_id=message_id, user_id="default", helpful=payload.helpful)
        db.add(feedback)
    feedback.helpful = payload.helpful
    feedback.category = payload.category
    feedback.note = payload.note
    await db.flush()
    return {"id": feedback.id, "helpful": feedback.helpful, "category": feedback.category, "note": feedback.note}
