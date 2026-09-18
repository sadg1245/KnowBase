"""服务端所有权约束：所有私人资源都必须在加载阶段限定到当前用户。

不存在与不属于当前用户的记录统一返回 404，避免泄露记录是否存在。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import (
    LearningTask,
    MistakeRecord,
    QuizAttempt,
    QuizRun,
    QuizSet,
    WeakKnowledgeState,
)
from app.models.chat import ChatSession, LearningNote
from app.models.document import Document
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, StudySession
from app.models.user import LearningDomain, User
from app.models.workspace import Workspace


not_found = lambda label: HTTPException(404, f"{label} not found")  # noqa: E731


def _workspace_ids(user: User):
    return select(Workspace.id).where(Workspace.owner_id == user.id)


async def owned_workspace(
    db: AsyncSession, workspace_id: str, user: User, *, label: str = "Knowledge base"
) -> Workspace:
    row = (await db.execute(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.owner_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        raise not_found(label)
    return row


async def workspace_owner_id(db: AsyncSession, workspace_id: str | None) -> str:
    """由知识库推导所有者，保证记录上的 user_id 与所有者始终一致。"""
    if not workspace_id:
        raise ValueError("A private record requires a knowledge base owner")
    owner = await db.scalar(
        select(Workspace.owner_id).where(Workspace.id == workspace_id)
    )
    if not owner:
        raise ValueError(f"Knowledge base {workspace_id} has no owner")
    return owner


async def owned_domain(db: AsyncSession, domain_id: str, user: User) -> LearningDomain:
    row = (await db.execute(
        select(LearningDomain).where(
            LearningDomain.id == domain_id, LearningDomain.user_id == user.id
        )
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Learning domain")
    return row


async def _by_workspace(
    db: AsyncSession, model, record_id: str, user: User, label: str
):
    row = (await db.execute(
        select(model).where(
            model.id == record_id,
            model.workspace_id.in_(_workspace_ids(user)),
        )
    )).scalar_one_or_none()
    if row is None:
        raise not_found(label)
    return row


async def owned_document(db: AsyncSession, document_id: str, user: User) -> Document:
    return await _by_workspace(db, Document, document_id, user, "Document")


async def owned_point(db: AsyncSession, point_id: str, user: User) -> KnowledgePoint:
    return await _by_workspace(db, KnowledgePoint, point_id, user, "Knowledge point")


async def owned_card(db: AsyncSession, card_id: str, user: User) -> Flashcard:
    return await _by_workspace(db, Flashcard, card_id, user, "Card")


async def owned_question(db: AsyncSession, question_id: str, user: User) -> QuizQuestion:
    return await _by_workspace(db, QuizQuestion, question_id, user, "Question")


async def owned_quiz_set(db: AsyncSession, quiz_set_id: str, user: User) -> QuizSet:
    return await _by_workspace(db, QuizSet, quiz_set_id, user, "Quiz set")


async def owned_mistake(db: AsyncSession, mistake_id: str, user: User) -> MistakeRecord:
    return await _by_workspace(db, MistakeRecord, mistake_id, user, "Mistake")


async def owned_task(db: AsyncSession, task_id: str, user: User) -> LearningTask:
    return await _by_workspace(db, LearningTask, task_id, user, "Learning task")


async def owned_weak_state(
    db: AsyncSession, state_id: str, user: User
) -> WeakKnowledgeState:
    return await _by_workspace(db, WeakKnowledgeState, state_id, user, "Weak knowledge")


async def owned_quiz_run(db: AsyncSession, run_id: str, user: User) -> QuizRun:
    row = (await db.execute(
        select(QuizRun)
        .join(QuizSet, QuizSet.id == QuizRun.quiz_set_id)
        .where(QuizRun.id == run_id, QuizSet.workspace_id.in_(_workspace_ids(user)))
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Quiz run")
    return row


async def owned_attempt(db: AsyncSession, attempt_id: str, user: User) -> QuizAttempt:
    row = (await db.execute(
        select(QuizAttempt)
        .join(QuizSet, QuizSet.id == QuizAttempt.quiz_set_id)
        .where(QuizAttempt.id == attempt_id, QuizSet.workspace_id.in_(_workspace_ids(user)))
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Quiz attempt")
    return row


async def owned_chat_session(db: AsyncSession, session_id: str, user: User) -> ChatSession:
    row = (await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id, ChatSession.user_id == user.id
        )
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Learning session")
    return row


async def owned_study_session(db: AsyncSession, session_id: str, user: User) -> StudySession:
    row = (await db.execute(
        select(StudySession).where(
            StudySession.id == session_id, StudySession.user_id == user.id
        )
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Study session")
    return row


async def owned_note(db: AsyncSession, note_id: str, user: User) -> LearningNote:
    row = (await db.execute(
        select(LearningNote)
        .outerjoin(Workspace, Workspace.id == LearningNote.workspace_id)
        .outerjoin(ChatSession, ChatSession.id == LearningNote.session_id)
        .where(
            LearningNote.id == note_id,
            (Workspace.owner_id == user.id) | (ChatSession.user_id == user.id),
        )
    )).scalar_one_or_none()
    if row is None:
        raise not_found("Note")
    return row
