"""Transactional orchestration for quiz generation, runs, and submissions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.assessment import MistakeRecord, QuizAttempt, QuizRun, QuizSet
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _legacy_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


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
    await db.flush()

    try:
        paper = await build_generated_paper(evidence, request, settings, completion)
    except Exception as exc:
        quiz_set.status = "failed"
        quiz_set.generation_error = str(exc)
        await db.commit()
        await db.refresh(quiz_set)
        raise

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
            quiz_set_id=quiz_set.id,
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
    quiz_set.question_count = len(questions)
    quiz_set.generation_model = paper.generation_model
    quiz_set.generation_error = None
    quiz_set.status = "ready"
    await db.commit()
    await db.refresh(quiz_set)
    return quiz_set


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
) -> QuizRun:
    """Create a monotonic answer round, or explicitly resume an unfinished one."""
    quiz_set = await _quiz_set(db, quiz_set_id)
    if quiz_set.status != "ready":
        raise AssessmentStateError("Quiz set is not ready")
    latest = (
        await db.execute(
            select(QuizRun)
            .where(QuizRun.quiz_set_id == quiz_set_id)
            .order_by(QuizRun.round_number.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if resume and latest is not None and latest.status != "submitted":
        return latest
    run = QuizRun(
        quiz_set_id=quiz_set_id,
        round_number=(latest.round_number + 1) if latest else 1,
        answer_mode=quiz_set.answer_mode,
        status="not_started",
    )
    db.add(run)
    await db.flush()
    return run


async def start_quiz_run(
    db: AsyncSession,
    run_id: str,
    now: datetime | None = None,
) -> QuizRun:
    """Start a run once; repeated starts preserve the server timestamp."""
    run = await _quiz_run(db, run_id)
    if run.status == "submitted":
        raise AssessmentStateError("Submitted quiz runs cannot be restarted")
    if run.status == "not_started":
        run.status = "in_progress"
        run.started_at = now or _now()
        await db.flush()
    elif run.status != "in_progress":
        raise AssessmentStateError("Quiz run has an invalid status")
    return run


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
            select(MistakeRecord).where(MistakeRecord.question_id == question.id)
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
    point = await db.get(KnowledgePoint, point_id)
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
    if int(answered_count or 0) < quiz_set.question_count:
        return
    run.status = "submitted"
    run.submitted_at = submitted_at
    run.elapsed_seconds = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)


async def _submit_question(
    db: AsyncSession,
    run_id: str,
    question_id: str,
    payload: QuestionSubmitRequest,
    settings: Settings,
    completion: Completion | None = None,
    now: datetime | None = None,
    is_redo: bool = False,
    *,
    _record_activity: bool = True,
    _finish_run: bool = True,
) -> QuizAttempt:
    """Persist one immutable answer and all same-transaction compatibility state."""
    submitted_at = now or _now()
    run = await _quiz_run(db, run_id)
    if run.status != "in_progress" or run.started_at is None:
        raise AssessmentStateError("Quiz run must be started before submission")
    quiz_set = await _quiz_set(db, run.quiz_set_id)
    question = await db.get(QuizQuestion, question_id)
    if question is None:
        raise AssessmentNotFoundError("Quiz question not found")
    if question.quiz_set_id != run.quiz_set_id:
        raise AssessmentScopeError("Question does not belong to this quiz run")

    previous_attempt_number = await db.scalar(
        select(func.max(QuizAttempt.attempt_number)).where(
            QuizAttempt.quiz_run_id == run.id,
            QuizAttempt.question_id == question.id,
        )
    )
    attempt_number = int(previous_attempt_number or 0) + 1
    duration = max(0, int(payload.duration_seconds))

    evaluation_status = "graded"
    feedback: Any = None
    error_reason: str | None = None
    is_correct: bool | None
    score: float | None
    max_score: float
    if question.question_type in OBJECTIVE_TYPES:
        result = grade_objective(question.question_type, question.answer_payload, payload.answer)
        is_correct = result.is_correct
        score = result.score
        max_score = result.max_score
        feedback = result.feedback
        error_reason = result.error_reason
    elif question.question_type in SUBJECTIVE_TYPES:
        try:
            result = await evaluate_subjective(question, payload.answer, settings, completion)
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

    attempt = QuizAttempt(
        quiz_set_id=run.quiz_set_id,
        quiz_run_id=run.id,
        question_id=question.id,
        attempt_number=attempt_number,
        user_answer=payload.answer,
        is_correct=is_correct,
        score=score,
        max_score=max_score,
        evaluation_status=evaluation_status,
        feedback=feedback,
        error_reason=error_reason,
        duration_seconds=duration,
        submitted_at=submitted_at,
    )
    db.add(attempt)
    await db.flush()

    if evaluation_status == "graded":
        question.attempts += 1
        question.correct_attempts += int(is_correct is True)
        question.last_answer = _legacy_text(payload.answer)
        question.last_correct = is_correct
        await _update_mistake(
            db,
            question,
            attempt,
            correct=bool(is_correct),
            is_redo=is_redo,
            submitted_at=submitted_at,
        )
        await _update_point_mastery(db, question.knowledge_point_id, correct=bool(is_correct))

    if _record_activity:
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
                "evaluation_status": evaluation_status,
                "correct": is_correct,
            },
            created_at=submitted_at,
        ))

    await db.flush()
    await _recompute_run(db, run)
    run.elapsed_seconds = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)
    if _finish_run:
        await _finish_if_complete(db, run, quiz_set, submitted_at)
    await db.flush()
    return attempt


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
    """Persist one public per-question submission."""
    run = await _quiz_run(db, run_id)
    if run.answer_mode != "sequential":
        raise AssessmentStateError("Full-paper runs require a paper submission")
    return await _submit_question(
        db,
        run_id,
        question_id,
        payload,
        settings,
        completion,
        now,
        is_redo,
    )


async def submit_paper(
    db: AsyncSession,
    run_id: str,
    answers: PaperSubmitRequest | dict[str, Any],
    settings: Settings,
    completion: Completion | None = None,
    now: datetime | None = None,
) -> QuizRun:
    """Grade every supplied full-paper answer and finalize from graded attempts only."""
    submitted_at = now or _now()
    run = await _quiz_run(db, run_id)
    if run.status != "in_progress" or run.started_at is None:
        raise AssessmentStateError("Quiz run must be started before paper submission")
    if run.answer_mode != "full_paper":
        raise AssessmentStateError("Only full-paper runs accept paper submissions")
    quiz_set = await _quiz_set(db, run.quiz_set_id)
    answer_map = answers.answers if isinstance(answers, PaperSubmitRequest) else answers
    questions = (
        await db.execute(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_set_id == run.quiz_set_id)
            .order_by(QuizQuestion.position, QuizQuestion.id)
        )
    ).scalars().all()
    questions_by_id = {question.id: question for question in questions}
    unknown_ids = set(answer_map) - set(questions_by_id)
    if unknown_ids:
        raise AssessmentScopeError("Paper contains answers for questions outside this quiz run")

    for question in questions:
        if question.id not in answer_map:
            continue
        await _submit_question(
            db,
            run.id,
            question.id,
            QuestionSubmitRequest(answer=answer_map[question.id], duration_seconds=0),
            settings,
            completion,
            now=submitted_at,
            _record_activity=False,
            _finish_run=False,
        )

    await _recompute_run(db, run)
    run.status = "submitted"
    run.submitted_at = submitted_at
    run.elapsed_seconds = _run_elapsed(run, submitted_at, quiz_set.duration_limit_seconds)
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
    await db.flush()
    return run


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
        "explanation": question.explanation,
        "source_snapshot": list(question.source_snapshot or []),
        "strict_sources": question.strict_sources,
        "generation_model": question.generation_model,
    }
    if attempt is not None:
        payload["attempt"] = serialize_attempt(attempt)
    if reveal:
        payload.update({
            "answer": question.answer,
            "answer_payload": question.answer_payload,
            "grading_rubric": question.grading_rubric,
        })
    return payload


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
    attempt_rows = [
        attempt
        for attempt in (attempts or [])
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
        "question_count": quiz_set.question_count,
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
    payload: dict[str, Any] = {
        "id": run.id,
        "quiz_set_id": run.quiz_set_id,
        "round_number": run.round_number,
        "answer_mode": run.answer_mode,
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
        "attempts": [serialize_attempt(attempt) for attempt in (attempts or [])],
    }
    if quiz_set is not None:
        payload["quiz_set"] = serialize_quiz_set(
            quiz_set,
            questions=questions,
            run=run,
            attempts=attempts,
        )
    return payload
