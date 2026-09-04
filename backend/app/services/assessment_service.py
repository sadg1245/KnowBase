"""Transactional orchestration for quiz generation, runs, and submissions."""

from __future__ import annotations

import asyncio
import json
import weakref
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assessment import MistakeRecord, QuizAttempt, QuizRun, QuizSet, WeakKnowledgeState
from app.models.chat import DocumentChunk
from app.models.document import Document
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.models.workspace import Workspace
from app.schemas.assessment import PaperSubmitRequest, QuestionSubmitRequest, QuizSetGenerateRequest
from app.services.assessment_ai import (
    OBJECTIVE_TYPES,
    SUBJECTIVE_TYPES,
    AssessmentAIError,
    Completion,
    build_generated_paper,
    evaluate_subjective,
)
from app.services.assessment_scoring import (
    MistakeState,
    elapsed_seconds,
    grade_objective,
    next_mistake_state,
)
from app.services.weakness_service import recalculate_knowledge_point, upsert_weak_learning_tasks


class AssessmentServiceError(RuntimeError):
    """A service-layer failure with a stable HTTP mapping for later routes."""

    status_code = 500

    def __init__(self, message: str):
        super().__init__(message)


class AssessmentNotFoundError(AssessmentServiceError, LookupError):
    status_code = 404


class AssessmentScopeError(AssessmentServiceError, ValueError):
    status_code = 400


class AssessmentStateError(AssessmentServiceError):
    status_code = 409


class AssessmentValidationError(AssessmentServiceError, ValueError):
    status_code = 422


_LOCKS_BY_LOOP: weakref.WeakKeyDictionary[
    Any,
    weakref.WeakValueDictionary[str, asyncio.Lock],
] = weakref.WeakKeyDictionary()


def _lock_key(db: AsyncSession, namespace: str, entity_id: str) -> str:
    return f"{id(db.get_bind())}:{namespace}:{entity_id}"


@asynccontextmanager
async def _process_lock(db: AsyncSession, namespace: str, entity_id: str):
    if db.get_bind().dialect.name != "sqlite":
        yield
        return
    loop = asyncio.get_running_loop()
    locks = _LOCKS_BY_LOOP.setdefault(loop, weakref.WeakValueDictionary())
    key = _lock_key(db, namespace, entity_id)
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    async with lock:
        yield


async def _clean_transaction(db: AsyncSession) -> None:
    if db.in_transaction():
        await db.commit()


async def _begin_write_transaction(db: AsyncSession) -> None:
    """Lock SQLite writers across engines/processes before reading mutable state."""
    if db.get_bind().dialect.name == "sqlite":
        await db.execute(text("BEGIN IMMEDIATE"))


@dataclass(frozen=True)
class _PreparedGrade:
    user_answer: Any
    evaluation_status: str
    is_correct: bool | None
    score: float | None
    max_score: float
    feedback: Any
    error_reason: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _legacy_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _iso(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _run_elapsed(run: QuizRun, finished_at: datetime, limit: int | None) -> int:
    if run.started_at is None:
        return 0
    return elapsed_seconds(_as_utc(run.started_at), _as_utc(finished_at), limit)


async def _workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    row = await db.get(Workspace, workspace_id)
    if row is None:
        raise AssessmentNotFoundError("Workspace not found")
    return row


async def _documents_in_scope(
    db: AsyncSession,
    workspace_id: str,
    document_ids: Sequence[str],
) -> list[Document]:
    requested_ids = _stable_unique(document_ids)
    if not requested_ids:
        return []
    rows = (
        await db.execute(select(Document).where(Document.id.in_(requested_ids)))
    ).scalars().all()
    rows_by_id = {row.id: row for row in rows}
    missing = [document_id for document_id in requested_ids if document_id not in rows_by_id]
    if missing:
        raise AssessmentNotFoundError("Document not found: " + ", ".join(missing))
    cross_scope = [row.id for row in rows if row.workspace_id != workspace_id]
    if cross_scope:
        raise AssessmentScopeError("Documents do not belong to the selected workspace")
    return [rows_by_id[document_id] for document_id in requested_ids]


async def _points_in_scope(
    db: AsyncSession,
    workspace_id: str,
    point_ids: Sequence[str],
) -> list[KnowledgePoint]:
    requested_ids = _stable_unique(point_ids)
    if not requested_ids:
        return []
    rows = (
        await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(requested_ids)))
    ).scalars().all()
    rows_by_id = {row.id: row for row in rows}
    missing = [point_id for point_id in requested_ids if point_id not in rows_by_id]
    if missing:
        raise AssessmentNotFoundError("Knowledge point not found: " + ", ".join(missing))
    if any(row.workspace_id != workspace_id for row in rows):
        raise AssessmentScopeError("Knowledge points do not belong to the selected workspace")
    return [rows_by_id[point_id] for point_id in requested_ids]


def _chunk_matches_sections(chunk: DocumentChunk, section_filters: Sequence[str]) -> bool:
    filters = {value.strip().casefold() for value in section_filters if value.strip()}
    if not filters:
        return True
    sections = {
        value.strip().casefold()
        for value in [chunk.heading or "", *(chunk.section_path or [])]
        if isinstance(value, str) and value.strip()
    }
    return bool(filters & sections)


def _chunk_matches_point_evidence(chunk: DocumentChunk, point: KnowledgePoint) -> bool:
    """Require a default weak point to have an unambiguous source slice."""
    if point.document_id and chunk.document_id != point.document_id:
        return False
    if point.source_page is not None and chunk.page_num == point.source_page:
        return True
    if point.source_heading:
        heading = point.source_heading.strip().casefold()
        return heading == (chunk.heading or "").strip().casefold() or heading in {
            value.strip().casefold() for value in (chunk.section_path or []) if isinstance(value, str)
        }
    return False


async def _generation_scope(
    db: AsyncSession,
    request: QuizSetGenerateRequest,
) -> tuple[list[Document], list[KnowledgePoint], list[DocumentChunk]]:
    await _workspace(db, request.workspace_id)
    points = await _points_in_scope(db, request.workspace_id, request.knowledge_point_ids)
    documents = await _documents_in_scope(db, request.workspace_id, request.document_ids)

    if documents and points:
        document_ids = {document.id for document in documents}
        if any(point.document_id and point.document_id not in document_ids for point in points):
            raise AssessmentScopeError("Knowledge points fall outside the selected document scope")

    if not documents:
        point_document_ids = _stable_unique(
            point.document_id for point in points if point.document_id
        )
        if point_document_ids:
            documents = await _documents_in_scope(db, request.workspace_id, point_document_ids)
        else:
            documents = (
                await db.execute(
                    select(Document)
                    .where(
                        Document.workspace_id == request.workspace_id,
                        Document.status == "ready",
                    )
                    .order_by(Document.created_at, Document.id)
                )
            ).scalars().all()

    if not documents:
        raise AssessmentValidationError("No ready documents are available for assessment generation")
    unavailable = [document.id for document in documents if document.status != "ready"]
    if unavailable:
        raise AssessmentValidationError("Selected documents are not ready: " + ", ".join(unavailable))

    document_ids = [document.id for document in documents]
    chunks = (
        await db.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.workspace_id == request.workspace_id,
                DocumentChunk.document_id.in_(document_ids),
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.id)
        )
    ).scalars().all()
    chunks = [chunk for chunk in chunks if _chunk_matches_sections(chunk, request.section_filters)]
    if not chunks:
        raise AssessmentValidationError("No source chunks match the selected assessment scope")
    if not points:
        candidates = (await db.execute(
            select(KnowledgePoint)
            .join(
                WeakKnowledgeState,
                WeakKnowledgeState.knowledge_point_id == KnowledgePoint.id,
            )
            .where(
                KnowledgePoint.workspace_id == request.workspace_id,
                KnowledgePoint.document_id.in_(document_ids),
                WeakKnowledgeState.weakness_score > 0,
            )
            .order_by(
                WeakKnowledgeState.weakness_score.desc(),
                KnowledgePoint.importance.desc(),
                KnowledgePoint.id,
            )
        )).scalars().all()
        for candidate in candidates:
            point_chunks = [
                chunk for chunk in chunks if _chunk_matches_point_evidence(chunk, candidate)
            ]
            if point_chunks:
                points = [candidate]
                chunks = point_chunks
                break
    return documents, points, chunks


def _question_point_id(question: Any, points: Sequence[KnowledgePoint]) -> str | None:
    if len(points) == 1:
        return points[0].id
    source_document_ids = {
        source.get("document_id")
        for source in question.source_snapshot
        if isinstance(source, dict) and source.get("document_id")
    }
    matches = [point.id for point in points if point.document_id in source_document_ids]
    return matches[0] if len(matches) == 1 else None


def _source_label(snapshot: Sequence[dict[str, Any]]) -> str | None:
    if not snapshot:
        return None
    source = snapshot[0]
    label = source.get("source_file") or source.get("document_id")
    page = source.get("page")
    return f"{label} · p.{page}" if label and page is not None else label


async def generate_quiz_set(
    db: AsyncSession,
    request: QuizSetGenerateRequest,
    settings: Settings,
    completion: Completion | None = None,
) -> QuizSet:
    """Validate a generation scope, call the configured AI, and persist atomically."""
    documents, points, evidence = await _generation_scope(db, request)
    evidence_payload = [{
        "id": chunk.id,
        "document_id": chunk.document_id,
        "source_file": chunk.source_file,
        "page_num": chunk.page_num,
        "heading": chunk.heading,
        "section_path": list(chunk.section_path or []),
        "content": chunk.content,
    } for chunk in evidence]
    quiz_set = QuizSet(
        workspace_id=request.workspace_id,
        title=request.title or "Assessment",
        document_ids=[document.id for document in documents],
        knowledge_point_ids=[point.id for point in points],
        section_filters=list(request.section_filters),
        question_count=request.count,
        difficulty=request.difficulty,
        question_types=list(request.question_types),
        strict_sources=request.strict_sources,
        answer_mode=request.answer_mode,
        duration_limit_seconds=request.duration_limit_seconds,
        status="generating",
    )
    db.add(quiz_set)
    await db.commit()
    quiz_set_id = quiz_set.id

    try:
        paper = await build_generated_paper(evidence_payload, request, settings, completion)
    except Exception as exc:
        try:
            persisted_set = (
                await db.execute(
                    select(QuizSet).where(QuizSet.id == quiz_set_id).with_for_update()
                )
            ).scalar_one()
            persisted_set.status = "failed"
            persisted_set.generation_error = str(exc)
            await db.commit()
            quiz_set = persisted_set
        except SQLAlchemyError as persistence_error:
            await db.rollback()
            raise AssessmentServiceError("Could not persist failed assessment generation") from persistence_error
        raise

    try:
        persisted_set = (
            await db.execute(
                select(QuizSet).where(QuizSet.id == quiz_set_id).with_for_update()
            )
        ).scalar_one()
        if persisted_set.status != "generating":
            raise AssessmentStateError("Quiz set generation is no longer pending")
        questions: list[QuizQuestion] = []
        for position, generated in enumerate(paper.questions, start=1):
            source_snapshot = [dict(source) for source in generated.source_snapshot]
            document_id = next(
                (
                    source.get("document_id")
                    for source in source_snapshot
                    if source.get("document_id")
                ),
                None,
            )
            questions.append(QuizQuestion(
                workspace_id=request.workspace_id,
                quiz_set_id=persisted_set.id,
                document_id=document_id,
                knowledge_point_id=_question_point_id(generated, points),
                question_type=generated.question_type,
                prompt=generated.prompt,
                options=list(generated.options) or None,
                answer=_legacy_text(generated.answer_payload),
                difficulty_level=generated.difficulty,
                answer_payload=generated.answer_payload,
                grading_rubric=dict(generated.grading_rubric),
                source_snapshot=source_snapshot,
                strict_sources=request.strict_sources,
                generation_model=paper.generation_model,
                position=position,
                explanation=generated.explanation,
                source_label=_source_label(source_snapshot),
            ))
        db.add_all(questions)
        persisted_set.question_count = len(questions)
        persisted_set.generation_model = paper.generation_model
        persisted_set.generation_error = None
        persisted_set.status = "ready"
        await db.commit()
        return persisted_set
    except AssessmentServiceError:
        await db.rollback()
        raise
    except SQLAlchemyError as exc:
        await db.rollback()
        try:
            failed_set = await db.get(QuizSet, quiz_set_id)
            if failed_set is not None:
                failed_set.status = "failed"
                failed_set.generation_error = "Could not persist generated assessment"
                await db.commit()
        except SQLAlchemyError as persistence_error:
            await db.rollback()
            raise AssessmentServiceError(
                "Could not persist failed assessment generation"
            ) from persistence_error
        raise AssessmentServiceError("Could not persist generated assessment") from exc
    except Exception:
        await db.rollback()
        raise


async def _quiz_set(db: AsyncSession, quiz_set_id: str) -> QuizSet:
    row = await db.get(QuizSet, quiz_set_id)
    if row is None:
        raise AssessmentNotFoundError("Quiz set not found")
    return row


async def _quiz_run(db: AsyncSession, run_id: str) -> QuizRun:
    row = await db.get(QuizRun, run_id)
    if row is None:
        raise AssessmentNotFoundError("Quiz run not found")
    return row


async def create_quiz_run(
    db: AsyncSession,
    quiz_set_id: str,
    *,
    resume: bool = False,
    answer_mode: str | None = None,
    question_ids: Sequence[str] | None = None,
) -> QuizRun:
    """Create a monotonic answer round, or explicitly resume an unfinished one."""
    async with _process_lock(db, "round", quiz_set_id):
        await _clean_transaction(db)
        try:
            await _begin_write_transaction(db)
            quiz_set = (
                await db.execute(
                    select(QuizSet).where(QuizSet.id == quiz_set_id).with_for_update()
                )
            ).scalar_one_or_none()
            if quiz_set is None:
                raise AssessmentNotFoundError("Quiz set not found")
            if quiz_set.status != "ready":
                raise AssessmentStateError("Quiz set is not ready")
            if answer_mode is not None and answer_mode not in {"sequential", "full_paper"}:
                raise AssessmentValidationError("Unsupported answer mode")
            scope = None if question_ids is None else _stable_unique(question_ids)
            if scope is not None:
                if not scope:
                    raise AssessmentValidationError("A scoped run needs at least one question")
                rows = (await db.execute(select(QuizQuestion).where(QuizQuestion.id.in_(scope)))).scalars().all()
                if len(rows) != len(scope):
                    raise AssessmentNotFoundError("Question not found")
                if any(row.quiz_set_id != quiz_set_id or row.workspace_id != quiz_set.workspace_id for row in rows):
                    raise AssessmentScopeError("Questions are outside this quiz set")
            latest = (
                await db.execute(
                    select(QuizRun)
                    .where(QuizRun.quiz_set_id == quiz_set_id)
                    .order_by(QuizRun.round_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            resumable = latest
            if resume:
                candidates = (await db.execute(select(QuizRun).where(QuizRun.quiz_set_id == quiz_set_id)
                    .order_by(QuizRun.round_number.desc()))).scalars().all()
                resumable = next((row for row in candidates if row.question_ids == scope), None)
            if resume and resumable is not None and resumable.status != "submitted":
                if answer_mode and answer_mode != resumable.answer_mode:
                    raise AssessmentStateError("Cannot change the mode of an existing run")
                await db.commit()
                return resumable
            run = QuizRun(
                quiz_set_id=quiz_set_id,
                round_number=(latest.round_number + 1) if latest else 1,
                answer_mode=answer_mode or quiz_set.answer_mode,
                question_ids=scope,
                status="not_started",
            )
            db.add(run)
            await db.commit()
            return run
        except AssessmentServiceError:
            await db.rollback()
            raise
        except IntegrityError as exc:
            await db.rollback()
            raise AssessmentStateError("A quiz run round was created concurrently; retry") from exc
        except SQLAlchemyError as exc:
            await db.rollback()
            raise AssessmentServiceError("Could not create quiz run") from exc
        except Exception:
            await db.rollback()
            raise


async def start_quiz_run(
    db: AsyncSession,
    run_id: str,
    now: datetime | None = None,
) -> QuizRun:
    """Start a run once; repeated starts preserve the server timestamp."""
    async with _process_lock(db, "run", run_id):
        await _clean_transaction(db)
        try:
            await _begin_write_transaction(db)
            run = (
                await db.execute(
                    select(QuizRun).where(QuizRun.id == run_id).with_for_update()
                )
            ).scalar_one_or_none()
            if run is None:
                raise AssessmentNotFoundError("Quiz run not found")
            if run.status == "submitted":
                raise AssessmentStateError("Submitted quiz runs cannot be restarted")
            if run.status == "not_started":
                run.status = "in_progress"
                run.started_at = now or _now()
            elif run.status != "in_progress":
                raise AssessmentStateError("Quiz run has an invalid status")
            await db.commit()
            return run
        except AssessmentServiceError:
            await db.rollback()
            raise
        except SQLAlchemyError as exc:
            await db.rollback()
            raise AssessmentServiceError("Could not start quiz run") from exc
        except Exception:
            await db.rollback()
            raise


def _mistake_state(record: MistakeRecord | None) -> MistakeState | None:
    if record is None:
        return None
    return MistakeState(
        wrong_count=record.wrong_count,
        redo_count=record.redo_count,
        consecutive_correct=record.consecutive_correct,
        mastery_status=record.mastery_status,
        first_wrong_at=record.first_wrong_at,
        last_wrong_at=record.last_wrong_at,
        last_redone_at=record.last_redone_at,
        resolved_at=record.resolved_at,
    )


def _apply_mistake_state(record: MistakeRecord, state: MistakeState) -> None:
    record.wrong_count = state.wrong_count
    record.redo_count = state.redo_count
    record.consecutive_correct = state.consecutive_correct
    record.mastery_status = state.mastery_status
    record.first_wrong_at = state.first_wrong_at
    record.last_wrong_at = state.last_wrong_at
    record.last_redone_at = state.last_redone_at
    record.resolved_at = state.resolved_at


async def _update_mistake(
    db: AsyncSession,
    question: QuizQuestion,
    attempt: QuizAttempt,
    *,
    correct: bool,
    is_redo: bool,
    submitted_at: datetime,
) -> None:
    record = (
        await db.execute(
            select(MistakeRecord)
            .where(MistakeRecord.question_id == question.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    state = next_mistake_state(
        _mistake_state(record),
        correct=correct,
        is_redo=is_redo,
        now=submitted_at,
    )
    if state is None:
        return
    if record is None:
        record = MistakeRecord(
            question_id=question.id,
            knowledge_point_id=question.knowledge_point_id,
            workspace_id=question.workspace_id,
        )
        db.add(record)
    record.latest_attempt_id = attempt.id
    record.user_answer_snapshot = attempt.user_answer
    record.correct_answer_snapshot = question.answer_payload
    record.error_reason = attempt.error_reason
    record.source_snapshot = list(question.source_snapshot or [])
    _apply_mistake_state(record, state)


async def _update_point_mastery(
    db: AsyncSession,
    point_id: str | None,
    *,
    correct: bool,
) -> None:
    if point_id is None:
        return
    point = (
        await db.execute(
            select(KnowledgePoint)
            .where(KnowledgePoint.id == point_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if point is None:
        return
    point.mastery = round(max(0.0, min(1.0, point.mastery + (0.12 if correct else -0.08))), 6)
    point.mastery_status = "mastered" if point.mastery >= 0.8 else "learning"


async def _recompute_run(db: AsyncSession, run: QuizRun) -> None:
    graded = (
        await db.execute(
            select(QuizAttempt).where(
                QuizAttempt.quiz_run_id == run.id,
                QuizAttempt.evaluation_status == "graded",
            )
        )
    ).scalars().all()
    if run.question_ids is not None:
        graded = [attempt for attempt in graded if attempt.question_id in run.question_ids]
    run.graded_count = len(graded)
    run.correct_count = sum(1 for attempt in graded if attempt.is_correct is True)
    run.score = round(sum(float(attempt.score or 0.0) for attempt in graded), 6)
    run.max_score = round(sum(float(attempt.max_score) for attempt in graded), 6)


async def _finish_if_complete(
    db: AsyncSession,
    run: QuizRun,
    quiz_set: QuizSet,
    submitted_at: datetime,
) -> None:
    answered_count = await db.scalar(
        select(func.count(func.distinct(QuizAttempt.question_id))).where(
            QuizAttempt.quiz_run_id == run.id
        )
    )
    required = len(run.question_ids) if run.question_ids is not None else quiz_set.question_count
    if int(answered_count or 0) < required:
        return
    run.status = "submitted"
    run.submitted_at = submitted_at
    run.elapsed_seconds = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)


async def _submission_context(
    db: AsyncSession,
    run_id: str,
    question_id: str,
) -> tuple[QuizRun, QuizSet, QuizQuestion]:
    run = await _quiz_run(db, run_id)
    if run.status != "in_progress" or run.started_at is None:
        raise AssessmentStateError("Quiz run must be started before submission")
    quiz_set = await _quiz_set(db, run.quiz_set_id)
    question = await db.get(QuizQuestion, question_id)
    if question is None:
        raise AssessmentNotFoundError("Quiz question not found")
    if question.quiz_set_id != run.quiz_set_id:
        raise AssessmentScopeError("Question does not belong to this quiz run")
    _check_question_scope(run, question.id)
    existing = await db.scalar(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_run_id == run.id,
            QuizAttempt.question_id == question.id,
        )
    )
    if int(existing or 0):
        raise AssessmentStateError("This question has already been submitted in this quiz run")
    return run, quiz_set, question


def _check_question_scope(run: QuizRun, question_id: str) -> None:
    if run.question_ids is not None and question_id not in run.question_ids:
        raise AssessmentScopeError("Question is outside this run's fixed scope")


async def _prepare_grade(
    question: QuizQuestion,
    user_answer: Any,
    settings: Settings,
    completion: Completion | None,
) -> _PreparedGrade:
    evaluation_status = "graded"
    feedback: Any = None
    error_reason: str | None = None
    is_correct: bool | None
    score: float | None
    max_score: float
    if question.question_type in OBJECTIVE_TYPES:
        result = grade_objective(question.question_type, question.answer_payload, user_answer)
        is_correct = result.is_correct
        score = result.score
        max_score = result.max_score
        feedback = result.feedback
        error_reason = result.error_reason
    elif question.question_type in SUBJECTIVE_TYPES:
        try:
            result = await evaluate_subjective(question, user_answer, settings, completion)
        except AssessmentAIError as exc:
            evaluation_status = "grading_failed"
            is_correct = None
            score = None
            max_score = 1.0
            feedback = {
                "message": str(exc),
                "retryable": True,
                "status_code": exc.status_code,
            }
            error_reason = str(exc)
        else:
            is_correct = result.is_correct
            score = result.score
            max_score = result.max_score
            feedback = {
                "message": result.feedback,
                "matched_points": list(result.matched_points),
                "missing_points": list(result.missing_points),
            }
            error_reason = result.error_reason
    else:
        raise AssessmentValidationError("Unsupported assessment question type")
    return _PreparedGrade(
        user_answer=user_answer,
        evaluation_status=evaluation_status,
        is_correct=is_correct,
        score=score,
        max_score=max_score,
        feedback=feedback,
        error_reason=error_reason,
    )


@asynccontextmanager
async def _submission_locks(
    db: AsyncSession,
    run_id: str,
    questions: Sequence[QuizQuestion],
):
    lock_targets = [
        ("run", run_id),
        *(("question", question.id) for question in sorted(questions, key=lambda row: row.id)),
        *(("point", point_id) for point_id in sorted({
            question.knowledge_point_id
            for question in questions
            if question.knowledge_point_id is not None
        })),
    ]
    async with AsyncExitStack() as stack:
        for namespace, entity_id in lock_targets:
            await stack.enter_async_context(_process_lock(db, namespace, entity_id))
        yield


async def _locked_run(db: AsyncSession, run_id: str) -> QuizRun:
    run = (
        await db.execute(
            select(QuizRun)
            .where(QuizRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None:
        raise AssessmentNotFoundError("Quiz run not found")
    return run


async def _locked_question(db: AsyncSession, question_id: str) -> QuizQuestion:
    question = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.id == question_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if question is None:
        raise AssessmentNotFoundError("Quiz question not found")
    return question


async def _question_duration(
    db: AsyncSession,
    run: QuizRun,
    quiz_set: QuizSet,
    submitted_at: datetime,
    claimed_duration: int,
) -> int:
    server_elapsed = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)
    recorded_duration = await db.scalar(
        select(func.coalesce(func.sum(QuizAttempt.duration_seconds), 0)).where(
            QuizAttempt.quiz_run_id == run.id
        )
    )
    available = max(0, server_elapsed - int(recorded_duration or 0))
    return min(max(0, int(claimed_duration)), available)


async def _persist_prepared_attempt(
    db: AsyncSession,
    run: QuizRun,
    question: QuizQuestion,
    grade: _PreparedGrade,
    *,
    duration: int,
    submitted_at: datetime,
    is_redo: bool,
    record_activity: bool,
) -> QuizAttempt:
    attempt = QuizAttempt(
        quiz_set_id=run.quiz_set_id,
        quiz_run_id=run.id,
        question_id=question.id,
        attempt_number=1,
        user_answer=grade.user_answer,
        is_correct=grade.is_correct,
        score=grade.score,
        max_score=grade.max_score,
        evaluation_status=grade.evaluation_status,
        feedback=grade.feedback,
        error_reason=grade.error_reason,
        duration_seconds=duration,
        submitted_at=submitted_at,
    )
    db.add(attempt)
    await db.flush()

    question.last_answer = _legacy_text(grade.user_answer)
    await _apply_grade_effects(db, question, attempt, is_redo=is_redo, now=submitted_at)

    if record_activity:
        db.add(StudyActivity(
            workspace_id=question.workspace_id,
            activity_type="quiz",
            title="Completed an assessment question",
            duration_seconds=duration,
            payload={
                "quiz_set_id": run.quiz_set_id,
                "quiz_run_id": run.id,
                "question_id": question.id,
                "attempt_id": attempt.id,
                "evaluation_status": grade.evaluation_status,
                "correct": grade.is_correct,
                "is_redo": is_redo,
            },
            created_at=submitted_at,
        ))
    await db.flush()
    if question.knowledge_point_id:
        state = await recalculate_knowledge_point(db, question.knowledge_point_id, submitted_at)
        await upsert_weak_learning_tasks(db, state, submitted_at)
    return attempt


async def _apply_grade_effects(db, question, attempt, *, is_redo, now):
    """Single owner for successful-grade counters, mistake state and mastery."""
    grade = attempt
    if grade.evaluation_status == "graded":
        question.attempts += 1
        question.correct_attempts += int(grade.is_correct is True)
        question.last_correct = grade.is_correct
        await _update_mistake(
            db,
            question,
            attempt,
            correct=bool(grade.is_correct),
            is_redo=is_redo,
            submitted_at=now,
        )
        await _update_point_mastery(
            db,
            question.knowledge_point_id,
            correct=bool(grade.is_correct),
        )


async def retry_grading(db, attempt_id, settings, completion=None):
    """Evaluate outside locks; compare-and-apply under the submission write locks."""
    attempt = await db.get(QuizAttempt, attempt_id)
    if attempt is None:
        raise AssessmentNotFoundError("Attempt not found")
    question = await db.get(QuizQuestion, attempt.question_id)
    if question is None:
        raise AssessmentNotFoundError("Question not found")
    if question.question_type not in SUBJECTIVE_TYPES or attempt.evaluation_status not in {"pending_ai", "grading_failed"}:
        raise AssessmentStateError("Only failed or pending subjective attempts can be regraded")
    run_id = attempt.quiz_run_id
    answer = attempt.user_answer
    await _clean_transaction(db)
    grade = await _prepare_grade(question, answer, settings, completion)
    async with _submission_locks(db, run_id, [question]):
        try:
            await _begin_write_transaction(db)
            run = await _locked_run(db, run_id)
            question = await _locked_question(db, question.id)
            attempt = (await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id)
                .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if attempt is None:
                raise AssessmentNotFoundError("Attempt not found")
            if attempt.evaluation_status not in {"pending_ai", "grading_failed"}:
                raise AssessmentStateError("Attempt has already been graded")
            _check_question_scope(run, question.id)
            for key in ("evaluation_status", "is_correct", "score", "max_score", "feedback", "error_reason"):
                setattr(attempt, key, getattr(grade, key))
            activities = (await db.execute(select(StudyActivity).where(StudyActivity.workspace_id == question.workspace_id))).scalars().all()
            is_redo = run.question_ids is not None or any(
                (row.payload or {}).get("attempt_id") == attempt.id and (row.payload or {}).get("is_redo")
                for row in activities
            )
            await _apply_grade_effects(db, question, attempt, is_redo=is_redo, now=_now())
            await db.flush()
            await _recompute_run(db, run)
            if question.knowledge_point_id:
                state = await recalculate_knowledge_point(db, question.knowledge_point_id)
                await upsert_weak_learning_tasks(db, state)
            await db.commit()
            return attempt
        except Exception:
            await db.rollback()
            raise


async def _ensure_unsubmitted_question(
    db: AsyncSession,
    run_id: str,
    question_id: str,
) -> None:
    existing = await db.scalar(
        select(func.count(QuizAttempt.id)).where(
            QuizAttempt.quiz_run_id == run_id,
            QuizAttempt.question_id == question_id,
        )
    )
    if int(existing or 0):
        raise AssessmentStateError("This question has already been submitted in this quiz run")


async def submit_question(
    db: AsyncSession,
    run_id: str,
    question_id: str,
    payload: QuestionSubmitRequest,
    settings: Settings,
    completion: Completion | None = None,
    now: datetime | None = None,
    is_redo: bool = False,
) -> QuizAttempt:
    """Grade without a transaction, then atomically persist one question submission."""
    submitted_at = now or _now()
    run, _, question = await _submission_context(db, run_id, question_id)
    if run.answer_mode != "sequential":
        raise AssessmentStateError("Full-paper runs require a paper submission")
    await _clean_transaction(db)
    grade = await _prepare_grade(question, payload.answer, settings, completion)

    async with _submission_locks(db, run_id, [question]):
        try:
            await _begin_write_transaction(db)
            run = await _locked_run(db, run_id)
            if run.status != "in_progress" or run.started_at is None:
                raise AssessmentStateError("Quiz run must be started before submission")
            if run.answer_mode != "sequential":
                raise AssessmentStateError("Full-paper runs require a paper submission")
            quiz_set = await _quiz_set(db, run.quiz_set_id)
            question = await _locked_question(db, question_id)
            if question.quiz_set_id != run.quiz_set_id:
                raise AssessmentScopeError("Question does not belong to this quiz run")
            _check_question_scope(run, question.id)
            await _ensure_unsubmitted_question(db, run.id, question.id)
            duration = await _question_duration(
                db,
                run,
                quiz_set,
                submitted_at,
                payload.duration_seconds,
            )
            attempt = await _persist_prepared_attempt(
                db,
                run,
                question,
                grade,
                duration=duration,
                submitted_at=submitted_at,
                is_redo=is_redo or run.question_ids is not None,
                record_activity=True,
            )
            await _recompute_run(db, run)
            run.elapsed_seconds = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)
            await _finish_if_complete(db, run, quiz_set, submitted_at)
            await db.commit()
            return attempt
        except AssessmentServiceError:
            await db.rollback()
            raise
        except IntegrityError as exc:
            await db.rollback()
            raise AssessmentStateError(
                "This question was submitted concurrently; reload the quiz run"
            ) from exc
        except SQLAlchemyError as exc:
            await db.rollback()
            raise AssessmentServiceError("Could not persist assessment submission") from exc
        except Exception:
            await db.rollback()
            raise


async def submit_paper(
    db: AsyncSession,
    run_id: str,
    answers: PaperSubmitRequest | dict[str, Any],
    settings: Settings,
    completion: Completion | None = None,
    now: datetime | None = None,
) -> QuizRun:
    """Grade a full paper without a write transaction, then persist it atomically."""
    submitted_at = now or _now()
    run = await _quiz_run(db, run_id)
    if run.status != "in_progress" or run.started_at is None:
        raise AssessmentStateError("Quiz run must be started before paper submission")
    if run.answer_mode != "full_paper":
        raise AssessmentStateError("Only full-paper runs accept paper submissions")
    quiz_set = await _quiz_set(db, run.quiz_set_id)
    answer_map = dict(answers.answers if isinstance(answers, PaperSubmitRequest) else answers)
    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_set_id == run.quiz_set_id)
            .order_by(QuizQuestion.position, QuizQuestion.id)
        )
    ).scalars().all()
    questions_by_id = {question.id: question for question in questions}
    if run.question_ids is not None:
        questions = [question for question in questions if question.id in run.question_ids]
        questions_by_id = {question.id: question for question in questions}
    unknown_ids = set(answer_map) - set(questions_by_id)
    if unknown_ids:
        raise AssessmentScopeError("Paper contains answers for questions outside this quiz run")
    supplied_questions = [question for question in questions if question.id in answer_map]
    if supplied_questions:
        existing = await db.scalar(
            select(func.count(QuizAttempt.id)).where(
                QuizAttempt.quiz_run_id == run.id,
                QuizAttempt.question_id.in_([question.id for question in supplied_questions]),
            )
        )
        if int(existing or 0):
            raise AssessmentStateError("This quiz paper contains an already submitted question")

    await _clean_transaction(db)
    prepared_grades = {
        question.id: await _prepare_grade(
            question,
            answer_map[question.id],
            settings,
            completion,
        )
        for question in supplied_questions
    }

    async with _submission_locks(db, run_id, supplied_questions):
        try:
            await _begin_write_transaction(db)
            run = await _locked_run(db, run_id)
            if run.status != "in_progress" or run.started_at is None:
                raise AssessmentStateError("Quiz run must be started before paper submission")
            if run.answer_mode != "full_paper":
                raise AssessmentStateError("Only full-paper runs accept paper submissions")
            quiz_set = await _quiz_set(db, run.quiz_set_id)
            persisted_questions = (
                await db.execute(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_set_id == run.quiz_set_id)
                    .order_by(QuizQuestion.position, QuizQuestion.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars().all()
            persisted_by_id = {question.id: question for question in persisted_questions}
            if run.question_ids is not None:
                persisted_by_id = {key: value for key, value in persisted_by_id.items() if key in run.question_ids}
            if set(answer_map) - set(persisted_by_id):
                raise AssessmentScopeError(
                    "Paper contains answers for questions outside this quiz run"
                )
            for question_id in prepared_grades:
                await _ensure_unsubmitted_question(db, run.id, question_id)
            for question_id, grade in prepared_grades.items():
                await _persist_prepared_attempt(
                    db,
                    run,
                    persisted_by_id[question_id],
                    grade,
                    duration=0,
                    submitted_at=submitted_at,
                    is_redo=run.question_ids is not None,
                    record_activity=False,
                )

            await _recompute_run(db, run)
            run.status = "submitted"
            run.submitted_at = submitted_at
            run.elapsed_seconds = _run_elapsed(
                run,
                submitted_at,
                quiz_set.duration_limit_seconds,
            )
            db.add(StudyActivity(
                workspace_id=quiz_set.workspace_id,
                activity_type="quiz",
                title="Completed an assessment paper",
                duration_seconds=run.elapsed_seconds,
                payload={
                    "quiz_set_id": quiz_set.id,
                    "quiz_run_id": run.id,
                    "graded_count": run.graded_count,
                    "correct_count": run.correct_count,
                },
                created_at=submitted_at,
            ))
            await db.commit()
            return run
        except AssessmentServiceError:
            await db.rollback()
            raise
        except IntegrityError as exc:
            await db.rollback()
            raise AssessmentStateError(
                "This quiz paper was submitted concurrently; reload the quiz run"
            ) from exc
        except SQLAlchemyError as exc:
            await db.rollback()
            raise AssessmentServiceError("Could not persist assessment paper") from exc
        except Exception:
            await db.rollback()
            raise


def serialize_attempt(attempt: QuizAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "quiz_set_id": attempt.quiz_set_id,
        "quiz_run_id": attempt.quiz_run_id,
        "question_id": attempt.question_id,
        "attempt_number": attempt.attempt_number,
        "user_answer": attempt.user_answer,
        "is_correct": attempt.is_correct,
        "score": attempt.score,
        "max_score": attempt.max_score,
        "evaluation_status": attempt.evaluation_status,
        "feedback": attempt.feedback,
        "error_reason": attempt.error_reason,
        "duration_seconds": attempt.duration_seconds,
        "submitted_at": _iso(attempt.submitted_at),
    }


def serialize_question(
    question: QuizQuestion,
    *,
    reveal: bool = False,
    attempt: QuizAttempt | None = None,
) -> dict[str, Any]:
    if attempt is not None and (
        attempt.question_id != question.id
        or attempt.quiz_set_id != question.quiz_set_id
    ):
        raise AssessmentScopeError("Attempt does not belong to this quiz question")
    payload: dict[str, Any] = {
        "id": question.id,
        "quiz_set_id": question.quiz_set_id,
        "workspace_id": question.workspace_id,
        "document_id": question.document_id,
        "knowledge_point_id": question.knowledge_point_id,
        "question_type": question.question_type,
        "prompt": question.prompt,
        "options": question.options,
        "difficulty": question.difficulty_level,
        "position": question.position,
        "source_snapshot": _safe_source_metadata(question.source_snapshot or []),
        "strict_sources": question.strict_sources,
        "generation_model": question.generation_model,
    }
    if attempt is not None:
        payload["attempt"] = serialize_attempt(attempt)
    if reveal:
        payload.update({
            "answer": question.answer,
            "answer_payload": question.answer_payload,
            "explanation": question.explanation,
            "grading_rubric": question.grading_rubric,
            "source_snapshot": list(question.source_snapshot or []),
        })
    return payload


def _safe_source_metadata(snapshots: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    safe_keys = ("chunk_id", "document_id", "source_file", "page")
    return [
        {key: snapshot[key] for key in safe_keys if key in snapshot}
        for snapshot in snapshots
        if isinstance(snapshot, dict)
    ]


def _latest_attempts(attempts: Sequence[QuizAttempt]) -> dict[str, QuizAttempt]:
    latest: dict[str, QuizAttempt] = {}
    for attempt in attempts:
        previous = latest.get(attempt.question_id)
        if previous is None or attempt.attempt_number > previous.attempt_number:
            latest[attempt.question_id] = attempt
    return latest


def serialize_quiz_set(
    quiz_set: QuizSet,
    *,
    questions: Sequence[QuizQuestion] | None = None,
    run: QuizRun | None = None,
    attempts: Sequence[QuizAttempt] | None = None,
) -> dict[str, Any]:
    question_rows = list(questions if questions is not None else quiz_set.__dict__.get("questions", []))
    if run is not None and run.quiz_set_id != quiz_set.id:
        raise AssessmentScopeError("Quiz run does not belong to this quiz set")
    if run is not None and run.question_ids is not None:
        question_rows = [question for question in question_rows if question.id in run.question_ids]
    question_ids: set[str] = set()
    for question in question_rows:
        if question.quiz_set_id != quiz_set.id or question.workspace_id != quiz_set.workspace_id:
            raise AssessmentScopeError("Question does not belong to this quiz set workspace")
        question_ids.add(question.id)
    supplied_attempts = list(attempts or [])
    for attempt in supplied_attempts:
        if attempt.quiz_set_id != quiz_set.id or attempt.question_id not in question_ids:
            raise AssessmentScopeError("Attempt does not belong to this quiz set")
    attempt_rows = [
        attempt
        for attempt in supplied_attempts
        if run is None or attempt.quiz_run_id == run.id
    ]
    latest_attempts = _latest_attempts(attempt_rows)
    reveal_all = run is not None and run.status == "submitted"
    sequential_reveals = (
        set(latest_attempts)
        if run is not None and run.answer_mode == "sequential"
        else set()
    )
    return {
        "id": quiz_set.id,
        "workspace_id": quiz_set.workspace_id,
        "title": quiz_set.title,
        "document_ids": list(quiz_set.document_ids or []),
        "knowledge_point_ids": list(quiz_set.knowledge_point_ids or []),
        "section_filters": list(quiz_set.section_filters or []),
        "question_count": len(run.question_ids) if run is not None and run.question_ids is not None else quiz_set.question_count,
        "difficulty": quiz_set.difficulty,
        "question_types": list(quiz_set.question_types or []),
        "strict_sources": quiz_set.strict_sources,
        "answer_mode": quiz_set.answer_mode,
        "duration_limit_seconds": quiz_set.duration_limit_seconds,
        "status": quiz_set.status,
        "generation_model": quiz_set.generation_model,
        "generation_error": quiz_set.generation_error,
        "created_at": _iso(quiz_set.created_at),
        "updated_at": _iso(quiz_set.updated_at),
        "questions": [
            serialize_question(
                question,
                reveal=reveal_all or question.id in sequential_reveals,
                attempt=latest_attempts.get(question.id),
            )
            for question in sorted(question_rows, key=lambda row: (row.position, row.id))
        ],
    }


def serialize_quiz_run(
    run: QuizRun,
    *,
    quiz_set: QuizSet | None = None,
    questions: Sequence[QuizQuestion] | None = None,
    attempts: Sequence[QuizAttempt] | None = None,
) -> dict[str, Any]:
    supplied_attempts = list(attempts or [])
    question_rows = list(questions or [])
    question_ids = {question.id for question in question_rows}
    for attempt in supplied_attempts:
        if attempt.quiz_set_id != run.quiz_set_id:
            raise AssessmentScopeError("Attempt does not belong to this quiz run's set")
        if questions is not None and attempt.question_id not in question_ids:
            raise AssessmentScopeError("Attempt does not belong to this quiz run's questions")
    attempt_rows = [attempt for attempt in supplied_attempts if attempt.quiz_run_id == run.id]
    for attempt in attempt_rows:
        _check_question_scope(run, attempt.question_id)
    for question in question_rows:
        if question.quiz_set_id != run.quiz_set_id:
            raise AssessmentScopeError("Question does not belong to this quiz run")
    if quiz_set is not None and quiz_set.id != run.quiz_set_id:
        raise AssessmentScopeError("Quiz run does not belong to this quiz set")
    if quiz_set is not None:
        for question in question_rows:
            if question.workspace_id != quiz_set.workspace_id:
                raise AssessmentScopeError("Question does not belong to this quiz set workspace")
    payload: dict[str, Any] = {
        "id": run.id,
        "quiz_set_id": run.quiz_set_id,
        "round_number": run.round_number,
        "answer_mode": run.answer_mode,
        "question_ids": run.question_ids,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "submitted_at": _iso(run.submitted_at),
        "elapsed_seconds": run.elapsed_seconds,
        "score": run.score,
        "max_score": run.max_score,
        "correct_count": run.correct_count,
        "graded_count": run.graded_count,
        "created_at": _iso(run.created_at),
        "updated_at": _iso(run.updated_at),
        "attempts": [serialize_attempt(attempt) for attempt in attempt_rows],
    }
    if quiz_set is not None:
        payload["quiz_set"] = serialize_quiz_set(
            quiz_set,
            questions=questions,
            run=run,
            attempts=attempt_rows,
        )
    return payload
