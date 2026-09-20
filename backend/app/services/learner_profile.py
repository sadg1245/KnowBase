"""Read-time learner profile aggregation for the AI tutor prompt."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assessment import LearningTask, MistakeRecord, WeakKnowledgeState
from app.models.learning import KnowledgePoint, LearningGoal, StudyActivity
from app.models.user import LearningPreference, User
from app.models.workspace import Workspace
from app.services.hybrid_retrieval import _search_tokens

_CACHE: dict[tuple[str, str | None, tuple[str, ...]], tuple[float, "LearnerProfileSnapshot"]] = {}
_CACHE_MAX_ENTRIES = 256
_RECENT_WINDOW_DAYS = 14
_ROW_BUDGET = 20


@dataclass
class ProfileKnowledgePoint:
    knowledge_point_id: str
    title: str
    mastery: float
    status: str


@dataclass
class ProfileWeakPoint:
    knowledge_point_id: str
    title: str
    mastery: float
    weakness_score: float
    reason: str = ""


@dataclass
class ProfileMistake:
    knowledge_point_title: str
    pattern: str
    count: int


@dataclass
class LearnerProfileSnapshot:
    display_name: str
    preferred_mode: str
    goal_summary: str
    mastery: list[ProfileKnowledgePoint] = field(default_factory=list)
    weak_points: list[ProfileWeakPoint] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    common_mistakes: list[ProfileMistake] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.isoformat()
        return payload


@dataclass
class DifficultyPreference:
    """画像折算出的难度与内容类型偏好（只读，用于检索期软加权，§20.2/§20.3）。"""

    level: int | None = None
    min_difficulty: int | None = None
    max_difficulty: int | None = None
    preferred_content_types: list[str] = field(default_factory=list)
    basis: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.level is None and not self.preferred_content_types


def _level_from_mastery(mastery: float) -> int:
    """掌握度 0–1 折算到难度 1–5：0.0→1，1.0→5。"""
    return max(1, min(5, int(round(mastery * 4)) + 1))


def content_types_for_level(level: int) -> list[str]:
    """新手优先定义与直觉，熟练优先推导与综合练习（设计文档 §9.13）。"""
    if level <= 2:
        return ["definition", "concept", "intuition", "simple_example"]
    if level >= 4:
        return ["derivation", "formula", "advanced_example", "exercise", "solution"]
    return ["concept", "formula", "example", "code"]


def invalidate_profile_cache(user_id: str, workspace_id: str | None = None) -> None:
    """Drop cached snapshots; called by writers that change learning evidence."""
    for key in [
        key
        for key in _CACHE
        if key[0] == user_id
        and (workspace_id is None or key[1] is None or key[1] == workspace_id)
    ]:
        _CACHE.pop(key, None)


def _prune_cache(now: float) -> None:
    """Evict expired snapshots so an idle user's entry does not stay resident forever."""
    ttl = settings.PROFILE_CACHE_TTL_SECONDS
    expired = [key for key, (stamp, _) in _CACHE.items() if now - stamp >= ttl]
    for key in expired:
        _CACHE.pop(key, None)
    if len(_CACHE) <= _CACHE_MAX_ENTRIES:
        return
    for key, _ in sorted(_CACHE.items(), key=lambda item: item[1][0])[: len(_CACHE) - _CACHE_MAX_ENTRIES]:
        _CACHE.pop(key, None)


async def invalidate_workspace_profile(db: AsyncSession, workspace_id: str | None) -> None:
    """Resolve the workspace owner and drop that owner's cached snapshots."""
    if not workspace_id:
        return
    workspace = await db.get(Workspace, workspace_id)
    owner = getattr(workspace, "owner_id", None)
    if owner:
        invalidate_profile_cache(owner, workspace_id)


def _relevance(question: str, titles: list[str]) -> list[float]:
    tokens = {token.lower() for token in _search_tokens(question)}
    scores: list[float] = []
    for title in titles:
        lowered = title.lower()
        hits = sum(1 for token in tokens if token and token in lowered)
        scores.append(float(hits))
    return scores


def format_profile_block(snapshot: LearnerProfileSnapshot) -> str:
    """Render the profile block; it must never look like citable evidence."""
    lines = ["（以下信息不是资料证据，只能用于调整讲解方式、举例和难度）"]
    lines.append(f"- 称呼：{snapshot.display_name}")
    lines.append(f"- 学习目标：{snapshot.goal_summary}")
    if snapshot.weak_points:
        rendered = "；".join(
            f"{point.title}（掌握度 {round(point.mastery * 100)}%{f'，{point.reason}' if point.reason else ''}）"
            for point in snapshot.weak_points
        )
        lines.append(f"- 当前薄弱知识点：{rendered}")
    if snapshot.common_mistakes:
        rendered = "；".join(
            f"{item.knowledge_point_title} 上「{item.pattern}」出现 {item.count} 次"
            for item in snapshot.common_mistakes
        )
        lines.append(f"- 常见错误：{rendered}")
    if snapshot.recent_topics:
        lines.append(f"- 最近学习：{'、'.join(snapshot.recent_topics)}")
    if snapshot.next_actions:
        lines.append(f"- 建议的下一步：{'；'.join(snapshot.next_actions)}")
    return "\n".join(lines)


class LearnerProfileService:
    def __init__(self, db: AsyncSession, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    async def build(
        self,
        *,
        workspace_id: str | None,
        question: str,
        owned_workspace_ids: list[str] | None = None,
    ) -> LearnerProfileSnapshot:
        """Build the snapshot, scoped to workspaces this caller actually owns.

        ``workspace_id`` narrows the scope to one knowledge base; otherwise the scope is every
        workspace in ``owned_workspace_ids``. An empty scope fails closed and returns no
        workspace-derived rows, so a missing or forged id can never widen the query to other users.
        """
        owned = list(owned_workspace_ids or [])
        if workspace_id:
            scope = [workspace_id] if (
                owned_workspace_ids is None or workspace_id in owned
            ) else []
        else:
            scope = owned
        key = (self.user_id, workspace_id, tuple(sorted(scope)))
        cached = _CACHE.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < settings.PROFILE_CACHE_TTL_SECONDS:
            return cached[1]
        snapshot = await self._build_snapshot(
            workspace_id=workspace_id, question=question, scope=scope
        )
        _prune_cache(now)
        _CACHE[key] = (now, snapshot)
        return snapshot

    async def difficulty_preference(
        self,
        *,
        workspace_id: str | None = None,
        knowledge_point_ids: list[str] | None = None,
        owned_workspace_ids: list[str] | None = None,
    ) -> DifficultyPreference:
        """按知识点掌握度折算难度区间与内容类型偏好；没有记录时不加任何偏好。"""
        scope = [workspace_id] if workspace_id else list(owned_workspace_ids or [])
        query = select(KnowledgePoint.id, KnowledgePoint.mastery, KnowledgePoint.title)
        if knowledge_point_ids:
            query = query.where(KnowledgePoint.id.in_(list(knowledge_point_ids)))
        elif scope:
            query = query.where(KnowledgePoint.workspace_id.in_(scope))
        else:
            return DifficultyPreference(basis=["no_scope"])
        rows = (await self.db.execute(query)).all()
        if not rows:
            return DifficultyPreference(basis=["no_knowledge_point_evidence"])
        masteries = [float(row[1] or 0.0) for row in rows]
        average = sum(masteries) / len(masteries)
        level = _level_from_mastery(average)
        basis = [
            f"掌握度均值 {round(average * 100)}% → 难度档 {level}",
            f"参与折算的知识点 {len(rows)} 个",
        ]
        weak_titles = [
            str(row[2])
            for row in sorted(rows, key=lambda item: float(item[1] or 0.0))[:2]
            if row[2]
        ]
        if weak_titles:
            basis.append(f"最薄弱：{'、'.join(weak_titles)}")
        return DifficultyPreference(
            level=level,
            min_difficulty=max(1, level - 1),
            max_difficulty=min(5, level + 1),
            preferred_content_types=content_types_for_level(level),
            basis=basis,
        )

    async def _build_snapshot(
        self, *, workspace_id: str | None, question: str, scope: list[str]
    ) -> LearnerProfileSnapshot:
        user = await self.db.get(User, self.user_id)
        preference = (
            await self.db.execute(
                select(LearningPreference).where(LearningPreference.user_id == self.user_id)
            )
        ).scalar_one_or_none()
        goal = (
            await self.db.execute(
                select(LearningGoal)
                .where(LearningGoal.user_id == self.user_id, LearningGoal.is_active.is_(True))
                .order_by(LearningGoal.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        point_filter = [KnowledgePoint.workspace_id.in_(scope)]
        points = list(
            (
                await self.db.execute(
                    select(KnowledgePoint)
                    .where(*point_filter)
                    .order_by(KnowledgePoint.mastery.asc())
                    .limit(_ROW_BUDGET)
                )
            ).scalars().all()
        )
        titles = {point.id: point.title for point in points}

        weak_rows = list(
            (
                await self.db.execute(
                    select(WeakKnowledgeState)
                    .where(WeakKnowledgeState.workspace_id.in_(scope))
                    .order_by(WeakKnowledgeState.weakness_score.desc())
                    .limit(_ROW_BUDGET)
                )
            ).scalars().all()
        )
        missing_ids = [row.knowledge_point_id for row in weak_rows if row.knowledge_point_id not in titles]
        if missing_ids:
            extra = list(
                (
                await self.db.execute(
                    select(KnowledgePoint).where(KnowledgePoint.id.in_(missing_ids))
                )
            ).scalars().all()
        )
            titles.update({point.id: point.title for point in extra})

        mistake_rows = list(
            (
                await self.db.execute(
                    select(MistakeRecord)
                    .where(
                        MistakeRecord.workspace_id.in_(scope),
                        MistakeRecord.last_wrong_at
                        >= datetime.now(timezone.utc) - timedelta(days=_RECENT_WINDOW_DAYS),
                    )
                    .order_by(MistakeRecord.last_wrong_at.desc())
                    .limit(_ROW_BUDGET)
                )
            ).scalars().all()
        )
        task_rows = list(
            (
                await self.db.execute(
                    select(LearningTask)
                    .where(
                        LearningTask.status == "pending",
                        LearningTask.workspace_id.in_(scope),
                    )
                    .order_by(LearningTask.priority.desc())
                    .limit(_ROW_BUDGET)
                )
            ).scalars().all()
        )
        activity_rows = list(
            (
                await self.db.execute(
                    select(StudyActivity)
                    .where(StudyActivity.user_id == self.user_id)
                    .order_by(StudyActivity.occurred_at.desc())
                    .limit(_ROW_BUDGET)
                )
            ).scalars().all()
        )

        weak_points = [
            ProfileWeakPoint(
                knowledge_point_id=row.knowledge_point_id,
                title=titles.get(row.knowledge_point_id, "未命名知识点"),
                mastery=next(
                    (point.mastery for point in points if point.id == row.knowledge_point_id), 0.0
                ),
                weakness_score=row.weakness_score,
                reason=str((row.evidence or {}).get("reason", "")),
            )
            for row in weak_rows
            if row.knowledge_point_id in titles
        ]
        weak_points.sort(key=lambda item: item.knowledge_point_id)

        recent_topics: list[str] = []
        for row in activity_rows:
            if row.title and row.title not in recent_topics:
                recent_topics.append(row.title)

        mistakes: dict[tuple[str, str], ProfileMistake] = {}
        for row in mistake_rows:
            title = titles.get(row.knowledge_point_id or "", "未归类知识点")
            pattern = (row.error_reason or "").strip() or "答案类型或解题步骤出错"
            key = (title, pattern)
            if key in mistakes:
                mistakes[key].count += 1
            else:
                mistakes[key] = ProfileMistake(title, pattern, 1)

        scores = _relevance(question, [item.title for item in weak_points])
        relevant = sorted(
            (item for score, item in zip(scores, weak_points) if score > 0),
            key=lambda item: -item.weakness_score,
        )
        selected_weak = relevant[: settings.PROFILE_MAX_KNOWLEDGE_POINTS]
        mastery = [
            ProfileKnowledgePoint(item.knowledge_point_id, item.title, item.mastery, "weak")
            for item in selected_weak
        ]
        related_titles = {item.title for item in selected_weak}
        selected_mistakes = [
            item for item in mistakes.values() if item.knowledge_point_title in related_titles
        ][: settings.PROFILE_MAX_MISTAKES]
        next_actions = [row.title for row in task_rows[:3]]
        goal_summary = (
            f"日目标 {round(goal.target_value)} 分钟"
            if goal is not None
            else f"日目标 {getattr(preference, 'daily_goal_minutes', 30)} 分钟"
        )

        return LearnerProfileSnapshot(
            display_name=getattr(user, "display_name", "") or "学习者",
            preferred_mode=getattr(preference, "preferred_mode", "") or "simple",
            goal_summary=goal_summary,
            mastery=mastery,
            weak_points=selected_weak,
            recent_topics=recent_topics[:3] if selected_weak else recent_topics[:5],
            common_mistakes=selected_mistakes,
            next_actions=next_actions,
            generated_at=datetime.now(timezone.utc),
        )
