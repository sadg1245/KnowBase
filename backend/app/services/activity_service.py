"""Append-only, idempotent learning activity ledger."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import StudyActivity


USER_ACTIVITY_TYPES = frozenset({
    "document_read",
    "question_asked",
    "conversation_completed",
    "card_created",
    "review_completed",
    "quiz_completed",
    "knowledge_mastered",
    "goal_changed",
})
INTERNAL_EVIDENCE_TYPES = frozenset({"mastery_changed", "weakness_changed"})
LEGACY_ACTIVITY_TYPES = frozenset({"organize", "review", "quiz", "learning_task"})
ALLOWED_ACTIVITY_TYPES = USER_ACTIVITY_TYPES | INTERNAL_EVIDENCE_TYPES | LEGACY_ACTIVITY_TYPES


class InvalidActivityType(ValueError):
    """Raised before an unknown activity type can enter the ledger."""


async def append_activity(
    db: AsyncSession,
    *,
    event_key: str | None,
    activity_type: str,
    title: str,
    source_type: str | None,
    source_id: str | None,
    workspace_id: str | None = None,
    duration_seconds: int = 0,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> StudyActivity:
    if activity_type not in ALLOWED_ACTIVITY_TYPES:
        raise InvalidActivityType(activity_type)
    if event_key:
        existing = (await db.execute(
            select(StudyActivity).where(StudyActivity.event_key == event_key)
        )).scalar_one_or_none()
        if existing is not None:
            return existing
    row = StudyActivity(
        event_key=event_key,
        activity_type=activity_type,
        title=title,
        workspace_id=workspace_id,
        source_type=source_type,
        source_id=source_id,
        duration_seconds=max(0, int(duration_seconds)),
        payload=payload,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        schema_version=1,
    )
    db.add(row)
    await db.flush()
    return row


def compatible_activity_type(value: str) -> str:
    return {"review": "review_completed", "quiz": "quiz_completed"}.get(value, value)
