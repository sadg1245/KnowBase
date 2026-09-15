"""Natural-period learning reports with reconstructable metric evidence."""

from __future__ import annotations

import base64
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import QuizAttempt
from app.models.learning import KnowledgePoint, StudyActivity
from app.models.workspace import Workspace
from app.services import goal_service
from app.services.period_service import daily_buckets, period_bounds, previous_period


INTERNAL_TYPES = {"mastery_changed", "weakness_changed"}
REVIEW_TYPES = {"review", "review_completed"}
EVIDENCE_METRICS = {
    "learning_time", "activity_count", "new_knowledge_points", "review_count",
    "quiz_accuracy", "mastery_change", "weakness_change",
}


class InvalidEvidenceCursor(ValueError):
    """The evidence cursor belongs to another period or metric."""


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _metric(value, metric: str, period_type: str, anchor_date: date) -> dict:
    return {
        "value": value,
        "evidence_query": {
            "metric": metric,
            "period_type": period_type,
            "anchor_date": anchor_date.isoformat(),
        },
    }


def _unique_activities(rows: list[StudyActivity]) -> list[StudyActivity]:
    seen = set()
    result = []
    for row in rows:
        identity = (row.source_type, row.source_id, row.activity_type) if row.source_id else ("id", row.id)
        if identity not in seen:
            seen.add(identity)
            result.append(row)
    return result


async def _period_stats(db: AsyncSession, bounds) -> dict:
    activities = _unique_activities(list(await db.scalars(select(StudyActivity).where(
        StudyActivity.occurred_at >= bounds.utc_start,
        StudyActivity.occurred_at < bounds.utc_end,
    ).order_by(StudyActivity.occurred_at, StudyActivity.id))))
    user_activities = [row for row in activities if row.activity_type not in INTERNAL_TYPES]
    review_rows = [row for row in activities if row.activity_type in REVIEW_TYPES]
    review_identities = {
        (row.source_type, row.source_id) if row.source_id else ("id", row.id)
        for row in review_rows
    }
    attempts = list(await db.scalars(select(QuizAttempt).where(
        QuizAttempt.submitted_at >= bounds.utc_start,
        QuizAttempt.submitted_at < bounds.utc_end,
    )))
    graded = [row for row in attempts if row.evaluation_status == "graded" and row.score is not None]
    total_score = sum(float(row.score) for row in graded)
    max_score = sum(float(row.max_score) for row in graded)
    accuracy = round(total_score / max_score * 100, 2) if max_score else 0.0
    new_points = list(await db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.created_at >= bounds.utc_start,
        KnowledgePoint.created_at < bounds.utc_end,
    )))
    mastery_delta = 0.0
    weakness = {"improved": 0, "worsened": 0, "unchanged": 0}
    for row in activities:
        payload = row.payload or {}
        if row.activity_type == "mastery_changed":
            mastery_delta += float(payload.get("after_mastery", 0)) - float(payload.get("before_mastery", 0))
        elif row.activity_type == "weakness_changed":
            before = payload.get("before_score")
            after = payload.get("after_score")
            if before is None or after is None or before == after:
                weakness["unchanged"] += 1
            elif after < before:
                weakness["improved"] += 1
            else:
                weakness["worsened"] += 1
    return {
        "activities": activities,
        "user_activities": user_activities,
        "total_active_seconds": sum(max(0, row.duration_seconds or 0) for row in user_activities),
        "activity_count": len(user_activities),
        "review_count": len(review_identities),
        "quiz_accuracy": accuracy,
        "pending_grading_count": sum(row.evaluation_status != "graded" for row in attempts),
        "new_knowledge_points": len(new_points),
        "mastery_delta": round(mastery_delta * 100, 2),
        "weakness_changes": weakness,
    }


def _comparison(current: float, previous: float) -> dict:
    if previous == 0:
        return {"current": current, "previous": previous, "percent_change": None, "label": "暂无可比基线"}
    change = round((current - previous) / abs(previous) * 100, 2)
    return {"current": current, "previous": previous, "percent_change": change, "label": "上升" if change > 0 else ("下降" if change < 0 else "持平")}


async def build_report(
    db: AsyncSession, period_type: str, anchor_date: date, *, now: datetime
) -> dict:
    profile = await goal_service.get_or_create_profile(db)
    bounds = period_bounds(period_type, anchor_date, profile.timezone_name)
    previous = previous_period(bounds)
    stats = await _period_stats(db, bounds)
    previous_stats = await _period_stats(db, previous)
    zone = ZoneInfo(profile.timezone_name)
    buckets = {bucket: {"date": bucket.isoformat(), "active_seconds": 0, "activities": 0,
                        "reviews": 0, "new_knowledge_points": 0} for bucket in daily_buckets(bounds)}
    for row in stats["user_activities"]:
        bucket = _aware(row.occurred_at).astimezone(zone).date()
        if bucket in buckets:
            buckets[bucket]["active_seconds"] += max(0, row.duration_seconds or 0)
            buckets[bucket]["activities"] += 1
            if row.activity_type in REVIEW_TYPES:
                buckets[bucket]["reviews"] += 1
    points = list(await db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.created_at >= bounds.utc_start,
        KnowledgePoint.created_at < bounds.utc_end,
    )))
    for point in points:
        bucket = _aware(point.created_at).astimezone(zone).date()
        if bucket in buckets:
            buckets[bucket]["new_knowledge_points"] += 1
    metrics = {
        "learning_time": _metric(stats["total_active_seconds"], "learning_time", period_type, anchor_date),
        "activity_count": _metric(stats["activity_count"], "activity_count", period_type, anchor_date),
        "new_knowledge_points": _metric(stats["new_knowledge_points"], "new_knowledge_points", period_type, anchor_date),
        "review_count": _metric(stats["review_count"], "review_count", period_type, anchor_date),
        "quiz_accuracy": _metric(stats["quiz_accuracy"], "quiz_accuracy", period_type, anchor_date),
        "mastery_change": _metric(stats["mastery_delta"], "mastery_change", period_type, anchor_date),
        "weakness_change": _metric(stats["weakness_changes"], "weakness_change", period_type, anchor_date),
    }
    return {
        "period": {
            "type": period_type,
            "timezone_name": profile.timezone_name,
            "local_start": bounds.local_start.date().isoformat(),
            "local_end": bounds.local_end.date().isoformat(),
            "utc_start": bounds.utc_start.isoformat(),
            "utc_end": bounds.utc_end.isoformat(),
        },
        "total_active_seconds": stats["total_active_seconds"],
        "activity_count": stats["activity_count"],
        "new_knowledge_points": stats["new_knowledge_points"],
        "review_count": stats["review_count"],
        "quiz_accuracy": stats["quiz_accuracy"],
        "pending_grading_count": stats["pending_grading_count"],
        "mastery_delta": stats["mastery_delta"],
        "weakness_changes": stats["weakness_changes"],
        "metrics": metrics,
        "comparisons": {
            "learning_time": _comparison(stats["total_active_seconds"], previous_stats["total_active_seconds"]),
            "activity_count": _comparison(stats["activity_count"], previous_stats["activity_count"]),
            "new_knowledge_points": _comparison(stats["new_knowledge_points"], previous_stats["new_knowledge_points"]),
            "review_count": _comparison(stats["review_count"], previous_stats["review_count"]),
            "quiz_accuracy": _comparison(stats["quiz_accuracy"], previous_stats["quiz_accuracy"]),
            "mastery_change": _comparison(stats["mastery_delta"], previous_stats["mastery_delta"]),
        },
        "trend": list(buckets.values()),
    }


def _cursor_signature(period_type: str, anchor_date: date, metric: str) -> str:
    return f"{period_type}:{anchor_date.isoformat()}:{metric}"


def _encode_cursor(signature: str, offset: int) -> str:
    raw = json.dumps({"signature": signature, "offset": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None, signature: str) -> int:
    if not cursor:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        if payload["signature"] != signature:
            raise InvalidEvidenceCursor("Evidence cursor does not match this query")
        return max(0, int(payload["offset"]))
    except InvalidEvidenceCursor:
        raise
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidEvidenceCursor("Invalid evidence cursor") from exc


async def get_metric_evidence(
    db: AsyncSession,
    period_type: str,
    anchor_date: date,
    metric: str,
    *,
    cursor: str | None = None,
    limit: int = 30,
) -> dict:
    if metric not in EVIDENCE_METRICS:
        raise ValueError(f"Unsupported report metric: {metric}")
    profile = await goal_service.get_or_create_profile(db)
    bounds = period_bounds(period_type, anchor_date, profile.timezone_name)
    signature = _cursor_signature(period_type, anchor_date, metric)
    offset = _decode_cursor(cursor, signature)
    items: list[dict] = []
    if metric in {"learning_time", "activity_count", "review_count", "mastery_change", "weakness_change"}:
        query = select(StudyActivity).where(
            StudyActivity.occurred_at >= bounds.utc_start,
            StudyActivity.occurred_at < bounds.utc_end,
        )
        if metric in {"learning_time", "activity_count"}:
            query = query.where(StudyActivity.activity_type.not_in(INTERNAL_TYPES))
        elif metric == "review_count":
            query = query.where(StudyActivity.activity_type.in_(REVIEW_TYPES))
        elif metric == "mastery_change":
            query = query.where(StudyActivity.activity_type == "mastery_changed")
        else:
            query = query.where(StudyActivity.activity_type == "weakness_changed")
        rows = list(await db.scalars(query.order_by(StudyActivity.occurred_at.desc(), StudyActivity.id.desc())))
        for row in _unique_activities(rows):
            workspace = await db.get(Workspace, row.workspace_id) if row.workspace_id else None
            items.append({
                "id": row.id, "kind": "activity", "activity_type": row.activity_type,
                "title": row.title, "workspace_id": row.workspace_id,
                "workspace_name": workspace.name if workspace else None,
                "duration_seconds": row.duration_seconds,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "source_label": row.source_type or "历史记录",
                "occurred_at": row.occurred_at.isoformat(),
                "payload": row.payload,
            })
    elif metric == "new_knowledge_points":
        rows = list(await db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.created_at >= bounds.utc_start,
            KnowledgePoint.created_at < bounds.utc_end,
        ).order_by(KnowledgePoint.created_at.desc(), KnowledgePoint.id.desc())))
        items = [{
            "id": row.id, "kind": "knowledge_point", "title": row.title,
            "workspace_id": row.workspace_id, "duration_seconds": 0,
            "source_type": "knowledge_point", "source_id": row.id,
            "source_label": "知识点", "occurred_at": row.created_at.isoformat(),
        } for row in rows]
    else:
        rows = list(await db.scalars(select(QuizAttempt).where(
            QuizAttempt.submitted_at >= bounds.utc_start,
            QuizAttempt.submitted_at < bounds.utc_end,
        ).order_by(QuizAttempt.submitted_at.desc(), QuizAttempt.id.desc())))
        items = [{
            "id": row.id, "kind": "quiz_attempt", "title": "测验作答",
            "duration_seconds": row.duration_seconds, "source_type": "quiz_attempt",
            "source_id": row.id, "source_label": "测验记录",
            "occurred_at": row.submitted_at.isoformat(), "score": row.score,
            "max_score": row.max_score, "evaluation_status": row.evaluation_status,
        } for row in rows]
    page = items[offset:offset + limit]
    next_cursor = _encode_cursor(signature, offset + limit) if offset + limit < len(items) else None
    return {"items": page, "next_cursor": next_cursor, "metric": metric}


async def build_legacy_report(db: AsyncSession, *, days: int, now: datetime) -> dict:
    """Adapt the shared evidence calculations to the old rolling-window response."""
    profile = await goal_service.get_or_create_profile(db)
    end = _aware(now) + timedelta(microseconds=1)
    start = _aware(now) - timedelta(days=days)
    stats = await _period_stats(db, SimpleNamespace(utc_start=start, utc_end=end))
    zone = ZoneInfo(profile.timezone_name)
    daily: dict[str, dict] = {}
    for row in stats["user_activities"]:
        key = _aware(row.occurred_at).astimezone(zone).date().isoformat()
        daily.setdefault(key, {"date": key, "minutes": 0.0, "activities": 0})
        daily[key]["minutes"] = round(daily[key]["minutes"] + (row.duration_seconds or 0) / 60, 1)
        daily[key]["activities"] += 1
    points = list(await db.scalars(select(KnowledgePoint)))
    return {
        "days": days,
        "total_minutes": round(stats["total_active_seconds"] / 60),
        "activity_count": stats["activity_count"],
        "review_count": stats["review_count"],
        "quiz_accuracy": round(stats["quiz_accuracy"]),
        "mastered_points": sum(point.mastery >= .8 for point in points),
        "total_points": len(points),
        "daily": [daily[key] for key in sorted(daily)],
        "suggestion": (
            "优先复习掌握度较低的知识点，并在复习后用自己的话复述一次。"
            if points else "先导入一份资料并生成知识点，开始第一轮学习。"
        ),
    }
