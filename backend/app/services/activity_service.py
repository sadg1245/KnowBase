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
    if event_key and db.bind and db.bind.dialect.name in {"sqlite", "postgresql"}:
        if db.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        values = {
            "event_key": event_key, "activity_type": activity_type, "title": title,
            "workspace_id": workspace_id, "source_type": source_type, "source_id": source_id,
            "duration_seconds": row.duration_seconds, "payload": payload,
            "occurred_at": row.occurred_at, "schema_version": 1,
        }
        await db.execute(insert(StudyActivity).values(**values).on_conflict_do_nothing())
        return (await db.execute(
            select(StudyActivity).where(StudyActivity.event_key == event_key)
        )).scalar_one()
    db.add(row)
    await db.flush()
    return row


def compatible_activity_type(value: str) -> str:
    return {"review": "review_completed", "quiz": "quiz_completed"}.get(value, value)


async def append_card_created(db: AsyncSession, card, *, occurred_at: datetime | None = None) -> StudyActivity:
    return await append_activity(
        db,
        event_key=f"activity:card:{card.id}",
        activity_type="card_created",
        title="创建了一张知识卡片",
        workspace_id=card.workspace_id,
        source_type="flashcard",
        source_id=card.id,
        payload={
            "knowledge_point_id": card.knowledge_point_id,
            "card_source_type": card.source_type,
        },
        occurred_at=occurred_at,
    )


async def append_mastery_change(
    db: AsyncSession,
    point,
    *,
    before_mastery: float,
    before_status: str,
    reason: str,
    source_type: str,
    source_id: str,
    occurred_at: datetime | None = None,
) -> list[StudyActivity]:
    after_mastery = float(point.mastery)
    after_status = point.mastery_status
    if before_mastery == after_mastery and before_status == after_status:
        return []
    timestamp = occurred_at or datetime.now(timezone.utc)
    payload = {
        "knowledge_point_id": point.id,
        "before_mastery": before_mastery,
        "after_mastery": after_mastery,
        "before_status": before_status,
        "after_status": after_status,
        "reason": reason,
    }
    evidence = await append_activity(
        db,
        event_key=f"evidence:mastery:{point.id}:{source_type}:{source_id}",
        activity_type="mastery_changed",
        title=f"知识点掌握度发生变化：{point.title}",
        workspace_id=point.workspace_id,
        source_type=source_type,
        source_id=source_id,
        payload=payload,
        occurred_at=timestamp,
    )
    rows = [evidence]
    if before_status != "mastered" and after_status == "mastered":
        rows.append(await append_activity(
            db,
            event_key=f"activity:mastered:{point.id}:{source_type}:{source_id}",
            activity_type="knowledge_mastered",
            title=f"掌握了知识点：{point.title}",
            workspace_id=point.workspace_id,
            source_type="knowledge_point",
            source_id=point.id,
            payload=payload,
            occurred_at=timestamp,
        ))
    return rows


def weakness_category(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 60:
        return "weak"
    if score >= 30:
        return "watch"
    return "stable"


async def append_weakness_change(
    db: AsyncSession,
    state,
    *,
    before_score: float | None,
    before_category: str | None,
    reason: str,
    occurred_at: datetime | None = None,
) -> StudyActivity | None:
    after_score = float(state.weakness_score)
    after_category = weakness_category(after_score)
    if before_score == after_score and before_category == after_category:
        return None
    timestamp = occurred_at or datetime.now(timezone.utc)
    key_time = timestamp.astimezone(timezone.utc).isoformat()
    return await append_activity(
        db,
        event_key=f"evidence:weakness:{state.knowledge_point_id}:{key_time}:{after_score}",
        activity_type="weakness_changed",
        title="知识点薄弱度发生变化",
        workspace_id=state.workspace_id,
        source_type="weak_knowledge_state",
        source_id=state.id,
        payload={
            "knowledge_point_id": state.knowledge_point_id,
            "before_score": before_score,
            "after_score": after_score,
            "before_category": before_category,
            "after_category": after_category,
            "reason": reason,
        },
        occurred_at=timestamp,
    )
