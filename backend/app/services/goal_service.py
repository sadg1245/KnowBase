"""Canonical learning goals, compatibility profile fields, and measurable progress."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning import KnowledgePoint, LearningGoal, StudyActivity, UserProfile
from app.models.workspace import Workspace
from app.schemas.insights import GlobalGoalsUpdate, WorkspaceGoalUpdate
from app.services.activity_service import append_activity
from app.services.period_service import period_bounds


GLOBAL_METRICS = ("daily_minutes", "daily_reviews", "weekly_days", "overall_mastery")
LEARNING_ACTIVITY_TYPES = {
    "document_read", "question_asked", "conversation_completed", "card_created",
    "review_completed", "quiz_completed", "knowledge_mastered",
    "organize", "review", "quiz", "learning_task",
}


class GoalValidationError(ValueError):
    """A goal cannot be saved without violating its date, timezone, or scope contract."""


class GoalNotFoundError(LookupError):
    """The requested workspace or workspace goal does not exist."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise GoalValidationError(f"Invalid timezone: {name}") from exc


def _local_today(now: datetime, timezone_name: str) -> date:
    return _aware(now).astimezone(_zone(timezone_name)).date()


async def get_or_create_profile(db: AsyncSession) -> UserProfile:
    profile = await db.scalar(select(UserProfile).limit(1))
    if profile is None:
        profile = UserProfile(display_name="学习者")
        db.add(profile)
        await db.flush()
    return profile


async def _seed_global_goals(db: AsyncSession, profile: UserProfile) -> dict[str, LearningGoal]:
    rows = list(await db.scalars(select(LearningGoal).where(LearningGoal.scope_type == "global")))
    by_metric = {row.metric: row for row in rows}
    defaults = {
        "daily_minutes": float(profile.daily_goal_minutes),
        "daily_reviews": float(profile.daily_review_target),
        "weekly_days": float(profile.weekly_goal_days),
        "overall_mastery": 100.0,
    }
    for metric, target in defaults.items():
        if metric not in by_metric:
            row = LearningGoal(scope_type="global", metric=metric, target_value=target)
            db.add(row)
            by_metric[metric] = row
    await db.flush()
    return by_metric


async def _record_change(
    db: AsyncSession,
    goal: LearningGoal,
    before: dict,
    after: dict,
    now: datetime,
) -> None:
    goal.version += 1
    await append_activity(
        db,
        event_key=f"activity:goal:{goal.id}:v{goal.version}",
        activity_type="goal_changed",
        title="修改了学习目标",
        workspace_id=goal.workspace_id,
        source_type="learning_goal",
        source_id=goal.id,
        payload={"metric": goal.metric, "scope_type": goal.scope_type, "before": before, "after": after},
        occurred_at=now,
    )


def _goal_state(goal: LearningGoal) -> dict:
    return {
        "target_value": float(goal.target_value),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "is_active": bool(goal.is_active),
    }


async def _progress(db: AsyncSession, goal: LearningGoal, now: datetime, timezone_name: str) -> dict:
    local_date = _local_today(now, timezone_name)
    if goal.metric == "daily_minutes":
        bounds = period_bounds("day", local_date, timezone_name)
        activities = list(await db.scalars(select(StudyActivity).where(
            StudyActivity.occurred_at >= bounds.utc_start,
            StudyActivity.occurred_at < bounds.utc_end,
        )))
        actual = sum(row.duration_seconds or 0 for row in activities) / 60
    elif goal.metric == "daily_reviews":
        bounds = period_bounds("day", local_date, timezone_name)
        activities = list(await db.scalars(select(StudyActivity).where(
            StudyActivity.occurred_at >= bounds.utc_start,
            StudyActivity.occurred_at < bounds.utc_end,
            StudyActivity.activity_type.in_(("review", "review_completed")),
        )))
        identities = {
            (row.source_type, row.source_id) if row.source_id else ("legacy", row.id)
            for row in activities
        }
        actual = float(len(identities))
    elif goal.metric == "weekly_days":
        bounds = period_bounds("week", local_date, timezone_name)
        activities = list(await db.scalars(select(StudyActivity).where(
            StudyActivity.occurred_at >= bounds.utc_start,
            StudyActivity.occurred_at < bounds.utc_end,
            StudyActivity.activity_type.in_(LEARNING_ACTIVITY_TYPES),
        )))
        zone = _zone(timezone_name)
        actual = float(len({_aware(row.occurred_at).astimezone(zone).date() for row in activities}))
    elif goal.metric == "workspace_mastery":
        average = await db.scalar(select(func.avg(KnowledgePoint.mastery)).where(
            KnowledgePoint.workspace_id == goal.workspace_id
        ))
        actual = float(average or 0) * 100
    else:
        average = await db.scalar(
            select(func.avg(KnowledgePoint.mastery))
            .join(Workspace, Workspace.id == KnowledgePoint.workspace_id)
            .where(Workspace.archived.is_(False))
        )
        actual = float(average or 0) * 100
    actual = round(actual, 2)
    target = float(goal.target_value)
    ratio = round(actual / target, 4) if target else 0.0
    return {
        "id": goal.id,
        "scope_type": goal.scope_type,
        "workspace_id": goal.workspace_id,
        "metric": goal.metric,
        "actual": actual,
        "target": target,
        "ratio": ratio,
        "status": "completed" if ratio >= 1 else ("in_progress" if actual > 0 else "not_started"),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "is_active": bool(goal.is_active),
        "version": goal.version,
    }


async def calculate_goal_progress(db: AsyncSession, goal: LearningGoal, bounds=None, *, now: datetime) -> dict:
    profile = await get_or_create_profile(db)
    return await _progress(db, goal, now, profile.timezone_name)


async def get_goals(db: AsyncSession, *, now: datetime) -> dict:
    profile = await get_or_create_profile(db)
    globals_by_metric = await _seed_global_goals(db, profile)
    result = {"timezone_name": profile.timezone_name}
    for metric in GLOBAL_METRICS:
        result[metric] = await _progress(db, globals_by_metric[metric], now, profile.timezone_name)
    workspace_rows = list(await db.scalars(select(LearningGoal).where(
        LearningGoal.scope_type == "workspace",
        LearningGoal.is_active.is_(True),
    ).order_by(LearningGoal.updated_at.desc())))
    result["workspace_goals"] = [await _progress(db, row, now, profile.timezone_name) for row in workspace_rows]
    return result


async def update_global_goals(db: AsyncSession, request: GlobalGoalsUpdate, *, now: datetime) -> dict:
    _zone(request.timezone_name)
    if request.target_completion_date < _local_today(now, request.timezone_name):
        raise GoalValidationError("Target completion date cannot be in the past")
    profile = await get_or_create_profile(db)
    goals = await _seed_global_goals(db, profile)
    targets = {
        "daily_minutes": (float(request.daily_minutes), None),
        "daily_reviews": (float(request.daily_reviews), None),
        "weekly_days": (float(request.weekly_days), None),
        "overall_mastery": (100.0, request.target_completion_date),
    }
    for metric, (target, target_date) in targets.items():
        goal = goals[metric]
        before = _goal_state(goal)
        if goal.target_value == target and goal.target_date == target_date and goal.is_active:
            continue
        goal.target_value = target
        goal.target_date = target_date
        goal.is_active = True
        await _record_change(db, goal, before, _goal_state(goal), now)
    profile.daily_goal_minutes = request.daily_minutes
    profile.daily_review_target = request.daily_reviews
    profile.weekly_goal_days = request.weekly_days
    profile.timezone_name = request.timezone_name
    profile.updated_at = now
    await db.flush()
    return await get_goals(db, now=now)


async def sync_legacy_profile_goals(db: AsyncSession, values: dict, *, now: datetime) -> UserProfile:
    profile = await get_or_create_profile(db)
    timezone_name = values.get("timezone_name", profile.timezone_name)
    _zone(timezone_name)
    goals = await _seed_global_goals(db, profile)
    mapping = {
        "daily_goal_minutes": "daily_minutes",
        "daily_review_target": "daily_reviews",
        "weekly_goal_days": "weekly_days",
    }
    for field, metric in mapping.items():
        if field not in values:
            continue
        goal = goals[metric]
        target = float(values[field])
        before = _goal_state(goal)
        if goal.target_value != target or not goal.is_active:
            goal.target_value = target
            goal.is_active = True
            await _record_change(db, goal, before, _goal_state(goal), now)
        setattr(profile, field, values[field])
    profile.timezone_name = timezone_name
    profile.updated_at = now
    await db.flush()
    return profile


async def update_workspace_goal(
    db: AsyncSession, workspace_id: str, request: WorkspaceGoalUpdate, *, now: datetime
) -> dict:
    profile = await get_or_create_profile(db)
    if request.target_date < _local_today(now, profile.timezone_name):
        raise GoalValidationError("Target date cannot be in the past")
    workspace = await db.scalar(select(Workspace).where(Workspace.id == workspace_id))
    if workspace is None:
        raise GoalNotFoundError(workspace_id)
    goal = await db.scalar(select(LearningGoal).where(
        LearningGoal.scope_type == "workspace",
        LearningGoal.workspace_id == workspace_id,
        LearningGoal.metric == "workspace_mastery",
    ))
    if goal is None:
        goal = LearningGoal(
            scope_type="workspace", workspace_id=workspace_id, metric="workspace_mastery",
            target_value=float(request.target_mastery), target_date=request.target_date,
        )
        db.add(goal)
        await db.flush()
        await _record_change(db, goal, {}, _goal_state(goal), now)
    else:
        before = _goal_state(goal)
        if goal.target_value != request.target_mastery or goal.target_date != request.target_date or not goal.is_active:
            goal.target_value = float(request.target_mastery)
            goal.target_date = request.target_date
            goal.is_active = True
            await _record_change(db, goal, before, _goal_state(goal), now)
    await db.flush()
    return await _progress(db, goal, now, profile.timezone_name)


async def delete_workspace_goal(db: AsyncSession, workspace_id: str, *, now: datetime) -> dict:
    goal = await db.scalar(select(LearningGoal).where(
        LearningGoal.scope_type == "workspace",
        LearningGoal.workspace_id == workspace_id,
        LearningGoal.metric == "workspace_mastery",
    ))
    if goal is None:
        raise GoalNotFoundError(workspace_id)
    if goal.is_active:
        before = _goal_state(goal)
        goal.is_active = False
        await _record_change(db, goal, before, _goal_state(goal), now)
        await db.flush()
    return await _progress(db, goal, now, (await get_or_create_profile(db)).timezone_name)
