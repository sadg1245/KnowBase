"""Build the learning home page from auditable records and current domain state."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt, QuizSet, WeakKnowledgeState
from app.models.document import Document
from app.models.learning import Flashcard, KnowledgePoint, LearningGoal, ReviewLog, StudyActivity
from app.models.user import User
from app.models.workspace import Workspace
from app.services import goal_service, study_session_service
from app.services.period_service import period_bounds


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _iso(value) -> str | None:
    return value.isoformat() if value else None


async def _display_name(db: AsyncSession, user_id: str) -> str:
    name = await db.scalar(select(User.display_name).where(User.id == user_id))
    return name or "学习者"


def _point(row: KnowledgePoint, weakness_score: float | None = None) -> dict:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "document_id": row.document_id,
        "title": row.title,
        "summary": row.summary,
        "explanation": row.explanation,
        "importance": row.importance,
        "difficulty": row.difficulty,
        "mastery": row.mastery,
        "mastery_status": row.mastery_status,
        "weakness_score": weakness_score,
        "tags": row.tags or [],
        "is_key": row.is_key,
        "created_at": _iso(row.created_at),
    }


def _derived_task(
    local_date,
    task_type: str,
    *,
    title: str,
    description: str,
    count: int | float,
    estimated_minutes: int,
    status: str,
    priority: int,
    path: str,
    source: dict,
    scope: str = "global",
) -> dict:
    return {
        "id": f"derived:{local_date.isoformat()}:{task_type}:{scope}",
        "type": task_type,
        "title": title,
        "description": description,
        "count": count,
        "estimated_minutes": estimated_minutes,
        "status": status,
        "priority": priority,
        "path": path,
        "source": source,
        "derived": True,
    }


async def _median_duration(db: AsyncSession, query, fallback: int) -> int:
    values = [int(value) for value in await db.scalars(query)]
    return max(1, round(median(values))) if values else fallback


async def rank_workspaces(
    db: AsyncSession, *, now: datetime, user_id: str, limit: int = 4
) -> list[dict]:
    preference = await goal_service.get_or_create_preferences_by_id(db, user_id)
    local_today = _aware(now).astimezone(ZoneInfo(preference.timezone_name)).date()
    recent_cutoff = _aware(now) - timedelta(days=30)
    workspaces = list(await db.scalars(
        select(Workspace).where(
            Workspace.owner_id == user_id, Workspace.archived.is_(False)
        )
    ))
    ranked = []
    for workspace in workspaces:
        goal = await db.scalar(select(LearningGoal).where(
            LearningGoal.scope_type == "workspace",
            LearningGoal.workspace_id == workspace.id,
            LearningGoal.metric == "workspace_mastery",
            LearningGoal.is_active.is_(True),
        ))
        urgency = 0.0
        if goal and goal.target_date:
            progress = await goal_service.calculate_goal_progress(db, goal, now=now)
            days = (goal.target_date - local_today).days
            if progress["ratio"] < 1 and days <= 14:
                urgency = 35.0 if days <= 0 else round(35 * (14 - days + 1) / 14, 2)

        weak_average = await db.scalar(select(func.avg(WeakKnowledgeState.weakness_score)).where(
            WeakKnowledgeState.workspace_id == workspace.id
        ))
        weakness = round(30 * min(100, float(weak_average or 0)) / 100, 2)
        mistake_count = int(await db.scalar(select(func.count(MistakeRecord.id)).where(
            MistakeRecord.workspace_id == workspace.id,
            MistakeRecord.mastery_status != "mastered",
        )) or 0)
        task_count = int(await db.scalar(select(func.count(LearningTask.id)).where(
            LearningTask.workspace_id == workspace.id,
            LearningTask.status == "pending",
        )) or 0)
        unfinished = round(20 * min(1, (mistake_count + task_count) / 5), 2)
        last_activity = await db.scalar(select(func.max(StudyActivity.occurred_at)).where(
            StudyActivity.workspace_id == workspace.id,
            StudyActivity.activity_type.in_(goal_service.LEARNING_ACTIVITY_TYPES),
        ))
        recent = 10.0 if last_activity and _aware(last_activity) >= recent_cutoff else 0.0
        unlearned = int(await db.scalar(select(func.count(Document.id)).where(
            Document.workspace_id == workspace.id,
            Document.learning_status != "completed",
        )) or 0)
        new_material = 5.0 if unlearned else 0.0
        components = {
            "goal_urgency": urgency,
            "weakness": weakness,
            "unfinished_work": unfinished,
            "recent_activity": recent,
            "new_material": new_material,
        }
        reason_labels = {
            "goal_urgency": "知识库目标即将到期",
            "weakness": "存在需要巩固的薄弱知识",
            "unfinished_work": "仍有错题或学习任务待完成",
            "recent_activity": "适合延续近期学习节奏",
            "new_material": "还有资料尚未开始学习",
        }
        primary = max(components, key=lambda key: components[key])
        ranked.append({
            "workspace_id": workspace.id,
            "name": workspace.name,
            "description": workspace.description or "",
            "domain": workspace.domain,
            "accent_color": workspace.accent_color,
            "score": round(sum(components.values()), 2),
            "components": components,
            "reason": reason_labels[primary] if components[primary] > 0 else "可以开始建立学习记录",
            "last_activity_at": _iso(last_activity),
            "path": f"/knowledge/{workspace.id}",
            "_last_activity": _aware(last_activity).timestamp() if last_activity else 0,
            "_updated": _aware(workspace.updated_at).timestamp(),
        })
    ranked.sort(key=lambda row: (-row["score"], -row["_last_activity"], -row["_updated"], row["workspace_id"]))
    for row in ranked:
        row.pop("_last_activity")
        row.pop("_updated")
    return ranked[:limit]


async def build_dashboard(db: AsyncSession, *, now: datetime, user_id: str) -> dict:
    now = _aware(now)
    await study_session_service.expire_stale_sessions(db, user_id=user_id, now=now)
    preference = await goal_service.get_or_create_preferences_by_id(db, user_id)
    zone = ZoneInfo(preference.timezone_name)
    local_today = now.astimezone(zone).date()
    day = period_bounds("day", local_today, preference.timezone_name)
    week = period_bounds("week", local_today, preference.timezone_name)
    goals = await goal_service.get_goals(db, now=now, user_id=user_id)
    owned_workspaces = select(Workspace.id).where(Workspace.owner_id == user_id)

    due_cards = int(await db.scalar(select(func.count(Flashcard.id)).where(
        Flashcard.due_at <= now, Flashcard.workspace_id.in_(owned_workspaces)
    )) or 0)
    unresolved_mistakes = int(await db.scalar(select(func.count(MistakeRecord.id)).where(
        MistakeRecord.mastery_status != "mastered",
        MistakeRecord.workspace_id.in_(owned_workspaces),
    )) or 0)
    day_activities = list(await db.scalars(select(StudyActivity).where(
        StudyActivity.user_id == user_id,
        StudyActivity.occurred_at >= day.utc_start,
        StudyActivity.occurred_at < day.utc_end,
        StudyActivity.activity_type.in_(goal_service.LEARNING_ACTIVITY_TYPES),
    )))
    week_activities = list(await db.scalars(select(StudyActivity).where(
        StudyActivity.user_id == user_id,
        StudyActivity.occurred_at >= week.utc_start,
        StudyActivity.occurred_at < week.utc_end,
        StudyActivity.activity_type.in_(goal_service.LEARNING_ACTIVITY_TYPES),
    )))
    today_seconds = sum(row.duration_seconds or 0 for row in day_activities)
    week_seconds = sum(row.duration_seconds or 0 for row in week_activities)
    today_minutes = round(today_seconds / 60)

    review_seconds = await _median_duration(
        db,
        select(ReviewLog.duration_seconds)
        .join(Flashcard, Flashcard.id == ReviewLog.card_id)
        .where(ReviewLog.duration_seconds > 0, Flashcard.workspace_id.in_(owned_workspaces)),
        45,
    )
    attempt_seconds = await _median_duration(
        db,
        select(QuizAttempt.duration_seconds)
        .join(QuizSet, QuizSet.id == QuizAttempt.quiz_set_id)
        .where(QuizAttempt.duration_seconds > 0, QuizSet.workspace_id.in_(owned_workspaces)),
        180,
    )
    review_count = min(due_cards, preference.daily_review_target)
    tasks = [
        _derived_task(
            local_today, "review", title="完成今日复习",
            description=f"{due_cards} 张卡片已到期，今日建议复习 {review_count} 张",
            count=review_count,
            estimated_minutes=math.ceil(review_count * review_seconds / 60),
            status="completed" if due_cards == 0 else "pending", priority=100, path="/review",
            source={"type": "due_flashcards", "actual_count": due_cards},
        ),
        _derived_task(
            local_today, "mistake", title="重做待掌握错题",
            description=f"还有 {unresolved_mistakes} 道错题尚未掌握",
            count=unresolved_mistakes,
            estimated_minutes=math.ceil(unresolved_mistakes * attempt_seconds / 60),
            status="completed" if unresolved_mistakes == 0 else "pending", priority=90,
            path="/practice?wrong=1",
            source={"type": "mistake_records", "mastery_status": "not_mastered"},
        ),
    ]

    persisted = list(await db.scalars(
        select(LearningTask).where(
            LearningTask.workspace_id.in_(owned_workspaces),
            LearningTask.status == "pending",
            LearningTask.due_at.is_not(None),
            LearningTask.due_at <= now,
        ).order_by(LearningTask.priority.desc(), LearningTask.due_at.asc(), LearningTask.id)
    ))
    for task in persisted:
        tasks.append({
            "id": task.id,
            "type": task.task_type,
            "title": task.title,
            "description": (task.payload or {}).get("description", "根据薄弱知识状态生成的学习任务"),
            "count": 1,
            "estimated_minutes": int((task.payload or {}).get("estimated_minutes", 10)),
            "status": task.status,
            "priority": task.priority,
            "path": task.path,
            "workspace_id": task.workspace_id,
            "knowledge_point_id": task.knowledge_point_id,
            "due_at": _iso(task.due_at),
            "source": {"type": "learning_task", "id": task.id},
            "derived": False,
        })

    for progress in goals["workspace_goals"]:
        target_date = datetime.fromisoformat(progress["target_date"]).date() if progress["target_date"] else None
        if target_date and progress["ratio"] < 1 and (target_date - local_today).days <= 14:
            tasks.append(_derived_task(
                local_today, "workspace_goal", scope=progress["workspace_id"],
                title="推进知识库学习目标",
                description=f"目标掌握度 {progress['target']:.0f}%，截止 {target_date.isoformat()}",
                count=round(max(0, progress["target"] - progress["actual"]), 1),
                estimated_minutes=15, status="pending", priority=70,
                path=f"/knowledge/{progress['workspace_id']}",
                source={"type": "learning_goal", "id": progress["id"]},
            ))

    remaining = max(0, preference.daily_goal_minutes - today_minutes)
    tasks.append(_derived_task(
        local_today, "study_time", title="完成今日学习时长",
        description=f"今日还需专注学习 {remaining} 分钟",
        count=remaining,
        estimated_minutes=remaining,
        status="completed" if remaining == 0 else "pending", priority=50, path="/learn",
        source={"type": "study_activities", "actual_minutes": today_minutes},
    ))
    tasks = tasks[:5]

    history_cutoff = week.utc_start - timedelta(days=60)
    history = list(await db.scalars(select(StudyActivity).where(
        StudyActivity.user_id == user_id,
        StudyActivity.occurred_at >= history_cutoff,
        StudyActivity.activity_type.in_(goal_service.LEARNING_ACTIVITY_TYPES),
    )))
    active_dates = {_aware(row.occurred_at).astimezone(zone).date() for row in history}
    cursor = local_today if local_today in active_dates else local_today - timedelta(days=1)
    streak = 0
    while cursor in active_dates:
        streak += 1
        cursor -= timedelta(days=1)

    recent_rows = list(await db.scalars(
        select(StudyActivity)
        .where(
            StudyActivity.user_id == user_id,
            StudyActivity.activity_type.not_in(("mastery_changed", "weakness_changed")),
        )
        .order_by(StudyActivity.occurred_at.desc(), StudyActivity.id.desc()).limit(8)
    ))
    weak_pairs = (await db.execute(
        select(KnowledgePoint, WeakKnowledgeState.weakness_score)
        .join(WeakKnowledgeState, WeakKnowledgeState.knowledge_point_id == KnowledgePoint.id)
        .where(KnowledgePoint.workspace_id.in_(owned_workspaces))
        .order_by(WeakKnowledgeState.weakness_score.desc(), KnowledgePoint.importance.desc())
        .limit(5)
    )).all()
    recommendations = await rank_workspaces(db, now=now, user_id=user_id, limit=4)
    workspace_count = int(await db.scalar(select(func.count(Workspace.id)).where(
        Workspace.owner_id == user_id, Workspace.archived.is_(False)
    )) or 0)
    document_count = int(await db.scalar(select(func.count(Document.id)).where(
        Document.workspace_id.in_(owned_workspaces)
    )) or 0)
    point_count = int(await db.scalar(select(func.count(KnowledgePoint.id)).where(
        KnowledgePoint.workspace_id.in_(owned_workspaces)
    )) or 0)
    recent_workspaces = [{
        "id": row["workspace_id"], "name": row["name"], "description": row["description"],
        "domain": row["domain"], "accent_color": row["accent_color"], "learning_goal": "",
    } for row in recommendations]
    return {
        "profile": {
            "display_name": await _display_name(db, user_id),
            "daily_goal_minutes": preference.daily_goal_minutes,
            "daily_review_target": preference.daily_review_target,
            "weekly_goal_days": preference.weekly_goal_days,
            "timezone_name": preference.timezone_name,
        },
        "stats": {
            "workspace_count": workspace_count, "document_count": document_count,
            "knowledge_point_count": point_count, "due_cards": due_cards,
            "wrong_questions": unresolved_mistakes, "today_minutes": today_minutes,
            "week_minutes": round(week_seconds / 60), "streak_days": streak,
        },
        "today_tasks": tasks,
        "goal_progress": {metric: goals[metric] for metric in goal_service.GLOBAL_METRICS},
        "learning_queue": {
            "due_reviews": {"count": due_cards, "path": "/review"},
            "mistakes": {"count": unresolved_mistakes, "path": "/practice?wrong=1"},
        },
        "recommended_workspaces": recommendations,
        "weak_points": [_point(point, score) for point, score in weak_pairs],
        "recent_activities": [{
            "id": row.id, "workspace_id": row.workspace_id, "type": row.activity_type,
            "title": row.title, "duration_seconds": row.duration_seconds,
            "source_type": row.source_type, "source_id": row.source_id,
            "occurred_at": _iso(row.occurred_at), "created_at": _iso(row.created_at),
        } for row in recent_rows],
        "recent_workspaces": recent_workspaces,
    }
