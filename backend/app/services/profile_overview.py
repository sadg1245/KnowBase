"""Read-time learner profile: deterministic facts first, language later.

设计约束（与画像设计文档一致）：

1. 不新增权威画像表，全部由既有事实表读时聚合；
2. 数值与结论来自 SQL / 业务规则，LLM 只负责把确定性指标说成人话；
3. 画像可以调整教学、练习与复习优先级，但不能作为资料事实证据。

所有查询都以调用者拥有的工作区为界，越权 id 只会得到空画像而不是别人的数据。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import MistakeRecord, QuizAttempt, WeakKnowledgeState
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity, StudySession
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.profile import (
    AttemptEvidenceItem,
    CommonErrorItem,
    FocusItem,
    GoalItem,
    LearnerProfileOverview,
    LearningObservations,
    MasteryItem,
    MistakePatternItem,
    ProfileInsight,
    RecentLearningArea,
    RecentLearningItem,
    ReviewEvidenceItem,
    WeakAction,
    WeakPointEvidence,
    WeakPointItem,
)
from app.services import goal_service

TREND_WINDOW_DAYS = 14
RECENT_WINDOW_DAYS = 30
EVIDENCE_WINDOW_DAYS = 90
MAX_FOCUS_AREAS = 3
MAX_FOCUS_POINTS = 5
MAX_RECENT_DAYS = 7
MAX_COMMON_ERRORS = 5
MAX_GOAL_ITEMS = 5
MAX_GOAL_POINTS_PER_BUCKET = 6
RECENT_ATTEMPT_LIMIT = 5
RECENT_REVIEW_LIMIT = 3
ROW_BUDGET = 500

# 掌握状态阈值（画像设计文档 §3.2）。
MASTERY_BANDS: tuple[tuple[float, str, str], ...] = (
    (0.30, "not_mastered", "未掌握"),
    (0.50, "weak", "薄弱"),
    (0.70, "learning", "学习中"),
    (0.85, "mastered", "已掌握"),
    (1.01, "proficient", "熟练"),
)

REVIEW_RATING_LABELS = {1: "忘记", 2: "模糊", 3: "记住", 4: "熟练"}
WEAKNESS_BANDS: tuple[tuple[float, str, str], ...] = (
    (30.0, "stable", "暂时稳定"),
    (60.0, "watch", "需要巩固"),
    (80.0, "weak", "薄弱"),
    (101.0, "priority", "优先处理"),
)
WEAKNESS_STATE_NOTES = {
    "stable": "掌握稳定，按复习计划保持即可",
    "watch": "掌握不稳定，建议尽快巩固",
    "weak": "掌握不稳定，属于当前薄弱知识",
    "priority": "掌握明显不足，建议优先处理",
}


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def mastery_band(score: float) -> tuple[str, str]:
    """把 0–1 的掌握度映射成五档状态，空值按未掌握处理。"""
    value = 0.0 if score is None else max(0.0, min(1.0, float(score)))
    for ceiling, status, label in MASTERY_BANDS:
        if value < ceiling:
            return status, label
    return "proficient", "熟练"


def weakness_band(score_100: float | None) -> tuple[str, str]:
    value = 0.0 if score_100 is None else float(score_100)
    for ceiling, band, label in WEAKNESS_BANDS:
        if value < ceiling:
            return band, label
    return "priority", "优先处理"


def mastery_confidence(days_since_evidence: int | None) -> tuple[float, str | None]:
    """置信度只描述“这个数字还新不新”，不倒扣掌握度（文档 §12）。"""
    if days_since_evidence is None:
        return 0.2, "还没有练习或复习记录，掌握度只是初始值"
    if days_since_evidence <= 14:
        return 0.9, None
    if days_since_evidence <= 30:
        return 0.7, f"最近 {days_since_evidence} 天没有新的复习或练习"
    if days_since_evidence <= 45:
        return 0.55, f"最近 {days_since_evidence} 天没有有效复习或练习"
    return 0.35, f"{days_since_evidence} 天没有有效复习或练习"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _day_label(local_date: date, today: date) -> str:
    delta = (today - local_date).days
    if delta == 0:
        return "今天"
    if delta == 1:
        return "昨天"
    return f"{local_date.month} 月 {local_date.day} 日"


def _goal_title(metric: str, target: float, workspace_name: str | None) -> str:
    if metric == "daily_minutes":
        return f"每日学习 {round(target)} 分钟"
    if metric == "daily_reviews":
        return f"每日复习 {round(target)} 张卡片"
    if metric == "weekly_days":
        return f"每周学习 {round(target)} 天"
    if metric == "workspace_mastery":
        return f"掌握「{workspace_name or '知识库'}」"
    return f"总体掌握度 {round(target)}%"


def _action_path(kind: str, *, workspace_id: str, point_id: str, title: str) -> str:
    from urllib.parse import urlencode

    if kind == "practice":
        query = urlencode({"workspace_id": workspace_id, "knowledge_point_id": point_id})
        return f"/practice?{query}&mode=targeted"
    if kind == "review":
        return "/review"
    prompt = f"请用通俗语言讲解知识点「{title}」（ID: {point_id}）"
    query = urlencode({"workspace": workspace_id, "knowledge_point_id": point_id, "mode": "simple", "prompt": prompt})
    return f"/learn?{query}"


def _weak_actions(state: WeakKnowledgeState | None, point: KnowledgePoint) -> list[WeakAction]:
    """把已有的确定性建议收敛成复习 / 练习 / 讲解三类动作。"""
    stored = {
        action.get("type"): action
        for action in (state.recommended_actions if state is not None else []) or []
        if isinstance(action, dict)
    }

    def resolved(action_type: str, stored_type: str, label: str) -> WeakAction:
        entry = stored.get(stored_type) or {}
        path = entry.get("path") if isinstance(entry.get("path"), str) else None
        return WeakAction(
            type=action_type,
            label=label,
            path=path
            or _action_path(action_type, workspace_id=point.workspace_id, point_id=point.id, title=point.title),
        )

    return [
        resolved("review", "review", "复习"),
        resolved("practice", "targeted_practice", "专项练习"),
        resolved("explain", "plain_explanation", "让 AI 讲解"),
    ]


def _reason_texts(
    *,
    point: KnowledgePoint,
    state: WeakKnowledgeState | None,
    attempts: list[QuizAttempt],
    reviews: list[ReviewLog],
    unresolved_mistakes: int,
    stale_days: int | None,
) -> list[str]:
    """用可复核的事实解释薄弱原因，而不是让模型自由发挥。"""
    reasons: list[str] = []
    graded = [attempt for attempt in attempts if attempt.is_correct is not None][:RECENT_ATTEMPT_LIMIT]
    if graded:
        correct = sum(1 for attempt in graded if attempt.is_correct)
        reasons.append(f"最近 {len(graded)} 题答对 {correct} 题")
    recent_reviews = reviews[:RECENT_REVIEW_LIMIT]
    weak_reviews = [review for review in recent_reviews if review.rating <= 2]
    if weak_reviews:
        reasons.append(
            f"最近 {len(recent_reviews)} 次复习都没记住"
            if len(weak_reviews) == len(recent_reviews)
            else f"最近 {len(recent_reviews)} 次复习有 {len(weak_reviews)} 次没记住"
        )
    if unresolved_mistakes:
        reasons.append(f"仍有 {unresolved_mistakes} 道错题未掌握")
    if stale_days is not None and stale_days >= TREND_WINDOW_DAYS:
        reasons.append(f"{stale_days} 天没有有效学习")
    if not reasons:
        evidence = (state.evidence if state is not None else {}) or {}
        stored = str(evidence.get("reason", "")).strip()
        if stored:
            reasons.append(stored)
    if not reasons and state is not None:
        reasons.append("薄弱分主要来自学习间隔偏长")
    return reasons[:3]


def _rule_insight(
    *, mastery: list[MasteryItem], weak_points: list[WeakPointItem], now: datetime
) -> ProfileInsight:
    """确定性说法：先给事实与建议，AI 版本另行按需生成。"""
    trends = [item for item in mastery if item.trend is not None and abs(item.trend) >= 0.01]
    improved = max(trends, key=lambda item: item.trend or 0.0, default=None)
    declined = min(trends, key=lambda item: item.trend or 0.0, default=None)
    sentences: list[str] = []
    based_on: list[str] = []
    if improved is not None and (improved.trend or 0) > 0:
        sentences.append(
            f"最近 {TREND_WINDOW_DAYS} 天 {improved.name} 掌握度提升 "
            f"{round((improved.trend or 0) * 100)} 个百分点（{round(improved.score * 100)}%）。"
        )
        based_on.append("mastery_trend")
    if declined is not None and (declined.trend or 0) < 0:
        sentences.append(
            f"{declined.name} 同期回落 {abs(round((declined.trend or 0) * 100))} 个百分点。"
        )
        based_on.append("mastery_trend")
    if weak_points:
        top = weak_points[0]
        detail = f"（{top.reasons[0]}）" if top.reasons else ""
        sentences.append(
            f"当前最该补的是 {top.name}，掌握度 {round(top.mastery * 100)}%{detail}。"
        )
        sentences.append(f"建议先完成 {top.name} 的复习，再做 3 道专项练习。")
        based_on.append("weak_points")
    elif mastery:
        sentences.append("目前没有明显薄弱点，可以继续推进当前目标。")
        based_on.append("mastery")
    evidence = {
        "trend_window_days": TREND_WINDOW_DAYS,
        "mastery": [
            {"name": item.name, "score": item.score, "trend": item.trend, "confidence": item.confidence}
            for item in mastery
        ],
        "weak_points": [
            {
                "name": point.name,
                "mastery": point.mastery,
                "weakness_score": point.weakness_score,
                "reasons": point.reasons,
                "attempt_accuracy": point.evidence.attempt_accuracy,
                "mistake_count": point.evidence.mistake_count,
            }
            for point in weak_points
        ],
    }
    return ProfileInsight(
        text="".join(sentences) if sentences else "",
        generated_by="rules",
        based_on=based_on,
        evidence=evidence if sentences else {},
        generated_at=now.isoformat(),
    )


def insight_snapshot(profile: LearnerProfileOverview) -> dict:
    """AI 洞察的输入快照：只包含确定性数字，便于缓存与审计。"""
    return {
        "display_name": profile.display_name,
        "trend_window_days": profile.trend_window_days,
        "current_focus": [item.name for item in profile.current_focus],
        "mastery": [
            {
                "name": item.name,
                "score": item.score,
                "status": item.status,
                "trend": item.trend,
                "confidence": item.confidence,
                "confidence_note": item.confidence_note,
            }
            for item in profile.mastery_overview
        ],
        "weak_points": [
            {
                "name": point.name,
                "mastery": point.mastery,
                "weakness_score": point.weakness_score,
                "reasons": point.reasons,
            }
            for point in profile.weak_points
        ],
        "goals": [
            {"title": goal.title, "progress": goal.progress, "target_date": goal.target_date, "status": goal.status}
            for goal in profile.goals
        ],
        "recent_learning": [
            {"label": item.label, "minutes": item.minutes, "areas": [area.name for area in item.areas]}
            for item in profile.recent_learning
        ],
        "observations": profile.observations.model_dump(),
    }


def snapshot_hash(snapshot: dict) -> str:
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class LearnerProfileOverviewService:
    """把学习事实聚合成一个可解释、可行动的学习画像。"""

    def __init__(self, db: AsyncSession, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    async def build(
        self,
        *,
        now: datetime,
        workspace_id: str | None = None,
        mastery_limit: int = 4,
        weak_limit: int = 3,
        include_children: bool = True,
        include_evidence: bool = True,
        child_limit: int | None = None,
    ) -> LearnerProfileOverview:
        current = _aware(now)
        preference = await goal_service.get_or_create_preferences_by_id(self.db, self.user_id)
        zone = _zone(preference.timezone_name)
        user = await self.db.get(User, self.user_id)

        workspaces = list(
            (
                await self.db.execute(
                    select(Workspace).where(
                        Workspace.owner_id == self.user_id, Workspace.archived.is_(False)
                    )
                )
            ).scalars().all()
        )
        if workspace_id:
            workspaces = [row for row in workspaces if row.id == workspace_id]
        workspace_by_id = {row.id: row for row in workspaces}
        scope = list(workspace_by_id)

        points = (
            list(
                (
                    await self.db.execute(
                        select(KnowledgePoint).where(KnowledgePoint.workspace_id.in_(scope))
                    )
                ).scalars().all()
            )
            if scope
            else []
        )
        point_by_id = {point.id: point for point in points}
        points_by_workspace: dict[str, list[KnowledgePoint]] = defaultdict(list)
        for point in points:
            points_by_workspace[point.workspace_id].append(point)

        weak_states = (
            list(
                (
                    await self.db.execute(
                        select(WeakKnowledgeState)
                        .where(WeakKnowledgeState.workspace_id.in_(scope))
                        .order_by(WeakKnowledgeState.weakness_score.desc())
                    )
                ).scalars().all()
            )
            if scope
            else []
        )
        state_by_point = {row.knowledge_point_id: row for row in weak_states}

        cutoff = current - timedelta(days=EVIDENCE_WINDOW_DAYS)
        mistake_rows = (
            list(
                (
                    await self.db.execute(
                        select(MistakeRecord)
                        .where(
                            MistakeRecord.workspace_id.in_(scope),
                            MistakeRecord.mastery_status != "mastered",
                        )
                        .order_by(MistakeRecord.last_wrong_at.desc(), MistakeRecord.id)
                        .limit(ROW_BUDGET)
                    )
                ).scalars().all()
            )
            if scope
            else []
        )
        activities = list(
            (
                await self.db.execute(
                    select(StudyActivity)
                    .where(
                        StudyActivity.user_id == self.user_id,
                        StudyActivity.occurred_at >= cutoff,
                    )
                    .order_by(StudyActivity.occurred_at.desc(), StudyActivity.id)
                    .limit(ROW_BUDGET)
                )
            ).scalars().all()
        )
        attempt_rows = (
            list(
                (
                    await self.db.execute(
                        select(QuizAttempt, QuizQuestion)
                        .join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id)
                        .where(
                            QuizQuestion.workspace_id.in_(scope),
                            QuizAttempt.submitted_at >= cutoff,
                        )
                        .order_by(QuizAttempt.submitted_at.desc(), QuizAttempt.id)
                        .limit(ROW_BUDGET)
                    )
                ).all()
            )
            if scope
            else []
        )
        review_rows = (
            list(
                (
                    await self.db.execute(
                        select(ReviewLog, Flashcard)
                        .join(Flashcard, ReviewLog.card_id == Flashcard.id)
                        .where(
                            Flashcard.workspace_id.in_(scope),
                            ReviewLog.reviewed_at >= cutoff,
                        )
                        .order_by(ReviewLog.reviewed_at.desc(), ReviewLog.id)
                        .limit(ROW_BUDGET)
                    )
                ).all()
            )
            if scope
            else []
        )

        attempts_by_point: dict[str, list[QuizAttempt]] = defaultdict(list)
        for attempt, question in attempt_rows:
            if question.knowledge_point_id:
                attempts_by_point[question.knowledge_point_id].append(attempt)
        reviews_by_point: dict[str, list[ReviewLog]] = defaultdict(list)
        for review, card in review_rows:
            if card.knowledge_point_id:
                reviews_by_point[card.knowledge_point_id].append(review)
        mistakes_by_point: dict[str, list[MistakeRecord]] = defaultdict(list)
        for row in mistake_rows:
            if row.knowledge_point_id:
                mistakes_by_point[row.knowledge_point_id].append(row)

        last_evidence_by_point = _last_evidence_by_point(
            activities=activities,
            attempts_by_point=attempts_by_point,
            reviews_by_point=reviews_by_point,
            states=weak_states,
            point_by_id=point_by_id,
        )
        last_evidence_by_workspace = _last_evidence_by_workspace(
            activities=activities,
            points=points,
            last_evidence_by_point=last_evidence_by_point,
            workspace_ids=scope,
        )
        trend_by_point = _trend_by_point(
            activities=activities, points=points, point_by_id=point_by_id, now=current
        )
        recent_minutes_by_workspace = _recent_minutes_by_workspace(
            activities=activities, scope=set(scope), now=current, days=TREND_WINDOW_DAYS
        )

        has_evidence = bool(
            activities or mistake_rows or attempt_rows or review_rows or weak_states
        )
        is_empty = not has_evidence

        mastery_items = [
            _workspace_mastery_item(
                workspace=workspace,
                points=points_by_workspace.get(workspace.id, []),
                trend_by_point=trend_by_point,
                last_evidence_at=last_evidence_by_workspace.get(workspace.id),
                last_evidence_by_point=last_evidence_by_point,
                now=current,
                include_children=include_children,
                child_limit=child_limit,
            )
            for workspace in workspaces
            if points_by_workspace.get(workspace.id)
        ]
        mastery_items.sort(key=lambda item: (-item.score, item.name))

        weak_points = [
            _weak_point_item(
                point=point_by_id[row.knowledge_point_id],
                area=workspace_by_id[point_by_id[row.knowledge_point_id].workspace_id].name,
                state=row,
                attempts=attempts_by_point.get(row.knowledge_point_id, []),
                reviews=reviews_by_point.get(row.knowledge_point_id, []),
                mistakes=mistakes_by_point.get(row.knowledge_point_id, []),
                last_evidence_at=last_evidence_by_point.get(row.knowledge_point_id),
                now=current,
                include_evidence=include_evidence,
            )
            for row in weak_states
            if row.knowledge_point_id in point_by_id
        ][: max(0, weak_limit)]

        current_focus, focus_points = _focus(
            workspaces=workspaces,
            points_by_workspace=points_by_workspace,
            recent_minutes_by_workspace=recent_minutes_by_workspace,
            last_evidence_by_workspace=last_evidence_by_workspace,
            weak_points=weak_points,
            last_evidence_by_point=last_evidence_by_point,
        )
        common_errors = _common_errors(
            mistakes=mistake_rows, workspace_by_id=workspace_by_id, point_by_id=point_by_id
        )
        recent_learning = _recent_learning(
            activities=activities,
            workspace_by_id=workspace_by_id,
            scope=set(scope),
            now=current,
            zone=zone,
        )
        goals = await self._goals(
            now=current,
            workspace_by_id=workspace_by_id,
            points_by_workspace=points_by_workspace,
        )
        observations = await self._observations(
            now=current, activities=activities, workspace_by_id=workspace_by_id, zone=zone
        )
        insight = _rule_insight(
            mastery=mastery_items, weak_points=weak_points, now=current
        )

        return LearnerProfileOverview(
            user_id=self.user_id,
            display_name=getattr(user, "display_name", "") or "学习者",
            is_empty=is_empty,
            empty_hint=(
                "开始一次学习、练习或复习后，系统会逐步了解你的学习状态。"
                if is_empty
                else None
            ),
            knowledge_point_count=len(points),
            current_focus=current_focus if not is_empty else [],
            focus_points=focus_points if not is_empty else [],
            mastery_overview=mastery_items[: max(0, mastery_limit)] if not is_empty else [],
            weak_points=weak_points if not is_empty else [],
            common_errors=common_errors if not is_empty else [],
            goals=goals,
            recent_learning=recent_learning if not is_empty else [],
            observations=observations,
            insight=insight if not is_empty else ProfileInsight(
                text="", generated_by="rules", based_on=[], evidence={}, generated_at=current.isoformat()
            ),
            trend_window_days=TREND_WINDOW_DAYS,
            recent_window_days=RECENT_WINDOW_DAYS,
            computed_at=current.isoformat(),
            id=self.user_id,
            daily_goal_minutes=preference.daily_goal_minutes,
            daily_review_target=preference.daily_review_target,
            weekly_goal_days=preference.weekly_goal_days,
            timezone_name=preference.timezone_name,
            preferred_mode=preference.preferred_mode,
            reminder_time=preference.reminder_time,
        )

    async def _goals(
        self,
        *,
        now: datetime,
        workspace_by_id: dict[str, Workspace],
        points_by_workspace: dict[str, list[KnowledgePoint]],
    ) -> list[GoalItem]:
        progress = await goal_service.get_goals(self.db, now=now, user_id=self.user_id)
        items: list[GoalItem] = []
        plan_seeded = False
        workspace_goals = sorted(
            progress.get("workspace_goals", []),
            key=lambda row: (row.get("target_date") or "9999", row.get("id") or ""),
        )
        for row in workspace_goals:
            workspace = workspace_by_id.get(row.get("workspace_id") or "")
            points = points_by_workspace.get(row.get("workspace_id") or "", [])
            items.append(
                _goal_item(
                    row=row,
                    title=_goal_title(row["metric"], row["target"], workspace.name if workspace else None),
                    points=points if not plan_seeded else [],
                )
            )
            plan_seeded = True
        for metric in goal_service.GLOBAL_METRICS:
            row = progress.get(metric)
            if not isinstance(row, dict):
                continue
            points = [point for row_points in points_by_workspace.values() for point in row_points]
            items.append(
                _goal_item(
                    row=row,
                    title=_goal_title(metric, row["target"], None),
                    points=points if not plan_seeded and metric == "overall_mastery" else [],
                )
            )
            if not plan_seeded and metric == "overall_mastery":
                plan_seeded = True
        return items[:MAX_GOAL_ITEMS]

    async def _observations(
        self,
        *,
        now: datetime,
        activities: list[StudyActivity],
        workspace_by_id: dict[str, Workspace],
        zone: ZoneInfo,
    ) -> LearningObservations:
        cutoff = now - timedelta(days=60)
        sessions = list(
            (
                await self.db.execute(
                    select(StudySession).where(
                        StudySession.user_id == self.user_id,
                        StudySession.started_at >= cutoff,
                        StudySession.active_seconds > 0,
                    )
                )
            ).scalars().all()
        )
        average = _average([row.active_seconds / 60 for row in sessions])
        period_counts: dict[str, int] = defaultdict(int)
        for row in activities:
            if row.workspace_id not in workspace_by_id:
                continue
            hour = _aware(row.occurred_at).astimezone(zone).hour
            period_counts["morning" if hour < 12 else "afternoon" if hour < 18 else "evening"] += 1
        preferred = max(period_counts, key=lambda key: period_counts[key]) if period_counts else None
        deep_modes = [
            row
            for row in activities
            if isinstance(row.payload, dict) and row.payload.get("mode") in {"deep", "deep_dive"}
        ]
        conversation_modes = [
            row
            for row in activities
            if isinstance(row.payload, dict) and row.payload.get("mode")
        ]
        deep_ratio = len(deep_modes) / len(conversation_modes) if conversation_modes else None
        notes: list[str] = []
        if average is not None:
            notes.append(f"平均学习会话约 {round(average)} 分钟")
        if preferred is not None:
            label = {"morning": "上午", "afternoon": "下午", "evening": "晚上"}[preferred]
            notes.append(f"{label}学习频率较高")
        if deep_ratio is not None and deep_ratio >= 0.5:
            notes.append("最近更常选择深入学习")
        return LearningObservations(
            average_session_minutes=_round(average, 1) if average is not None else None,
            preferred_period=preferred,
            preferred_period_label=(
                {"morning": "上午", "afternoon": "下午", "evening": "晚上"}[preferred]
                if preferred
                else None
            ),
            deep_mode_ratio=_round(deep_ratio) if deep_ratio is not None else None,
            notes=notes,
        )


def _goal_item(*, row: dict, title: str, points: list[KnowledgePoint]) -> GoalItem:
    completed: list[str] = []
    learning: list[str] = []
    pending: list[str] = []
    for point in sorted(points, key=lambda item: (-item.mastery, item.title)):
        status, _ = mastery_band(point.mastery)
        bucket = completed if status in {"mastered", "proficient"} else learning if status in {"learning", "weak"} else pending
        if len(bucket) < MAX_GOAL_POINTS_PER_BUCKET:
            bucket.append(point.title)
    return GoalItem(
        id=row.get("id"),
        title=title,
        scope_type=row.get("scope_type", "global"),
        metric=row.get("metric", ""),
        target_value=float(row.get("target", 0.0)),
        actual=float(row.get("actual", 0.0)),
        progress=min(1.0, max(0.0, float(row.get("ratio", 0.0)))),
        status=row.get("status", "not_started"),
        target_date=row.get("target_date"),
        workspace_id=row.get("workspace_id"),
        completed=completed,
        learning=learning,
        pending=pending,
    )


def _workspace_mastery_item(
    *,
    workspace: Workspace,
    points: list[KnowledgePoint],
    trend_by_point: dict[str, float | None],
    last_evidence_at: datetime | None,
    last_evidence_by_point: dict[str, datetime],
    now: datetime,
    include_children: bool,
    child_limit: int | None,
) -> MasteryItem:
    scores = [float(point.mastery) for point in points]
    score = _average(scores) or 0.0
    status, label = mastery_band(score)
    trends = [trend for trend in (trend_by_point.get(point.id) for point in points) if trend is not None]
    trend = _average(trends) if trends else None
    stale_days = int((now - last_evidence_at).days) if last_evidence_at else None
    confidence, note = mastery_confidence(stale_days)
    children: list[MasteryItem] = []
    if include_children:
        ordered = sorted(points, key=lambda item: (-item.mastery, item.title))
        if child_limit:
            ordered = ordered[:child_limit]
        for point in ordered:
            point_status, point_label = mastery_band(point.mastery)
            point_evidence = last_evidence_by_point.get(point.id)
            point_days = int((now - point_evidence).days) if point_evidence else None
            point_confidence, point_note = mastery_confidence(point_days)
            children.append(
                MasteryItem(
                    name=point.title,
                    score=_round(point.mastery),
                    status=point_status,  # type: ignore[arg-type]
                    status_label=point_label,
                    workspace_id=workspace.id,
                    knowledge_point_id=point.id,
                    trend=_round(trend_by_point[point.id]) if trend_by_point.get(point.id) is not None else None,
                    confidence=point_confidence,
                    confidence_note=point_note,
                    last_evidence_at=_iso(point_evidence),
                )
            )
    return MasteryItem(
        name=workspace.name,
        score=_round(score),
        status=status,  # type: ignore[arg-type]
        status_label=label,
        workspace_id=workspace.id,
        knowledge_point_count=len(points),
        trend=_round(trend) if trend is not None else None,
        confidence=confidence,
        confidence_note=note,
        last_evidence_at=_iso(last_evidence_at),
        children=children,
    )


def _weak_point_item(
    *,
    point: KnowledgePoint,
    area: str,
    state: WeakKnowledgeState,
    attempts: list[QuizAttempt],
    reviews: list[ReviewLog],
    mistakes: list[MistakeRecord],
    last_evidence_at: datetime | None,
    now: datetime,
    include_evidence: bool,
) -> WeakPointItem:
    status, status_label = mastery_band(point.mastery)
    band, band_label = weakness_band(state.weakness_score)
    graded = [attempt for attempt in attempts if attempt.is_correct is not None]
    accuracy = (
        sum(1 for attempt in graded[:RECENT_ATTEMPT_LIMIT] if attempt.is_correct)
        / len(graded[:RECENT_ATTEMPT_LIMIT])
        if graded[:RECENT_ATTEMPT_LIMIT]
        else None
    )
    unresolved_rows = len(mistakes)
    repeat_errors = sum(max(1, row.wrong_count) for row in mistakes)
    stale_days = int((now - last_evidence_at).days) if last_evidence_at else None
    evidence = WeakPointEvidence(
        recent_attempts=(
            [
                AttemptEvidenceItem(
                    correct=attempt.is_correct,
                    submitted_at=_iso(attempt.submitted_at),
                    duration_seconds=max(0, int(attempt.duration_seconds or 0)),
                )
                for attempt in attempts[:RECENT_ATTEMPT_LIMIT]
            ]
            if include_evidence
            else []
        ),
        attempt_accuracy=_round(accuracy) if accuracy is not None else None,
        recent_reviews=(
            [
                ReviewEvidenceItem(
                    rating=int(review.rating),
                    label=REVIEW_RATING_LABELS.get(int(review.rating), "未记录"),
                    reviewed_at=_iso(review.reviewed_at),
                )
                for review in reviews[:RECENT_REVIEW_LIMIT]
            ]
            if include_evidence
            else []
        ),
        mistake_count=unresolved_rows,
        repeat_error_count=repeat_errors,
        mistake_patterns=(
            _mistake_patterns(mistakes) if include_evidence else []
        ),
        last_studied_at=_iso(last_evidence_at),
        stale_days=stale_days,
        state_note=WEAKNESS_STATE_NOTES.get(band, ""),
        components={
            "accuracy": _round(state.accuracy_component or 0.0),
            "repeat_error": _round(state.repeat_error_component or 0.0),
            "review_feedback": _round(state.review_feedback_component or 0.0),
            "response_time": _round(state.response_time_component or 0.0),
            "recency": _round(state.recency_component or 0.0),
        },
    )
    return WeakPointItem(
        knowledge_point_id=point.id,
        name=point.title,
        workspace_id=point.workspace_id,
        area=area,
        mastery=_round(point.mastery),
        mastery_status=status,  # type: ignore[arg-type]
        mastery_status_label=status_label,
        weakness_score=_round(min(1.0, max(0.0, float(state.weakness_score) / 100))),
        weakness_band=band,  # type: ignore[arg-type]
        weakness_band_label=band_label,
        reasons=_reason_texts(
            point=point,
            state=state,
            attempts=attempts,
            reviews=reviews,
            unresolved_mistakes=unresolved_rows,
            stale_days=stale_days,
        ),
        actions=_weak_actions(state, point),
        evidence=evidence,
    )


def _mistake_patterns(mistakes: list[MistakeRecord], limit: int = 3) -> list[MistakePatternItem]:
    grouped: dict[str, MistakePatternItem] = {}
    for row in sorted(mistakes, key=lambda item: _aware(item.last_wrong_at), reverse=True):
        pattern = (row.error_reason or "").strip()
        if not pattern:
            continue
        current = grouped.get(pattern)
        if current is None:
            grouped[pattern] = MistakePatternItem(
                pattern=pattern,
                count=max(1, row.wrong_count),
                last_wrong_at=_iso(row.last_wrong_at),
            )
        else:
            current.count += max(1, row.wrong_count)
    return list(grouped.values())[:limit]


def _latest(values: list[datetime | None]) -> datetime | None:
    aware = [_aware(value) for value in values if value]
    return max(aware, default=None)


def _last_evidence_by_point(
    *,
    activities: list[StudyActivity],
    attempts_by_point: dict[str, list[QuizAttempt]],
    reviews_by_point: dict[str, list[ReviewLog]],
    states: list[WeakKnowledgeState],
    point_by_id: dict[str, KnowledgePoint],
) -> dict[str, datetime]:
    result: dict[str, datetime] = {}

    def record(point_id: str, value: datetime | None) -> None:
        if value is None or point_id not in point_by_id:
            return
        current = result.get(point_id)
        aware = _aware(value)
        if current is None or aware > current:
            result[point_id] = aware

    for row in activities:
        payload = row.payload if isinstance(row.payload, dict) else {}
        point_id = payload.get("knowledge_point_id")
        if isinstance(point_id, str):
            record(point_id, row.occurred_at)
    for point_id, rows in attempts_by_point.items():
        record(point_id, _latest([row.submitted_at for row in rows]))
    for point_id, rows in reviews_by_point.items():
        record(point_id, _latest([row.reviewed_at for row in rows]))
    for state in states:
        evidence = state.evidence if isinstance(state.evidence, dict) else {}
        raw = evidence.get("last_relevant_activity_at")
        if isinstance(raw, str):
            try:
                record(state.knowledge_point_id, datetime.fromisoformat(raw))
            except ValueError:
                continue
    return result


def _last_evidence_by_workspace(
    *,
    activities: list[StudyActivity],
    points: list[KnowledgePoint],
    last_evidence_by_point: dict[str, datetime],
    workspace_ids: list[str],
) -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    for row in activities:
        if row.workspace_id in workspace_ids and row.workspace_id:
            value = _aware(row.occurred_at)
            if row.workspace_id not in result or value > result[row.workspace_id]:
                result[row.workspace_id] = value
    for point in points:
        value = last_evidence_by_point.get(point.id)
        if value is None:
            continue
        current = result.get(point.workspace_id)
        if current is None or value > current:
            result[point.workspace_id] = value
    return result


def _trend_by_point(
    *,
    activities: list[StudyActivity],
    points: list[KnowledgePoint],
    point_by_id: dict[str, KnowledgePoint],
    now: datetime,
) -> dict[str, float | None]:
    """用 mastery_changed 事件重建 14 天前的基线，缺失基线视为未变化。"""
    window_start = now - timedelta(days=TREND_WINDOW_DAYS)
    events: dict[str, list[StudyActivity]] = defaultdict(list)
    for row in activities:
        if row.activity_type != "mastery_changed":
            continue
        payload = row.payload if isinstance(row.payload, dict) else {}
        point_id = payload.get("knowledge_point_id")
        if isinstance(point_id, str) and point_id in point_by_id:
            events[point_id].append(row)
    result: dict[str, float | None] = {}
    for point in points:
        rows = sorted(events.get(point.id, []), key=lambda row: _aware(row.occurred_at))
        before = [row for row in rows if _aware(row.occurred_at) <= window_start]
        after = [row for row in rows if _aware(row.occurred_at) > window_start]
        baseline: float | None = None
        if before:
            baseline = float((before[-1].payload or {}).get("after_mastery", point.mastery))
        elif after:
            baseline = float((after[0].payload or {}).get("before_mastery", point.mastery))
        result[point.id] = None if baseline is None else _round(float(point.mastery) - baseline)
    return result


def _recent_minutes_by_workspace(
    *,
    activities: list[StudyActivity],
    scope: set[str],
    now: datetime,
    days: int,
) -> dict[str, float]:
    cutoff = now - timedelta(days=days)
    totals: dict[str, float] = defaultdict(float)
    for row in activities:
        if row.workspace_id not in scope or _aware(row.occurred_at) < cutoff:
            continue
        if row.activity_type in {"mastery_changed", "weakness_changed"}:
            continue
        totals[row.workspace_id] += (row.duration_seconds or 0) / 60
    return totals


def _focus(
    *,
    workspaces: list[Workspace],
    points_by_workspace: dict[str, list[KnowledgePoint]],
    recent_minutes_by_workspace: dict[str, float],
    last_evidence_by_workspace: dict[str, datetime],
    weak_points: list[WeakPointItem],
    last_evidence_by_point: dict[str, datetime],
) -> tuple[list[FocusItem], list[FocusItem]]:
    weak_by_workspace: dict[str, int] = defaultdict(int)
    for point in weak_points:
        weak_by_workspace[point.workspace_id] += 1

    def rank_key(workspace: Workspace) -> tuple:
        last = last_evidence_by_workspace.get(workspace.id)
        return (
            -(last.timestamp() if last else 0.0),
            -recent_minutes_by_workspace.get(workspace.id, 0.0),
            -weak_by_workspace.get(workspace.id, 0),
            workspace.name,
        )

    ranked = sorted(
        (
            workspace
            for workspace in workspaces
            if points_by_workspace.get(workspace.id)
            and (
                recent_minutes_by_workspace.get(workspace.id, 0.0) > 0
                or weak_by_workspace.get(workspace.id, 0)
            )
        ),
        key=rank_key,
    )[:MAX_FOCUS_AREAS]
    areas = [
        FocusItem(
            name=workspace.name,
            kind="workspace",
            workspace_id=workspace.id,
            recent_minutes=_round(recent_minutes_by_workspace.get(workspace.id, 0.0), 1),
            reason=(
                f"最近 {TREND_WINDOW_DAYS} 天学习 {round(recent_minutes_by_workspace.get(workspace.id, 0.0))} 分钟"
                if recent_minutes_by_workspace.get(workspace.id, 0.0) > 0
                else "存在需要巩固的薄弱知识"
            ),
        )
        for workspace in ranked
    ]
    focus_points: list[FocusItem] = []
    for workspace in ranked[:2]:
        candidates = sorted(
            points_by_workspace.get(workspace.id, []),
            key=lambda point: (
                -(last_evidence_by_point[point.id].timestamp() if point.id in last_evidence_by_point else 0),
                -point.importance,
                point.title,
            ),
        )
        for point in candidates:
            if len(focus_points) >= MAX_FOCUS_POINTS:
                break
            reason = "最近学习" if point.id in last_evidence_by_point else "目标知识点"
            focus_points.append(
                FocusItem(
                    name=point.title,
                    kind="knowledge_point",
                    workspace_id=workspace.id,
                    knowledge_point_id=point.id,
                    recent_minutes=None,
                    reason=reason,
                )
            )
    return areas, focus_points


def _common_errors(
    *,
    mistakes: list[MistakeRecord],
    workspace_by_id: dict[str, Workspace],
    point_by_id: dict[str, KnowledgePoint],
) -> list[CommonErrorItem]:
    """错误事实 → 规则聚合；没有记录错误原因时不编造归纳。"""
    grouped: dict[tuple[str, str], tuple[CommonErrorItem, datetime]] = {}
    for row in mistakes:
        pattern = (row.error_reason or "").strip()
        if not pattern:
            continue
        workspace = workspace_by_id.get(row.workspace_id)
        point = point_by_id.get(row.knowledge_point_id or "")
        key = (workspace.name if workspace else "未归类", pattern)
        occurred = _aware(row.last_wrong_at)
        current = grouped.get(key)
        count = max(1, row.wrong_count)
        if current is None:
            grouped[key] = (
                CommonErrorItem(
                    area=workspace.name if workspace else "未归类",
                    pattern=pattern,
                    count=count,
                    knowledge_point_id=point.id if point else None,
                    knowledge_point_title=point.title if point else None,
                    last_wrong_at=_iso(row.last_wrong_at),
                ),
                occurred,
            )
        else:
            item, latest = current
            item.count += count
            if occurred > latest:
                item.last_wrong_at = _iso(row.last_wrong_at)
                grouped[key] = (item, occurred)
    return sorted(
        (item for item, _ in grouped.values()),
        key=lambda item: (-item.count, item.area, item.pattern),
    )[:MAX_COMMON_ERRORS]


def _recent_learning(
    *,
    activities: list[StudyActivity],
    workspace_by_id: dict[str, Workspace],
    scope: set[str],
    now: datetime,
    zone: ZoneInfo,
) -> list[RecentLearningItem]:
    buckets: dict[date, dict[str, dict]] = defaultdict(dict)
    for row in activities:
        if row.workspace_id not in scope or row.activity_type in {"mastery_changed", "weakness_changed"}:
            continue
        local = _aware(row.occurred_at).astimezone(zone)
        local_date = local.date()
        workspace_id = row.workspace_id or ""
        entry = buckets[local_date].get(workspace_id)
        minutes = (row.duration_seconds or 0) / 60
        if entry is None:
            buckets[local_date][workspace_id] = {
                "minutes": minutes,
                "count": 1,
                "last": local,
            }
        else:
            entry["minutes"] += minutes
            entry["count"] += 1
            if local > entry["last"]:
                entry["last"] = local
    today = now.astimezone(zone).date()
    items: list[RecentLearningItem] = []
    for local_date in sorted(buckets, reverse=True)[:MAX_RECENT_DAYS]:
        areas = [
            RecentLearningArea(
                name=workspace_by_id[workspace_id].name if workspace_id in workspace_by_id else "未归类学习",
                workspace_id=workspace_id or None,
                minutes=_round(entry["minutes"], 1),
            )
            for workspace_id, entry in buckets[local_date].items()
        ]
        areas.sort(key=lambda area: (-area.minutes, area.name))
        items.append(
            RecentLearningItem(
                date=local_date.isoformat(),
                label=_day_label(local_date, today),
                minutes=_round(sum(area.minutes for area in areas), 1),
                activity_count=sum(entry["count"] for entry in buckets[local_date].values()),
                last_studied_at=_iso(max(entry["last"] for entry in buckets[local_date].values())),
                areas=areas,
            )
        )
    return items
