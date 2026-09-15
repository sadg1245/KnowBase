"""个人学习闭环的数据模型。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(String(36), primary_key=True, default=_uuid)
    display_name = Column(String(80), nullable=False, default="学习者")
    daily_goal_minutes = Column(Integer, nullable=False, default=25)
    daily_review_target = Column(Integer, nullable=False, default=10)
    weekly_goal_days = Column(Integer, nullable=False, default=5)
    timezone_name = Column(String(100), nullable=False, default="Asia/Shanghai")
    preferred_mode = Column(String(30), nullable=False, default="explain")
    reminder_time = Column(String(5), nullable=True, default="20:00")
    password_hash = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False, default="")
    explanation = Column(Text, nullable=False, default="")
    source_page = Column(Integer, nullable=True)
    source_heading = Column(String(255), nullable=True)
    importance = Column(Integer, nullable=False, default=3)
    difficulty = Column(Integer, nullable=False, default=2)
    mastery = Column(Float, nullable=False, default=0.0)
    tags = Column(JSON, nullable=False, default=list)
    is_key = Column(Boolean, nullable=False, default=False)
    mastery_status = Column(String(20), nullable=False, default="not_started", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    workspace = relationship("Workspace", back_populates="knowledge_points")
    cards = relationship("Flashcard", back_populates="knowledge_point", cascade="all, delete-orphan")


class Flashcard(Base):
    __tablename__ = "flashcards"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    origin_message_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=True, index=True)
    front = Column(Text, nullable=False)
    back = Column(Text, nullable=False)
    source_label = Column(String(512), nullable=True)
    tags = Column(JSON, nullable=False, default=list)
    difficulty = Column(Integer, nullable=False, default=2)
    mastery = Column(Float, nullable=False, default=0.0)
    mastery_status = Column(String(20), nullable=False, default="not_started", index=True)
    source_type = Column(String(30), nullable=False, default="manual", index=True)
    source_snapshot = Column(JSON, nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    interval_days = Column(Integer, nullable=False, default=0)
    ease = Column(Float, nullable=False, default=2.5)
    review_count = Column(Integer, nullable=False, default=0)
    algorithm_version = Column(String(20), nullable=False, default="simple_v1")
    scheduler_data = Column(JSON, nullable=False, default=dict)
    last_reviewed_at = Column(DateTime(timezone=True), nullable=True)
    total_review_seconds = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    knowledge_point = relationship("KnowledgePoint", back_populates="cards")
    reviews = relationship("ReviewLog", back_populates="card", cascade="all, delete-orphan")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id = Column(String(36), primary_key=True, default=_uuid)
    card_id = Column(String(36), ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)
    previous_interval = Column(Integer, nullable=False, default=0)
    next_interval = Column(Integer, nullable=False, default=1)
    duration_seconds = Column(Integer, nullable=False, default=0)
    previous_mastery = Column(Float, nullable=False, default=0.0)
    next_mastery = Column(Float, nullable=False, default=0.0)
    previous_status = Column(String(20), nullable=False, default="not_started")
    next_status = Column(String(20), nullable=False, default="learning")
    algorithm_version = Column(String(20), nullable=False, default="simple_v1")
    reviewed_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)

    card = relationship("Flashcard", back_populates="reviews")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    quiz_set_id = Column(String(36), ForeignKey("quiz_sets.id", ondelete="CASCADE"), nullable=True, index=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    origin_message_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True)
    question_type = Column(String(20), nullable=False, default="short")
    prompt = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    answer = Column(Text, nullable=False)
    difficulty_level = Column(String(20), nullable=False, default="medium")
    answer_payload = Column(JSON, nullable=True)
    grading_rubric = Column(JSON, nullable=True)
    source_snapshot = Column(JSON, nullable=False, default=list)
    strict_sources = Column(Boolean, nullable=False, default=False)
    generation_model = Column(String(255), nullable=True)
    position = Column(Integer, nullable=False, default=0)
    explanation = Column(Text, nullable=False, default="")
    source_label = Column(String(512), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    correct_attempts = Column(Integer, nullable=False, default=0)
    last_answer = Column(Text, nullable=True)
    last_correct = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())


class StudyActivity(Base):
    __tablename__ = "study_activities"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    activity_type = Column(String(30), nullable=False, index=True)
    event_key = Column(String(255), nullable=True, unique=True, index=True)
    source_type = Column(String(40), nullable=True, index=True)
    source_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    duration_seconds = Column(Integer, nullable=False, default=0)
    payload = Column(JSON, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)
    schema_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)


class StudySession(Base):
    __tablename__ = "study_sessions"
    __table_args__ = (
        Index(
            "uq_study_sessions_active_context",
            "context_type",
            "context_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    context_type = Column(String(20), nullable=False)
    context_id = Column(String(36), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
    active_seconds = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active", index=True)
    last_sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)


class LearningGoal(Base):
    __tablename__ = "learning_goals"
    __table_args__ = (
        Index(
            "uq_learning_goals_global_metric",
            "metric",
            unique=True,
            sqlite_where=text("scope_type = 'global'"),
            postgresql_where=text("scope_type = 'global'"),
        ),
        Index(
            "uq_learning_goals_workspace_metric",
            "workspace_id",
            "metric",
            unique=True,
            sqlite_where=text("scope_type = 'workspace'"),
            postgresql_where=text("scope_type = 'workspace'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    scope_type = Column(String(20), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    metric = Column(String(30), nullable=False, index=True)
    target_value = Column(Float, nullable=False)
    target_date = Column(Date, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)


class ReportSuggestion(Base):
    __tablename__ = "report_suggestions"
    __table_args__ = (
        UniqueConstraint(
            "period_type", "period_start", "timezone_name", "stats_hash",
            name="uq_report_suggestions_snapshot",
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    period_type = Column(String(10), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)
    timezone_name = Column(String(100), nullable=False)
    stats_hash = Column(String(64), nullable=False)
    stats_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="pending", index=True)
    suggestion = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)
