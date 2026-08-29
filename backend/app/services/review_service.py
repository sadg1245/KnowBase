"""Business rules for spaced review, mastery, timing, and daily summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import Flashcard, KnowledgePoint, ReviewLog, StudyActivity


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

    if card.knowledge_point_id:
        point = (
            await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == card.knowledge_point_id))
        ).scalar_one_or_none()
        if point:
            point.mastery = mastery_after_review(point.mastery, rating)
            point.mastery_status = mastery_status_for(point.mastery, next_review_count)

    db.add(ReviewLog(
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
    ))
    db.add(StudyActivity(
        workspace_id=card.workspace_id,
        activity_type="review",
        title="完成了一张知识卡复习",
        duration_seconds=duration,
        payload={"rating": rating, "card_id": card.id},
        created_at=reviewed_at,
    ))
    await db.flush()
    return {
        "previous_mastery": previous_mastery,
        "next_mastery": next_mastery,
        "previous_status": previous_status,
        "next_status": next_status,
        "previous_interval": previous_interval,
        "next_interval": next_interval,
        "duration_seconds": duration,
    }
