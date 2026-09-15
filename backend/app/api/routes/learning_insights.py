"""Phase-six APIs for active study sessions and auditable learning insights."""

import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.learning import StudyActivity, StudySession
from app.schemas.insights import StudySessionFinish, StudySessionHeartbeat, StudySessionStart
from app.services import study_session_service


router = APIRouter(prefix="/learning", tags=["learning-insights"])


def _iso(value):
    return value.isoformat() if value else None


def _session(row: StudySession) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "context_type": row.context_type,
        "context_id": row.context_id,
        "started_at": _iso(row.started_at),
        "last_heartbeat_at": _iso(row.last_heartbeat_at),
        "ended_at": _iso(row.ended_at),
        "active_seconds": row.active_seconds,
        "status": row.status,
        "last_sequence": row.last_sequence,
    }


def _activity(row: StudyActivity) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "type": row.activity_type,
        "title": row.title,
        "duration_seconds": row.duration_seconds,
        "payload": row.payload,
        "event_key": row.event_key,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "occurred_at": _iso(row.occurred_at),
        "created_at": _iso(row.created_at),
    }


async def _call(operation):
    try:
        return await operation
    except study_session_service.StudySessionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/study-sessions/start", status_code=201)
async def start_study_session(payload: StudySessionStart, db: AsyncSession = Depends(get_db)) -> dict:
    row = await _call(study_session_service.start_session(db, payload))
    return _session(row)


@router.post("/study-sessions/{session_id}/heartbeat")
async def heartbeat_study_session(
    session_id: str,
    payload: StudySessionHeartbeat,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _call(study_session_service.heartbeat_session(db, session_id, payload.sequence))
    return {**_session(row), "next_heartbeat_seconds": 30}


@router.post("/study-sessions/{session_id}/finish")
async def finish_study_session(
    session_id: str,
    payload: StudySessionFinish,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await _call(study_session_service.finish_session(db, session_id, payload.sequence))
    return {"session": _session(result.session), "activity": _activity(result.activity)}


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, "Invalid activity cursor") from exc


@router.get("/activities")
async def list_activities(
    activity_type: str | None = None,
    workspace_id: str | None = None,
    source_type: str | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    limit: int = Query(30, ge=1, le=100),
    cursor: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    offset = _decode_cursor(cursor)
    query = select(StudyActivity)
    if activity_type:
        query = query.where(StudyActivity.activity_type == activity_type)
    if workspace_id:
        query = query.where(StudyActivity.workspace_id == workspace_id)
    if source_type:
        query = query.where(StudyActivity.source_type == source_type)
    if period_start:
        query = query.where(StudyActivity.occurred_at >= period_start.astimezone(timezone.utc))
    if period_end:
        query = query.where(StudyActivity.occurred_at < period_end.astimezone(timezone.utc))
    rows = (await db.execute(
        query.order_by(StudyActivity.occurred_at.desc(), StudyActivity.id.desc())
        .offset(offset)
        .limit(limit + 1)
    )).scalars().all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more else None
    )
    return {"items": [_activity(row) for row in items], "next_cursor": next_cursor}
