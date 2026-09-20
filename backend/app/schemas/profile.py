"""Validated contracts for the read-time learner profile.

画像由确定性事实聚合而来，因此每个数值字段都能追溯到 `knowledge_points`、
`weak_knowledge_states`、`mistake_records`、`quiz_attempts`、`review_logs`、
`learning_goals`、`study_activities` 与 `study_sessions`。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MasteryStatus = Literal["not_mastered", "weak", "learning", "mastered", "proficient"]
WeaknessBand = Literal["stable", "watch", "weak", "priority"]
WeakActionType = Literal["review", "practice", "explain", "reread", "example"]


class FocusItem(BaseModel):
    """一个正在被学习的方向：一级领域（知识库）或其中的知识点。"""

    name: str
    kind: Literal["workspace", "knowledge_point"] = "workspace"
    workspace_id: str | None = None
    knowledge_point_id: str | None = None
    recent_minutes: float | None = None
    reason: str | None = None


class MasteryItem(BaseModel):
    """掌握度条目；`children` 让完整画像页展开到知识点。"""

    name: str
    score: float = Field(ge=0, le=1)
    status: MasteryStatus
    status_label: str
    workspace_id: str | None = None
    knowledge_point_id: str | None = None
    knowledge_point_count: int = 0
    trend: float | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_note: str | None = None
    last_evidence_at: str | None = None
    children: list["MasteryItem"] = Field(default_factory=list)


class WeakAction(BaseModel):
    type: WeakActionType
    label: str
    path: str | None = None


class AttemptEvidenceItem(BaseModel):
    correct: bool | None = None
    submitted_at: str | None = None
    duration_seconds: int = 0


class ReviewEvidenceItem(BaseModel):
    rating: int
    label: str
    reviewed_at: str | None = None


class MistakePatternItem(BaseModel):
    pattern: str
    count: int
    last_wrong_at: str | None = None


class WeakPointEvidence(BaseModel):
    """回答“为什么系统认为这里薄弱”的全部依据。"""

    recent_attempts: list[AttemptEvidenceItem] = Field(default_factory=list)
    attempt_accuracy: float | None = Field(default=None, ge=0, le=1)
    recent_reviews: list[ReviewEvidenceItem] = Field(default_factory=list)
    mistake_count: int = 0
    repeat_error_count: int = 0
    mistake_patterns: list[MistakePatternItem] = Field(default_factory=list)
    last_studied_at: str | None = None
    stale_days: int | None = None
    state_note: str = ""
    components: dict[str, float] = Field(default_factory=dict)


class WeakPointItem(BaseModel):
    knowledge_point_id: str
    name: str
    workspace_id: str
    area: str
    mastery: float = Field(ge=0, le=1)
    mastery_status: MasteryStatus
    mastery_status_label: str
    weakness_score: float = Field(ge=0, le=1)
    weakness_band: WeaknessBand
    weakness_band_label: str
    reasons: list[str] = Field(default_factory=list)
    actions: list[WeakAction] = Field(default_factory=list)
    evidence: WeakPointEvidence = Field(default_factory=WeakPointEvidence)


class CommonErrorItem(BaseModel):
    area: str
    pattern: str
    count: int
    knowledge_point_id: str | None = None
    knowledge_point_title: str | None = None
    last_wrong_at: str | None = None


class GoalItem(BaseModel):
    id: str | None = None
    title: str
    scope_type: Literal["global", "workspace"]
    metric: str
    target_value: float
    actual: float
    progress: float = Field(ge=0, le=1)
    status: str
    target_date: str | None = None
    workspace_id: str | None = None
    completed: list[str] = Field(default_factory=list)
    learning: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)


class RecentLearningArea(BaseModel):
    name: str
    workspace_id: str | None = None
    minutes: float


class RecentLearningItem(BaseModel):
    date: str
    label: str
    minutes: float
    activity_count: int = 0
    last_studied_at: str | None = None
    areas: list[RecentLearningArea] = Field(default_factory=list)


class LearningObservations(BaseModel):
    """系统观察：只描述行为，不包装成人格标签。"""

    average_session_minutes: float | None = None
    preferred_period: Literal["morning", "afternoon", "evening"] | None = None
    preferred_period_label: str | None = None
    deep_mode_ratio: float | None = Field(default=None, ge=0, le=1)
    notes: list[str] = Field(default_factory=list)


class ProfileInsight(BaseModel):
    text: str
    generated_by: Literal["rules", "ai"] = "rules"
    based_on: list[str] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    model: str | None = None
    generated_at: str | None = None


class LearnerProfileOverview(BaseModel):
    """完整画像：首页卡片、完整画像页、Drawer 与 AI Tutor 共用的只读契约。"""

    user_id: str
    display_name: str
    is_empty: bool
    empty_hint: str | None = None
    knowledge_point_count: int = 0

    current_focus: list[FocusItem] = Field(default_factory=list)
    focus_points: list[FocusItem] = Field(default_factory=list)
    mastery_overview: list[MasteryItem] = Field(default_factory=list)
    weak_points: list[WeakPointItem] = Field(default_factory=list)
    common_errors: list[CommonErrorItem] = Field(default_factory=list)
    goals: list[GoalItem] = Field(default_factory=list)
    recent_learning: list[RecentLearningItem] = Field(default_factory=list)
    observations: LearningObservations = Field(default_factory=LearningObservations)
    insight: ProfileInsight

    trend_window_days: int
    recent_window_days: int
    computed_at: str

    # 旧 `/learning/profile` 的学习偏好字段保留：设置页、学习页与飞书提醒仍在读取。
    id: str
    daily_goal_minutes: int
    daily_review_target: int
    weekly_goal_days: int
    timezone_name: str
    preferred_mode: str
    reminder_time: str | None = None
