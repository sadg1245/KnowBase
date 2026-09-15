"""Deterministic, evidence-backed weak-knowledge scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import exp
from statistics import median
from typing import Sequence
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt, WeakKnowledgeState
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity


ATTEMPT_LIMIT = 20
ATTEMPT_RECENCY_DAYS = 14
RECENCY_STALE_DAYS = 30
TASK_SCORE_THRESHOLD = 60


def _utc(value: datetime) -> datetime:
    """Treat legacy SQLite timestamps without an offset as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


@dataclass(frozen=True)
class AttemptEvidence:
    is_correct: bool | None
    submitted_at: datetime
    duration_seconds: int


@dataclass(frozen=True)
class WeaknessMetrics:
    """Raw, inspectable evidence used for the five deterministic components."""

    attempts: Sequence[AttemptEvidence]
    unresolved_mistake_count: int
    review_ratings: Sequence[int]
    duration_ratios: Sequence[float]
    last_relevant_activity_at: datetime | None


@dataclass(frozen=True)
class WeaknessScore:
    total: int
    components: dict[str, float]
    evidence: dict


def calculate_weakness(metrics: WeaknessMetrics, now: datetime) -> WeaknessScore:
    """Score five observable signals; absent evidence is neutral, never an error."""
    current = _utc(now)
    graded = [attempt for attempt in metrics.attempts if attempt.is_correct is not None]
    if graded:
        weighted_total = 0.0
        weighted_wrong = 0.0
        for attempt in graded:
            age_days = max(0.0, (current - _utc(attempt.submitted_at)).total_seconds() / 86400)
            weight = exp(-age_days / ATTEMPT_RECENCY_DAYS)
            weighted_total += weight
            weighted_wrong += weight * float(attempt.is_correct is False)
        accuracy = _clamp(100 * weighted_wrong / weighted_total) if weighted_total else 0.0
    else:
        accuracy = 0.0

    repeat_error = _clamp(max(0, metrics.unresolved_mistake_count) * 25)
    valid_ratings = [rating for rating in metrics.review_ratings if 1 <= rating <= 4]
    review_feedback = (
        _clamp(100 * (4 - sum(valid_ratings) / len(valid_ratings)) / 3)
        if valid_ratings else 0.0
    )
    response_time = (
        _clamp(100 * (median(metrics.duration_ratios) - 1))
        if metrics.duration_ratios else 0.0
    )
    if metrics.last_relevant_activity_at is None:
        recency = 50.0
    else:
        age_days = max(0.0, (current - _utc(metrics.last_relevant_activity_at)).total_seconds() / 86400)
        recency = _clamp(100 * age_days / RECENCY_STALE_DAYS)

    components = {
        "accuracy": round(accuracy, 3),
        "repeat_error": round(repeat_error, 3),
        "review_feedback": round(review_feedback, 3),
        "response_time": round(response_time, 3),
        "recency": round(recency, 3),
    }
    total = round(sum((
        components["accuracy"] * 0.35,
        components["repeat_error"] * 0.25,
        components["review_feedback"] * 0.15,
        components["response_time"] * 0.10,
        components["recency"] * 0.15,
    )))
    return WeaknessScore(
        total=int(_clamp(total)),
        components=components,
        evidence={
            "graded_attempt_count": len(graded),
            "attempt_count": len(metrics.attempts),
            "unresolved_mistake_count": max(0, metrics.unresolved_mistake_count),
            "review_count": len(valid_ratings),
            "duration_comparison_count": len(metrics.duration_ratios),
            "last_relevant_activity_at": (
                _utc(metrics.last_relevant_activity_at).isoformat()
                if metrics.last_relevant_activity_at else None
            ),
        },
    )


def _recommended_actions(point: KnowledgePoint, score: WeaknessScore) -> list[dict]:
    if score.total < TASK_SCORE_THRESHOLD:
        return []
    learn_query = urlencode({"workspace": point.workspace_id, "knowledge_point_id": point.id})
    practice_query = urlencode({"workspace_id": point.workspace_id, "knowledge_point_id": point.id})
    point_context = f"知识点「{point.title}」（ID: {point.id}）"
    if point.document_id:
        source_query = urlencode({"page": point.source_page}) if point.source_page else ""
        source_path = f"/knowledge/{point.workspace_id}/documents/{point.document_id}"
        if source_query:
            source_path = f"{source_path}?{source_query}"
    else:
        source_path = f"/learn?{learn_query}&mode=simple&{urlencode({'prompt': '请带我重新阅读' + point_context})}"
    return [
        {"type": "re_read", "label": "重新阅读", "path": source_path},
        {
            "type": "plain_explanation", "label": "通俗讲解",
            "path": f"/learn?{learn_query}&mode=simple&{urlencode({'prompt': '请用通俗语言讲解' + point_context})}",
        },
        {
            "type": "new_example", "label": "生成新例子",
            "path": f"/learn?{learn_query}&mode=simple&{urlencode({'prompt': '请围绕' + point_context + '给出一个新的循序渐进例子'})}",
        },
        {
            "type": "targeted_practice", "label": "针对性练习",
            "path": f"/practice?{practice_query}&mode=targeted",
        },
        {
            "type": "review", "label": "加入近期复习",
            "path": "/review",
        },
    ]


async def recalculate_knowledge_point(
    db: AsyncSession,
    point_id: str,
    now: datetime | None = None,
) -> WeakKnowledgeState:
    """Rebuild one point's state from attempts, mistakes, reviews, and timing evidence."""
    current = _utc(now or datetime.now(timezone.utc))
    point = await db.get(KnowledgePoint, point_id)
    if point is None:
        raise ValueError("Knowledge point not found")

    attempt_rows = (await db.execute(
        select(QuizAttempt, QuizQuestion)
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .where(
            QuizQuestion.knowledge_point_id == point.id,
            QuizAttempt.evaluation_status == "graded",
            QuizAttempt.is_correct.is_not(None),
        )
        .order_by(QuizAttempt.submitted_at.desc(), QuizAttempt.id.desc())
        .limit(ATTEMPT_LIMIT)
    )).all()
    attempts = tuple(
        AttemptEvidence(
            is_correct=attempt.is_correct,
            submitted_at=attempt.submitted_at,
            duration_seconds=max(0, attempt.duration_seconds),
        )
        for attempt, _ in attempt_rows
    )
    unresolved = list((await db.execute(
        select(MistakeRecord).where(
            MistakeRecord.knowledge_point_id == point.id,
            MistakeRecord.mastery_status != "mastered",
        )
    )).scalars().all())
    unresolved_count = sum(max(1, row.wrong_count) for row in unresolved)

    review_rows = (await db.execute(
        select(ReviewLog)
        .join(Flashcard, ReviewLog.card_id == Flashcard.id)
        .where(Flashcard.knowledge_point_id == point.id)
        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id.desc())
        .limit(ATTEMPT_LIMIT)
    )).scalars().all()

    timing_rows = (await db.execute(
        select(QuizAttempt, QuizQuestion)
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .where(
            QuizQuestion.workspace_id == point.workspace_id,
            QuizAttempt.evaluation_status == "graded",
            QuizAttempt.duration_seconds > 0,
        )
    )).all()
    baselines: dict[tuple[str, str], list[int]] = {}
    for attempt, question in timing_rows:
        baselines.setdefault((question.question_type, question.difficulty_level), []).append(attempt.duration_seconds)
    duration_ratios = tuple(
        attempt.duration_seconds / median(baselines[(question.question_type, question.difficulty_level)])
        for attempt, question in attempt_rows
        if attempt.evaluation_status == "graded" and attempt.duration_seconds > 0
        and baselines.get((question.question_type, question.difficulty_level))
    )
    attempt_times = list((await db.execute(
        select(QuizAttempt.submitted_at)
        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
        .where(QuizQuestion.knowledge_point_id == point.id)
    )).scalars().all())
    review_times = list((await db.execute(
        select(ReviewLog.reviewed_at)
        .join(Flashcard, ReviewLog.card_id == Flashcard.id)
        .where(Flashcard.knowledge_point_id == point.id)
    )).scalars().all())
    completed_task_times = list((await db.execute(
        select(LearningTask.completed_at).where(
            LearningTask.knowledge_point_id == point.id,
            LearningTask.status == "completed",
            LearningTask.completed_at.is_not(None),
        )
    )).scalars().all())
    activity_rows = (await db.execute(
        select(StudyActivity).where(StudyActivity.workspace_id == point.workspace_id)
    )).scalars().all()
    activity_times = [
        row.created_at for row in activity_rows
        if isinstance(row.payload, dict) and row.payload.get("knowledge_point_id") == point.id
    ]
    last_activity = max(
        (_utc(value) for value in [*attempt_times, *review_times, *completed_task_times, *activity_times] if value),
        default=None,
    )
    latest_unresolved_at = max(
        (_utc(row.last_wrong_at) for row in unresolved if row.last_wrong_at),
        default=None,
    )
    metrics = WeaknessMetrics(
        attempts=attempts,
        unresolved_mistake_count=unresolved_count,
        review_ratings=tuple(row.rating for row in review_rows),
        duration_ratios=duration_ratios,
        last_relevant_activity_at=last_activity,
    )
    score = calculate_weakness(metrics, current)
    evidence = dict(score.evidence)
    evidence.update({
        "attempt_recency_days": ATTEMPT_RECENCY_DAYS,
        "recency_stale_days": RECENCY_STALE_DAYS,
        "timing_baseline": "median graded duration by question type and difficulty",
        "latest_attempt_at": max((_utc(value) for value in attempt_times), default=None).isoformat() if attempt_times else None,
        "latest_review_at": (
            _utc(review_rows[0].reviewed_at).isoformat() if review_rows else None
        ),
        "latest_unresolved_mistake_at": latest_unresolved_at.isoformat() if latest_unresolved_at else None,
    })
    state = (await db.execute(
        select(WeakKnowledgeState).where(WeakKnowledgeState.knowledge_point_id == point.id)
    )).scalar_one_or_none()
    if state is None:
        state = WeakKnowledgeState(knowledge_point_id=point.id, workspace_id=point.workspace_id)
        db.add(state)
    state.weakness_score = score.total
    state.accuracy_component = score.components["accuracy"]
    state.repeat_error_component = score.components["repeat_error"]
    state.review_feedback_component = score.components["review_feedback"]
    state.response_time_component = score.components["response_time"]
    state.recency_component = score.components["recency"]
    state.evidence = evidence
    state.recommended_actions = _recommended_actions(point, score)
    state.calculated_at = current
    await db.flush()
    return state


async def upsert_weak_learning_tasks(
    db: AsyncSession,
    state: WeakKnowledgeState,
    now: datetime | None = None,
) -> list[LearningTask]:
    """Keep the two scheduled actions idempotent; other recommendations are immediate."""
    if state.weakness_score < TASK_SCORE_THRESHOLD:
        return []
    current = _utc(now or datetime.now(timezone.utc))
    actions = {action["type"]: action for action in state.recommended_actions}
    tasks: list[LearningTask] = []
    for task_type, delay in (("review", timedelta()), ("targeted_practice", timedelta(days=1))):
        action = actions.get(task_type)
        if action is None:
            continue
        task = (await db.execute(
            select(LearningTask).where(
                LearningTask.knowledge_point_id == state.knowledge_point_id,
                LearningTask.task_type == task_type,
                LearningTask.status == "pending",
            )
        )).scalar_one_or_none()
        if task is None:
            task = LearningTask(
                workspace_id=state.workspace_id,
                knowledge_point_id=state.knowledge_point_id,
                task_type=task_type,
                title=action["label"],
                path=action["path"],
                payload={"weakness_score": state.weakness_score, "action": action},
                due_at=current + delay,
                priority=state.weakness_score,
            )
            db.add(task)
        else:
            task.title = action["label"]
            task.path = action["path"]
            task.payload = {"weakness_score": state.weakness_score, "action": action}
            task.priority = state.weakness_score
        tasks.append(task)
    await db.flush()
    return tasks


def weakness_priority_subquery():
    """A correlated score used to order due cards without altering their schedule."""
    return (
        select(WeakKnowledgeState.weakness_score)
        .where(WeakKnowledgeState.knowledge_point_id == Flashcard.knowledge_point_id)
        .correlate(Flashcard)
        .scalar_subquery()
    )
