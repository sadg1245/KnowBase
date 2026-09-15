"""Business rules for spaced review, mastery, timing, and daily summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import Flashcard, KnowledgePoint, ReviewLog, StudyActivity, UserProfile
from app.services.activity_service import append_activity, append_mastery_change
from app.models.assessment import WeakKnowledgeState
from app.services.weakness_service import recalculate_knowledge_point, upsert_weak_learning_tasks


ALGORITHM_VERSION = "simple_v1"
MASTERY_DELTAS = {1: -0.12, 2: 0.02, 3: 0.12, 4: 0.20}


def schedule_review(previous: int, ease: float, rating: int) -> tuple[int, float]:
    """Return a deterministic next interval and ease for the four review ratings."""
    if rating == 1:
        return 1, max(1.3, ease - 0.2)
    if rating == 2:
        return max(1, round(max(1, previous) * 1.3)), max(1.3, ease - 0.1)
    if rating == 3:
        return (1 if previous == 0 else max(2, round(previous * ease))), ease
    if rating == 4:
        return (3 if previous == 0 else max(4, round(previous * (ease + 0.35)))), min(3.2, ease + 0.1)
    raise ValueError("rating must be between 1 and 4")


def mastery_after_review(current: float, rating: int) -> float:
    """Apply the simple-v1 mastery delta and clamp the result to 0..1."""
    if rating not in MASTERY_DELTAS:
        raise ValueError("rating must be between 1 and 4")
    return round(max(0.0, min(1.0, current + MASTERY_DELTAS[rating])), 6)


def mastery_status_for(mastery: float, review_count: int) -> str:
    """Map numerical mastery and review history to the learner-facing state."""
    if review_count == 0 and mastery == 0:
        return "not_started"
    return "mastered" if mastery >= 0.8 else "learning"


def local_day_bounds(now: datetime, offset_minutes: int) -> tuple[datetime, datetime]:
    """Return the UTC boundaries of the local calendar day containing ``now``."""
    offset = timedelta(minutes=offset_minutes)
    local_now = now + offset
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start - offset, local_start + timedelta(days=1) - offset


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def build_review_summary(
    db: AsyncSession,
    timezone_offset_minutes: int,
    now: datetime | None = None,
) -> dict:
    """Aggregate the learner's review-day metrics using their local date."""
    current = now or datetime.now(timezone.utc)
    day_start, day_end = local_day_bounds(current, timezone_offset_minutes)
    due_cards = (
        await db.execute(
            select(Flashcard)
            .outerjoin(
                WeakKnowledgeState,
                WeakKnowledgeState.knowledge_point_id == Flashcard.knowledge_point_id,
            )
            .where(Flashcard.due_at <= current)
            .order_by(WeakKnowledgeState.weakness_score.desc().nullslast(), Flashcard.due_at.asc())
        )
    ).scalars().all()
    due_count = len(due_cards)
    new_count = sum(1 for card in due_cards if card.review_count == 0)
    overdue_count = sum(1 for card in due_cards if _as_utc(card.due_at) < day_start)

    today_reviews = (
        await db.execute(select(ReviewLog).where(
            ReviewLog.reviewed_at >= day_start,
            ReviewLog.reviewed_at < day_end,
        ))
    ).scalars().all()
    durations = list((await db.execute(
        select(ReviewLog.duration_seconds)
        .where(ReviewLog.duration_seconds > 0)
        .order_by(ReviewLog.reviewed_at.desc())
        .limit(30)
    )).scalars().all())
    average_seconds = (sum(durations) / len(durations)) if durations else 30
    estimated_minutes = ceil((due_count * average_seconds) / 60) if due_count else 0

    history_start = day_start - timedelta(days=120)
    review_dates = list((await db.execute(
        select(ReviewLog.reviewed_at).where(ReviewLog.reviewed_at >= history_start)
    )).scalars().all())
    activity_dates = list((await db.execute(
        select(StudyActivity.created_at).where(StudyActivity.created_at >= history_start)
    )).scalars().all())
    offset = timedelta(minutes=timezone_offset_minutes)
    active_dates = {(_as_utc(value) + offset).date() for value in [*review_dates, *activity_dates]}
    cursor = (current + offset).date()
    if cursor not in active_dates:
        cursor -= timedelta(days=1)
    streak_days = 0
    while cursor in active_dates:
        streak_days += 1
        cursor -= timedelta(days=1)

    point_ids = {card.knowledge_point_id for card in due_cards if card.knowledge_point_id}
    weak_points: list[dict] = []
    if point_ids:
        points = (
            await db.execute(
                select(KnowledgePoint)
                .where(KnowledgePoint.id.in_(point_ids))
                .order_by(KnowledgePoint.is_key.desc(), KnowledgePoint.mastery.asc(), KnowledgePoint.importance.desc())
                .limit(5)
            )
        ).scalars().all()
        weak_points = [{
            "id": point.id,
            "workspace_id": point.workspace_id,
            "title": point.title,
            "mastery": point.mastery,
            "mastery_status": point.mastery_status,
            "importance": point.importance,
            "is_key": point.is_key,
        } for point in points]

    profile = (await db.execute(select(UserProfile).limit(1))).scalar_one_or_none()
    return {
        "due_count": due_count,
        "new_count": new_count,
        "completed_today": len(today_reviews),
        "estimated_minutes": estimated_minutes,
        "streak_days": streak_days,
        "overdue_count": overdue_count,
        "weak_points": weak_points,
        "daily_target": profile.daily_review_target if profile else 10,
    }


async def apply_card_review(
    db: AsyncSession,
    card: Flashcard,
    rating: int,
    duration_seconds: int,
    now: datetime | None = None,
) -> dict:
    """Apply one review atomically to its card, linked point, and audit rows."""
    reviewed_at = now or datetime.now(timezone.utc)
    duration = max(0, min(3600, int(duration_seconds)))
    previous_interval = card.interval_days
    previous_mastery = card.mastery
    previous_status = card.mastery_status
    next_interval, next_ease = schedule_review(previous_interval, card.ease, rating)
    next_review_count = card.review_count + 1
    next_mastery = mastery_after_review(previous_mastery, rating)
    next_status = mastery_status_for(next_mastery, next_review_count)

    card.interval_days = next_interval
    card.ease = next_ease
    card.review_count = next_review_count
    card.mastery = next_mastery
    card.mastery_status = next_status
    card.due_at = reviewed_at + timedelta(days=next_interval)
    card.last_reviewed_at = reviewed_at
    card.total_review_seconds += duration
    card.algorithm_version = ALGORITHM_VERSION
    card.updated_at = reviewed_at

    point = None
    point_previous_mastery = None
    point_previous_status = None
    if card.knowledge_point_id:
        point = (
            await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == card.knowledge_point_id))
        ).scalar_one_or_none()
        if point:
            point_previous_mastery = point.mastery
            point_previous_status = point.mastery_status
            point.mastery = mastery_after_review(point.mastery, rating)
            point.mastery_status = mastery_status_for(point.mastery, next_review_count)

    review = ReviewLog(
        card_id=card.id,
        rating=rating,
        previous_interval=previous_interval,
        next_interval=next_interval,
        duration_seconds=duration,
        previous_mastery=previous_mastery,
        next_mastery=next_mastery,
        previous_status=previous_status,
        next_status=next_status,
        algorithm_version=ALGORITHM_VERSION,
        reviewed_at=reviewed_at,
    )
    db.add(review)
    await db.flush()
    await append_activity(
        db,
        event_key=f"activity:review:{review.id}",
        activity_type="review_completed",
        title="完成了一张知识卡复习",
        workspace_id=card.workspace_id,
        source_type="review_log",
        source_id=review.id,
        duration_seconds=duration,
        payload={"rating": rating, "card_id": card.id, "knowledge_point_id": card.knowledge_point_id},
        occurred_at=reviewed_at,
    )
    if point is not None and point_previous_mastery is not None and point_previous_status is not None:
        await append_mastery_change(
            db,
            point,
            before_mastery=point_previous_mastery,
            before_status=point_previous_status,
            reason="review",
            source_type="review_log",
            source_id=review.id,
            occurred_at=reviewed_at,
        )
    if card.knowledge_point_id:
        state = await recalculate_knowledge_point(db, card.knowledge_point_id, reviewed_at)
        await upsert_weak_learning_tasks(db, state, reviewed_at)
    return {
        "previous_mastery": previous_mastery,
        "next_mastery": next_mastery,
        "previous_status": previous_status,
        "next_status": next_status,
        "previous_interval": previous_interval,
        "next_interval": next_interval,
        "duration_seconds": duration,
        "review_id": review.id,
    }
