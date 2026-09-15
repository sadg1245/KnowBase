"""HTTP contracts for assessments; grading and mutations live in services."""
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt, QuizRun, WeakKnowledgeState
from app.models.learning import KnowledgePoint, QuizQuestion
from app.schemas.assessment import (LearningTaskStatus, MistakeMasteryStatus, MistakeRedoRequest,
    PaperSubmitRequest, QuestionSubmitRequest, QuizRunCreateRequest, QuizSetGenerateRequest)
from app.services import assessment_service as service, assessment_workflows as workflows
from app.services.assessment_ai import AssessmentAIError

router = APIRouter(prefix="/learning", tags=["assessments"])
DB = Annotated[AsyncSession, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


async def _call(operation):
    try:
        return await operation
    except (service.AssessmentServiceError, AssessmentAIError) as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/quiz-sets/generate")
async def generate_quiz_set(payload: QuizSetGenerateRequest, db: DB, settings: Config):
    paper = await _call(service.generate_quiz_set(db, payload, settings))
    return await workflows.set_view(db, paper.id)


@router.get("/quiz-sets/{quiz_set_id}")
async def get_quiz_set(quiz_set_id: str, db: DB):
    return await _call(workflows.set_view(db, quiz_set_id))


@router.post("/quiz-sets/{quiz_set_id}/runs")
async def create_run(quiz_set_id: str, db: DB, payload: QuizRunCreateRequest | None = Body(None)):
    payload = payload or QuizRunCreateRequest()
    run = await _call(service.create_quiz_run(db, quiz_set_id,
        resume=payload.resume_unsubmitted, answer_mode=payload.answer_mode))
    return await workflows.run_view(db, run)


@router.post("/quiz-runs/{run_id}/start")
async def start_run(run_id: str, db: DB):
    return await workflows.run_view(db, await _call(service.start_quiz_run(db, run_id)))


async def _attempt_result(db, attempt):
    return {"attempt": service.serialize_attempt(attempt),
            "run": await workflows.run_view(db, await service._quiz_run(db, attempt.quiz_run_id))}


@router.post("/quiz-runs/{run_id}/questions/{question_id}/submit")
async def submit_question(run_id: str, question_id: str, payload: QuestionSubmitRequest, db: DB, settings: Config):
    attempt = await _call(service.submit_question(db, run_id, question_id, payload, settings))
    return await _attempt_result(db, attempt)


@router.post("/quiz-runs/{run_id}/submit")
async def submit_paper(run_id: str, payload: PaperSubmitRequest, db: DB, settings: Config):
    run = await _call(service.submit_paper(db, run_id, payload, settings))
    return await workflows.run_view(db, run)


@router.post("/quiz-runs/{run_id}/retry")
async def retry_run(run_id: str, db: DB):
    run = await _call(service._quiz_run(db, run_id))
    if run.status != "submitted":
        raise HTTPException(409, "Only a submitted run can be retried")
    new_run = await _call(service.create_quiz_run(db, run.quiz_set_id, answer_mode=run.answer_mode, question_ids=run.question_ids))
    return await workflows.run_view(db, new_run)


@router.post("/attempts/{attempt_id}/retry-grading")
async def retry_grading(attempt_id: str, db: DB, settings: Config):
    attempt = await _call(service.retry_grading(db, attempt_id, settings))
    return await _attempt_result(db, attempt)


class ListScope(BaseModel):
    workspace_id: str | None = None
    document_id: str | None = None
    knowledge_point_id: str | None = None
    limit: int = 50
    offset: int = 0


def list_scope(workspace_id: str | None = None, document_id: str | None = None,
               knowledge_point_id: str | None = None, limit: int = Query(50, ge=1, le=200),
               offset: int = Query(0, ge=0)):
    return ListScope(workspace_id=workspace_id, document_id=document_id,
                     knowledge_point_id=knowledge_point_id, limit=limit, offset=offset)


Scope = Annotated[ListScope, Depends(list_scope)]


def _scope(query, model, scope, *, question=False):
    if scope.workspace_id:
        query = query.where(model.workspace_id == scope.workspace_id)
    if scope.knowledge_point_id:
        query = query.where(model.knowledge_point_id == scope.knowledge_point_id)
    if scope.document_id:
        predicate = KnowledgePoint.document_id == scope.document_id
        if question:
            predicate = or_(predicate, QuizQuestion.document_id == scope.document_id)
        query = query.where(predicate)
    return query


async def _page(db, query, scope, render):
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (await db.execute(query.limit(scope.limit).offset(scope.offset))).all()
    return {"items": [render(*row) for row in rows], "total": total,
            "limit": scope.limit, "offset": scope.offset}


def _mistake(record, question, point, recoverable=None):
    return {**workflows.serialize_row(record), "question": service.serialize_question(question, reveal=True),
            "recoverable_redo_attempt": service.serialize_attempt(recoverable) if recoverable else None,
            "document_id": question.document_id or (point.document_id if point else None),
            "knowledge_point_title": point.title if point else None,
            "source_label": question.source_label, "source_type": "chat" if question.origin_message_id else "quiz"}


async def _recoverable_redos(db, question_ids):
    if not question_ids:
        return {}
    rows = (await db.execute(select(QuizAttempt, QuizRun)
        .join(QuizRun, QuizRun.id == QuizAttempt.quiz_run_id)
        .join(QuizQuestion, QuizQuestion.id == QuizAttempt.question_id)
        .where(QuizAttempt.question_id.in_(question_ids), QuizRun.question_ids.is_not(None),
            QuizAttempt.evaluation_status.in_(["pending_ai", "grading_failed"]),
            QuizQuestion.question_type.in_(["short_answer", "concept_explanation"]))
        .order_by(QuizAttempt.submitted_at.desc(), QuizRun.round_number.desc(), QuizAttempt.id.desc()))).all()
    recovered = {}
    for attempt, run in rows:
        if attempt.question_id in run.question_ids:
            recovered.setdefault(attempt.question_id, attempt)
    return recovered


@router.get("/mistakes")
async def list_mistakes(db: DB, scope: Scope, mastery_status: MistakeMasteryStatus | None = None):
    query = select(MistakeRecord, QuizQuestion, KnowledgePoint).join(QuizQuestion, QuizQuestion.id == MistakeRecord.question_id)
    query = query.outerjoin(KnowledgePoint, KnowledgePoint.id == MistakeRecord.knowledge_point_id)
    query = _scope(query, MistakeRecord, scope, question=True)
    if mastery_status:
        query = query.where(MistakeRecord.mastery_status == mastery_status)
    page = await _page(db, query.order_by(MistakeRecord.last_wrong_at.desc(), MistakeRecord.id), scope, _mistake)
    recovered = await _recoverable_redos(db, [item["question_id"] for item in page["items"]])
    for item in page["items"]:
        attempt = recovered.get(item["question_id"])
        item["recoverable_redo_attempt"] = service.serialize_attempt(attempt) if attempt else None
    return page


@router.post("/mistakes/{mistake_id}/redo")
async def redo_mistake(mistake_id: str, payload: MistakeRedoRequest, db: DB, settings: Config):
    mistake = await db.get(MistakeRecord, mistake_id)
    if mistake is None:
        raise HTTPException(404, "Mistake not found")
    attempt = await _call(workflows.standalone_submission(db, mistake.question_id,
        QuestionSubmitRequest(**payload.model_dump()), settings, is_redo=True))
    await db.refresh(mistake)
    question = await db.get(QuizQuestion, mistake.question_id)
    point = await db.get(KnowledgePoint, mistake.knowledge_point_id) if mistake.knowledge_point_id else None
    recovered = await _recoverable_redos(db, [question.id])
    return {**(await _attempt_result(db, attempt)), "mistake": _mistake(mistake, question, point, recovered.get(question.id))}


def _point_record(row, point):
    return {**workflows.serialize_row(row), "knowledge_point_title": point.title if point else None,
            "document_id": point.document_id if point else None,
            "source_page": point.source_page if point else None,
            "source_heading": point.source_heading if point else None}


@router.get("/weak-knowledge")
async def list_weak_knowledge(db: DB, scope: Scope):
    query = select(WeakKnowledgeState, KnowledgePoint).join(KnowledgePoint, KnowledgePoint.id == WeakKnowledgeState.knowledge_point_id)
    query = _scope(query, WeakKnowledgeState, scope)
    return await _page(db, query.order_by(WeakKnowledgeState.weakness_score.desc(), WeakKnowledgeState.id), scope, _point_record)


class RecalculateScope(BaseModel):
    workspace_id: str | None = None
    document_id: str | None = None
    knowledge_point_id: str | None = None


@router.post("/weak-knowledge/recalculate")
async def recalculate_weak_knowledge(db: DB, payload: RecalculateScope | None = Body(None)):
    scope = payload or RecalculateScope()
    ids = await _call(workflows.recalculate_scope(db, **scope.model_dump()))
    return {"recalculated_count": len(ids), "knowledge_point_ids": ids}


@router.get("/tasks")
async def list_tasks(db: DB, scope: Scope, status: LearningTaskStatus | None = None,
                     due_before: datetime | None = None, due_after: datetime | None = None):
    query = select(LearningTask, KnowledgePoint).outerjoin(KnowledgePoint, KnowledgePoint.id == LearningTask.knowledge_point_id)
    query = _scope(query, LearningTask, scope)
    if status:
        query = query.where(LearningTask.status == status)
    if due_before:
        query = query.where(LearningTask.due_at <= service._as_utc(due_before))
    if due_after:
        query = query.where(LearningTask.due_at >= service._as_utc(due_after))
    return await _page(db, query.order_by(LearningTask.priority.desc(), LearningTask.due_at, LearningTask.id), scope, _point_record)


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: str, db: DB):
    task = await _call(workflows.complete_task(db, task_id))
    point = await db.get(KnowledgePoint, task.knowledge_point_id) if task.knowledge_point_id else None
    return _point_record(task, point)
