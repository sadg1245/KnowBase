"""REST endpoints for persistent learning sessions and message actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.chat import ChatFeedback, ChatSession, LearningNote, RetrievalHit, RetrievalRun
from app.models.conversation import Conversation
from app.models.learning import Flashcard, QuizQuestion
from app.models.user import User
from app.schemas.chat import (
    ChatSessionCreate,
    ChatSessionUpdate,
    FeedbackUpdate,
    MessageNoteCreate,
    ScopeUpdate,
    SummaryNoteCreate,
)
from app.schemas.scope import RetrievalScope
from app.services.conversation_service import ConversationService
from app.services.activity_service import append_card_created
from app.services.ownership import owned_chat_session, owned_workspace, resolve_owned_scope
from app.services.scope_resolver import scope_from_session


router = APIRouter(prefix="/chat", tags=["chat sessions"])


def _iso(value):
    return value.isoformat() if value else None


def _normalized_scope(
    *,
    scope_mode: str | None,
    scope_config: dict | None,
    workspace_id: str | None,
    document_ids: list[str] | None,
) -> RetrievalScope:
    """把请求里的范围归一化：显式 scope 优先，兼容字段保持迁移前的 strict 语义。"""
    documents = list(document_ids or [])
    if scope_mode or scope_config:
        config = dict(scope_config or {})
        if workspace_id and not config.get("workspace_ids"):
            config["workspace_ids"] = [workspace_id]
        if documents and not config.get("document_ids"):
            config["document_ids"] = documents
        return RetrievalScope.from_config(scope_mode, config)
    if documents:
        return RetrievalScope(
            mode="strict",
            document_ids=documents,
            workspace_ids=[workspace_id] if workspace_id else [],
        )
    if workspace_id:
        return RetrievalScope(mode="strict", workspace_ids=[workspace_id])
    return RetrievalScope(mode="smart")


def _session(row: ChatSession) -> dict:
    scope = scope_from_session(row)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "workspace_id": row.workspace_id,
        "title": row.title,
        "document_ids": row.selected_document_ids or [],
        "scope": scope.model_dump() if scope else None,
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


async def _owned_assistant_message(
    db: AsyncSession, message_id: str, user_id: str
) -> tuple[Conversation, ChatSession]:
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
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    rows = await ConversationService(db, current_user.id).list_sessions(
        workspace_id=workspace_id, favorite=favorite
    )
    return [_session(row) for row in rows]


@router.post("/sessions", status_code=201)
async def create_session(
    payload: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if payload.workspace_id:
        await owned_workspace(db, payload.workspace_id, current_user)
    scope = _normalized_scope(
        scope_mode=payload.scope_mode,
        scope_config=payload.scope_config.model_dump() if payload.scope_config else None,
        workspace_id=payload.workspace_id,
        document_ids=payload.document_ids,
    )
    row = await ConversationService(db, current_user.id).create_session(
        workspace_id=payload.workspace_id,
        document_ids=payload.document_ids,
        mode=payload.mode,
        strict_sources=payload.strict_sources,
        title=payload.title,
        scope_mode=scope.mode,
        scope_config=scope.config_payload(),
    )
    return _session(row)


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = ConversationService(db, current_user.id)
    row = await owned_chat_session(db, session_id, current_user)
    return {**_session(row), "messages": [_message(item) for item in await service.messages(session_id)]}


@router.patch("/sessions/{session_id}")
async def update_session(
    session_id: str,
    payload: ChatSessionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await owned_chat_session(db, session_id, current_user)
    changes = payload.model_dump(exclude_unset=True)
    if "document_ids" in changes:
        changes["selected_document_ids"] = changes.pop("document_ids")
    if "mode" in changes:
        changes["preferred_mode"] = changes.pop("mode")
    if changes.get("workspace_id"):
        await owned_workspace(db, changes["workspace_id"], current_user)
    if "scope_mode" in changes or "scope_config" in changes or "selected_document_ids" in changes:
        current = await owned_chat_session(db, session_id, current_user)
        scope = scope_from_session(current) or RetrievalScope(mode="strict")
        if "scope_mode" in changes:
            scope.mode = changes.pop("scope_mode")
        if "scope_config" in changes:
            scope = RetrievalScope.from_config(
                scope.mode, dict(changes.pop("scope_config") or {})
            )
        if "selected_document_ids" in changes:
            scope.document_ids = list(changes["selected_document_ids"] or [])
        if changes.get("workspace_id"):
            scope.workspace_ids = [changes["workspace_id"]]
        changes["scope_mode"] = scope.mode
        changes["scope_config"] = scope.config_payload()
    row = await ConversationService(db, current_user.id).update_session(session_id, **changes)
    if row is None:
        raise HTTPException(404, "Learning session not found")
    return _session(row)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not await ConversationService(db, current_user.id).delete_session(session_id):
        raise HTTPException(404, "Learning session not found")
    return Response(status_code=204)


@router.get("/sessions/{session_id}/scope")
async def get_session_scope(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """当前学习范围，以及最近一次范围解析结果（可解释「为什么搜到这里」）。"""
    row = await owned_chat_session(db, session_id, current_user)
    scope = scope_from_session(row) or RetrievalScope(mode="strict")
    latest = (await db.execute(
        select(RetrievalRun)
        .where(RetrievalRun.session_id == session_id)
        .order_by(RetrievalRun.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    return {
        "mode": scope.mode,
        "scope": scope.model_dump(),
        "last_resolution": (latest.scope_resolution or None) if latest else None,
        "last_resolved_at": _iso(latest.created_at) if latest else None,
    }


@router.patch("/sessions/{session_id}/scope")
async def update_session_scope(
    session_id: str,
    payload: ScopeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """更新学习范围；客户端传入的 id 一律先做所有权收敛。"""
    await owned_chat_session(db, session_id, current_user)
    owned = await resolve_owned_scope(
        db,
        current_user,
        workspace_ids=payload.workspace_ids,
        document_ids=payload.document_ids,
        knowledge_point_ids=payload.knowledge_point_ids,
    )
    scope = RetrievalScope(
        mode=payload.mode,
        workspace_ids=owned.workspace_ids,
        document_ids=owned.document_ids,
        knowledge_point_ids=owned.knowledge_point_ids,
        allow_workspace_expansion=payload.allow_workspace_expansion,
    )
    changes: dict = {
        "scope_mode": scope.mode,
        "scope_config": scope.config_payload(),
        "selected_document_ids": list(scope.document_ids),
    }
    if scope.workspace_ids:
        changes["workspace_id"] = scope.workspace_ids[0]
    updated = await ConversationService(db, current_user.id).update_session(
        session_id, **changes
    )
    if updated is None:
        raise HTTPException(404, "Learning session not found")
    return {**_session(updated), "dropped_ids": owned.dropped_ids}


def _hit(row: RetrievalHit) -> dict:
    return {
        "chunk_id": row.chunk_id,
        "document_id": row.document_id,
        "source_file": row.source_file,
        "page_num": row.page_num,
        "heading": row.heading,
        "vector_rank": row.vector_rank,
        "keyword_rank": row.keyword_rank,
        "vector_score": row.vector_score,
        "keyword_score": row.keyword_score,
        "fusion_score": row.fusion_score,
        "rerank_score": row.rerank_score,
        "profile_bonus": row.profile_bonus,
        "final_rank": row.final_rank,
        "selected_as_evidence": row.selected_as_evidence,
    }


@router.get("/retrieval-runs/{run_id}")
async def get_retrieval_run(
    run_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """归当前用户所有的检索审计记录（含范围快照与融合明细）。"""
    statement = (
        select(RetrievalRun)
        .join(ChatSession, ChatSession.id == RetrievalRun.session_id)
        .where(RetrievalRun.id == run_id, ChatSession.user_id == current_user.id)
    )
    run = (await db.execute(statement)).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Retrieval run not found")
    hits = list((await db.execute(
        select(RetrievalHit)
        .where(RetrievalHit.retrieval_run_id == run_id)
        .order_by(RetrievalHit.final_rank)
    )).scalars().all())
    hit_payload = [_hit(row) for row in hits]
    return {
        "run_id": run.id,
        "session_id": run.session_id,
        "query": run.query,
        "scope_mode": run.scope_mode,
        "input_scope": (run.scope_snapshot or {}).get("input_scope"),
        "scope_snapshot": run.scope_snapshot or {},
        "resolved_scope": run.scope_resolution or {},
        "expansion_rounds": run.expansion_rounds,
        "expanded_scope": run.expanded_scope,
        "workspace_id": run.workspace_id,
        "document_ids": run.document_ids or [],
        "evidence_status": run.evidence_status,
        "top_score": run.top_score,
        "vector_succeeded": run.vector_succeeded,
        "keyword_succeeded": run.keyword_succeeded,
        "degradation_reason": run.degradation_reason,
        "config_snapshot": run.config_snapshot or {},
        "dense_results": [item for item in hit_payload if item["vector_rank"]],
        "keyword_results": [item for item in hit_payload if item["keyword_rank"]],
        "reranked_results": hit_payload,
        "created_at": _iso(run.created_at),
    }


@router.post("/sessions/{session_id}/summary-note", status_code=201)
async def create_summary_note(
    session_id: str,
    payload: SummaryNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = ConversationService(db, current_user.id)
    session = await owned_chat_session(db, session_id, current_user)
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
    from app.services.learning_memory import remember_session_summary

    await remember_session_summary(
        db, user_id=current_user.id, session=session, content=note.content
    )
    return {"id": note.id, "title": note.title, "content": note.content}


@router.post("/messages/{message_id}/card", status_code=201)
async def create_message_card(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    message, session = await _owned_assistant_message(db, message_id, current_user.id)
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
        await append_card_created(db, existing, user_id=current_user.id)
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
async def create_message_note(
    message_id: str,
    payload: MessageNoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    message, session = await _owned_assistant_message(db, message_id, current_user.id)
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
async def create_message_mistake(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    message, session = await _owned_assistant_message(db, message_id, current_user.id)
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
async def update_message_feedback(
    message_id: str,
    payload: FeedbackUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    await _owned_assistant_message(db, message_id, current_user.id)
    feedback = (await db.execute(select(ChatFeedback).where(
        ChatFeedback.message_id == message_id,
        ChatFeedback.user_id == current_user.id,
    ))).scalar_one_or_none()
    if feedback is None:
        feedback = ChatFeedback(message_id=message_id, user_id=current_user.id, helpful=payload.helpful)
        db.add(feedback)
    feedback.helpful = payload.helpful
    feedback.category = payload.category
    feedback.note = payload.note
    await db.flush()
    return {"id": feedback.id, "helpful": feedback.helpful, "category": feedback.category, "note": feedback.note}
