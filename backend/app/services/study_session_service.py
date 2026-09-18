"""Server-authoritative lifecycle for active document and conversation time."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatSession
from app.models.document import Document
from app.models.learning import StudyActivity, StudySession
from app.models.workspace import Workspace
from app.schemas.insights import StudySessionStart
from app.services.activity_service import append_activity


MAX_HEARTBEAT_SECONDS = 60
MAX_SESSION_AGE = timedelta(hours=12)


class StudySessionError(ValueError):
    status_code = 400


class SessionNotFound(StudySessionError):
    status_code = 404


class ContextNotFound(StudySessionError):
    status_code = 404


class ContextMismatch(StudySessionError):
    status_code = 400


class SessionCompleted(StudySessionError):
    status_code = 409


@dataclass(frozen=True)
class SessionSettlement:
    session: StudySession
    activity: StudyActivity


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _validated_workspace(
    db: AsyncSession, request: StudySessionStart, user_id: str
) -> str | None:
    if request.context_type == "document":
        context = (await db.execute(
            select(Document)
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(Document.id == request.context_id, Workspace.owner_id == user_id)
        )).scalar_one_or_none()
    else:
        context = (await db.execute(
            select(ChatSession).where(
                ChatSession.id == request.context_id, ChatSession.user_id == user_id
            )
        )).scalar_one_or_none()
    if context is None:
        raise ContextNotFound(request.context_id)
    if request.workspace_id is not None and context.workspace_id != request.workspace_id:
        raise ContextMismatch("Learning context does not belong to the workspace")
    if context.workspace_id is not None:
        owned = await db.scalar(select(Workspace.id).where(
            Workspace.id == context.workspace_id, Workspace.owner_id == user_id
        ))
        if owned is None:
            raise ContextNotFound(request.context_id)
    return context.workspace_id


async def start_session(
    db: AsyncSession,
    request: StudySessionStart,
    user_id: str,
    now: datetime | None = None,
) -> StudySession:
    now = _aware(now or datetime.now(timezone.utc))
    await expire_stale_sessions(db, user_id=user_id, now=now)
    existing = (await db.execute(
        select(StudySession).where(
            StudySession.id == request.id, StudySession.user_id == user_id
        )
    )).scalar_one_or_none()
    if existing is not None:
        if existing.context_type != request.context_type or existing.context_id != request.context_id:
            raise ContextMismatch("Session id belongs to another learning context")
        return existing
    workspace_id = await _validated_workspace(db, request, user_id)
    active = (await db.execute(select(StudySession).where(
        StudySession.user_id == user_id,
        StudySession.context_type == request.context_type,
        StudySession.context_id == request.context_id,
        StudySession.status == "active",
    ))).scalar_one_or_none()
    if active is not None:
        return active
    row = StudySession(
        id=request.id,
        user_id=user_id,
        workspace_id=workspace_id,
        context_type=request.context_type,
        context_id=request.context_id,
        started_at=now,
        last_heartbeat_at=now,
        status="active",
        active_seconds=0,
        last_sequence=0,
    )
    if db.bind and db.bind.dialect.name in {"sqlite", "postgresql"}:
        if db.bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        await db.execute(insert(StudySession).values(
            id=request.id, user_id=user_id, workspace_id=workspace_id,
            context_type=request.context_type, context_id=request.context_id,
            started_at=now, last_heartbeat_at=now, status="active",
            active_seconds=0, last_sequence=0,
        ).on_conflict_do_nothing())
        resolved = (await db.execute(select(StudySession).where(
            StudySession.user_id == user_id,
            StudySession.context_type == request.context_type,
            StudySession.context_id == request.context_id,
            StudySession.status == "active",
        ))).scalar_one_or_none()
        if resolved is not None:
            return resolved
    db.add(row)
    await db.flush()
    return row


async def _session(db: AsyncSession, session_id: str, user_id: str) -> StudySession:
    row = (await db.execute(
        select(StudySession).where(
            StudySession.id == session_id, StudySession.user_id == user_id
        )
    )).scalar_one_or_none()
    if row is None:
        raise SessionNotFound(session_id)
    return row


async def heartbeat_session(
    db: AsyncSession,
    session_id: str,
    sequence: int,
    user_id: str,
    now: datetime | None = None,
) -> StudySession:
    row = await _session(db, session_id, user_id)
    if row.status not in {"active", "paused"}:
        raise SessionCompleted(session_id)
    if sequence <= row.last_sequence:
        return row
    now = _aware(now or datetime.now(timezone.utc))
    if now - _aware(row.started_at) > MAX_SESSION_AGE:
        return (await _settle(db, row, _aware(row.last_heartbeat_at), "expired")).session
    delta = max(0, int((now - _aware(row.last_heartbeat_at)).total_seconds()))
    if delta <= MAX_HEARTBEAT_SECONDS:
        row.active_seconds += delta
    row.last_heartbeat_at = now
    row.last_sequence = sequence
    row.status = "active"
    await db.flush()
    return row


async def _settle(
    db: AsyncSession,
    row: StudySession,
    now: datetime,
    status: str,
) -> SessionSettlement:
    event_key = f"activity:study-session:{row.id}"
    existing = (await db.execute(
        select(StudyActivity).where(StudyActivity.event_key == event_key)
    )).scalar_one_or_none()
    if existing is None:
        activity_type = "document_read" if row.context_type == "document" else "conversation_completed"
        title = "阅读文档" if row.context_type == "document" else "完成学习会话"
        existing = await append_activity(
            db,
            user_id=row.user_id,
            event_key=event_key,
            activity_type=activity_type,
            title=title,
            workspace_id=row.workspace_id,
            source_type="study_session",
            source_id=row.id,
            duration_seconds=row.active_seconds,
            payload={"context_type": row.context_type, "context_id": row.context_id},
            occurred_at=now,
        )
    if row.status in {"active", "paused"}:
        row.status = status
        row.ended_at = now
        await db.flush()
    return SessionSettlement(session=row, activity=existing)


async def finish_session(
    db: AsyncSession,
    session_id: str,
    sequence: int,
    user_id: str,
    now: datetime | None = None,
) -> SessionSettlement:
    row = await _session(db, session_id, user_id)
    now = _aware(now or datetime.now(timezone.utc))
    if sequence > row.last_sequence:
        row.last_sequence = sequence
    return await _settle(db, row, now, "completed")


async def expire_stale_sessions(
    db: AsyncSession,
    user_id: str,
    now: datetime | None = None,
) -> list[SessionSettlement]:
    now = _aware(now or datetime.now(timezone.utc))
    rows = (await db.execute(select(StudySession).where(
        StudySession.user_id == user_id,
        StudySession.status.in_(("active", "paused")),
    ))).scalars().all()
    results = []
    for row in rows:
        if now - _aware(row.started_at) > MAX_SESSION_AGE:
            results.append(await _settle(db, row, _aware(row.last_heartbeat_at), "expired"))
    return results
