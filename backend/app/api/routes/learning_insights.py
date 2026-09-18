"""Phase-six APIs for active study sessions and auditable learning insights."""

import base64
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.config import Settings
from app.models.learning import StudyActivity, StudySession
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.insights import (
    GlobalGoalsUpdate, StudySessionFinish, StudySessionHeartbeat, StudySessionStart,
    WorkspaceGoalUpdate, PeriodType,
)
from app.services import goal_service, report_ai_service, report_service, study_session_service
from app.services.ownership import owned_workspace


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


def _goal_collection(result: dict) -> dict:
    return {
        "timezone_name": result["timezone_name"],
        "global": {metric: result[metric] for metric in goal_service.GLOBAL_METRICS},
        "workspaces": result["workspace_goals"],
    }


def _goal_error(exc: Exception):
    if isinstance(exc, goal_service.GoalNotFoundError):
        raise HTTPException(404, "Learning goal not found") from exc
    raise HTTPException(422, str(exc)) from exc


async def _anchor_for(db: AsyncSession, value: date | None, user: User) -> date:
    if value is not None:
        return value
    preference = await goal_service.get_or_create_preferences(db, user)
    from zoneinfo import ZoneInfo
    return datetime.now(timezone.utc).astimezone(ZoneInfo(preference.timezone_name)).date()


@router.get("/reports/{period_type}")
async def get_learning_report(
    period_type: PeriodType,
    anchor_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    anchor = await _anchor_for(db, anchor_date, current_user)
    report = await report_service.build_report(
        db, period_type, anchor, now=datetime.now(timezone.utc), user_id=current_user.id
    )
    report["suggestion"] = await report_ai_service.get_cached_suggestion(
        db, report, user_id=current_user.id
    )
    return report


@router.get("/reports/{period_type}/evidence")
async def get_report_evidence(
    period_type: PeriodType,
    metric: str,
    anchor_date: date | None = None,
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await report_service.get_metric_evidence(
            db, period_type, await _anchor_for(db, anchor_date, current_user), metric,
            user_id=current_user.id, cursor=cursor, limit=limit,
        )
    except (report_service.InvalidEvidenceCursor, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/reports/{period_type}/suggestion")
async def create_report_suggestion(
    period_type: PeriodType,
    anchor_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        return await report_ai_service.generate_suggestion(
            db, settings, period_type, await _anchor_for(db, anchor_date, current_user),
            user_id=current_user.id,
        )
    except report_ai_service.ReportAIError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/goals")
async def get_learning_goals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return _goal_collection(await goal_service.get_goals(
        db, now=datetime.now(timezone.utc), user_id=current_user.id
    ))


@router.put("/goals/global")
async def put_global_goals(
    payload: GlobalGoalsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        result = await goal_service.update_global_goals(
            db, payload, now=datetime.now(timezone.utc), user_id=current_user.id
        )
    except goal_service.GoalValidationError as exc:
        _goal_error(exc)
    return _goal_collection(result)


@router.put("/goals/workspaces/{workspace_id}")
async def put_workspace_goal(
    workspace_id: str,
    payload: WorkspaceGoalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await goal_service.update_workspace_goal(
            db, workspace_id, payload, now=datetime.now(timezone.utc), user_id=current_user.id
        )
    except (goal_service.GoalValidationError, goal_service.GoalNotFoundError) as exc:
        _goal_error(exc)


@router.delete("/goals/workspaces/{workspace_id}")
async def delete_workspace_goal(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        return await goal_service.delete_workspace_goal(
            db, workspace_id, now=datetime.now(timezone.utc), user_id=current_user.id
        )
    except goal_service.GoalNotFoundError as exc:
        _goal_error(exc)


async def _call(operation):
    try:
        return await operation
    except study_session_service.StudySessionError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/study-sessions/start", status_code=201)
async def start_study_session(
    payload: StudySessionStart,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if payload.workspace_id:
        await owned_workspace(db, payload.workspace_id, current_user)
    row = await _call(study_session_service.start_session(db, payload, current_user.id))
    return _session(row)


@router.post("/study-sessions/{session_id}/heartbeat")
async def heartbeat_study_session(
    session_id: str,
    payload: StudySessionHeartbeat,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    row = await _call(study_session_service.heartbeat_session(
        db, session_id, payload.sequence, current_user.id
    ))
    return {**_session(row), "next_heartbeat_seconds": 30}


@router.post("/study-sessions/{session_id}/finish")
async def finish_study_session(
    session_id: str,
    payload: StudySessionFinish,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    result = await _call(study_session_service.finish_session(
        db, session_id, payload.sequence, current_user.id
    ))
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
    current_user: User = Depends(get_current_user),
) -> dict:
    offset = _decode_cursor(cursor)
    query = select(StudyActivity).where(StudyActivity.user_id == current_user.id)
    if activity_type:
        query = query.where(StudyActivity.activity_type == activity_type)
    if workspace_id:
        query = query.where(
            StudyActivity.workspace_id == workspace_id,
            StudyActivity.workspace_id.in_(
                select(Workspace.id).where(Workspace.owner_id == current_user.id)
            ),
        )
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
