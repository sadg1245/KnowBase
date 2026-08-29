"""个人学习闭环的数据模型。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
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
    origin_message_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True)
    question_type = Column(String(20), nullable=False, default="short")
    prompt = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    answer = Column(Text, nullable=False)
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
    title = Column(String(255), nullable=False)
    duration_seconds = Column(Integer, nullable=False, default=0)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)
