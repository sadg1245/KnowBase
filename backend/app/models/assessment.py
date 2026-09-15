"""Durable persistence models for assessment, mistakes, and follow-up work."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class QuizSet(Base):
    __tablename__ = "quiz_sets"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False, default="")
    document_ids = Column(JSON, nullable=False, default=list)
    knowledge_point_ids = Column(JSON, nullable=False, default=list)
    section_filters = Column(JSON, nullable=False, default=list)
    question_count = Column(Integer, nullable=False, default=0)
    difficulty = Column(String(20), nullable=False, default="medium")
    question_types = Column(JSON, nullable=False, default=list)
    strict_sources = Column(Boolean, nullable=False, default=False)
    answer_mode = Column(String(20), nullable=False, default="sequential")
    duration_limit_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="generating")
    generation_model = Column(String(255), nullable=True)
    generation_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    questions = relationship("QuizQuestion", cascade="all, delete-orphan")
    runs = relationship("QuizRun", back_populates="quiz_set", cascade="all, delete-orphan")


class QuizRun(Base):
    __tablename__ = "quiz_runs"
    __table_args__ = (UniqueConstraint("quiz_set_id", "round_number", name="uq_quiz_runs_set_round"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    quiz_set_id = Column(String(36), ForeignKey("quiz_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    round_number = Column(Integer, nullable=False)
    answer_mode = Column(String(20), nullable=False, default="sequential")
    # SQL NULL is a complete paper; a non-empty immutable list scopes a redo.
    question_ids = Column(JSON(none_as_null=True), nullable=True)
    status = Column(String(20), nullable=False, default="not_started")
    started_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    elapsed_seconds = Column(Integer, nullable=False, default=0)
    score = Column(Float, nullable=False, default=0.0)
    max_score = Column(Float, nullable=False, default=0.0)
    correct_count = Column(Integer, nullable=False, default=0)
    graded_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    quiz_set = relationship("QuizSet", back_populates="runs")
    attempts = relationship("QuizAttempt", back_populates="quiz_run", cascade="all, delete-orphan")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (UniqueConstraint("quiz_run_id", "question_id", "attempt_number", name="uq_quiz_attempts_run_question_number"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    quiz_set_id = Column(String(36), ForeignKey("quiz_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    quiz_run_id = Column(String(36), ForeignKey("quiz_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(String(36), ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number = Column(Integer, nullable=False)
    user_answer = Column(JSON, nullable=False, default=dict)
    is_correct = Column(Boolean, nullable=True)
    score = Column(Float, nullable=True)
    max_score = Column(Float, nullable=False, default=1.0)
    evaluation_status = Column(String(20), nullable=False, default="graded")
    feedback = Column(JSON, nullable=True)
    error_reason = Column(Text, nullable=True)
    duration_seconds = Column(Integer, nullable=False, default=0)
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())

    quiz_run = relationship("QuizRun", back_populates="attempts")
    question = relationship("QuizQuestion")


class MistakeRecord(Base):
    __tablename__ = "mistake_records"
    __table_args__ = (UniqueConstraint("question_id", name="uq_mistake_records_question"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    question_id = Column(String(36), ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    latest_attempt_id = Column(String(36), ForeignKey("quiz_attempts.id", ondelete="SET NULL"), nullable=True)
    user_answer_snapshot = Column(JSON, nullable=True)
    correct_answer_snapshot = Column(JSON, nullable=True)
    error_reason = Column(Text, nullable=True)
    source_snapshot = Column(JSON, nullable=False, default=list)
    wrong_count = Column(Integer, nullable=False, default=1)
    redo_count = Column(Integer, nullable=False, default=0)
    consecutive_correct = Column(Integer, nullable=False, default=0)
    mastery_status = Column(String(20), nullable=False, default="unresolved", index=True)
    first_wrong_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    last_wrong_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    last_redone_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class WeakKnowledgeState(Base):
    __tablename__ = "weak_knowledge_states"
    __table_args__ = (UniqueConstraint("knowledge_point_id", name="uq_weak_knowledge_states_point"),)

    id = Column(String(36), primary_key=True, default=_uuid)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    weakness_score = Column(Float, nullable=False, default=0.0, index=True)
    accuracy_component = Column(Float, nullable=False, default=0.0)
    repeat_error_component = Column(Float, nullable=False, default=0.0)
    review_feedback_component = Column(Float, nullable=False, default=0.0)
    response_time_component = Column(Float, nullable=False, default=0.0)
    recency_component = Column(Float, nullable=False, default=0.0)
    evidence = Column(JSON, nullable=False, default=dict)
    recommended_actions = Column(JSON, nullable=False, default=list)
    calculated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())


class LearningTask(Base):
    __tablename__ = "learning_tasks"
    __table_args__ = (
        Index(
            "uq_learning_tasks_pending_point_type",
            "knowledge_point_id",
            "task_type",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_point_id = Column(String(36), ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True)
    task_type = Column(String(30), nullable=False)
    title = Column(String(255), nullable=False)
    path = Column(String(512), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    priority = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
