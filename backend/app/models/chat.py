"""Persistent learning conversations, notes, feedback, and retrieval audit models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(255), nullable=False, default="default", index=True)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(255), nullable=False, default="新学习会话")
    selected_document_ids = Column(JSON, nullable=False, default=list)
    preferred_mode = Column(String(20), nullable=False, default="simple")
    strict_sources = Column(Boolean, nullable=False, default=True)
    is_favorite = Column(Boolean, nullable=False, default=False, index=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)
    last_message_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_chat_sessions_user_activity", "user_id", "last_message_at"),
    )


class LearningNote(Base):
    __tablename__ = "learning_notes"

    id = Column(String(36), primary_key=True, default=_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    source_snapshot = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    __table_args__ = (
        UniqueConstraint("message_id", name="uq_learning_notes_message"),
    )


class ChatFeedback(Base):
    __tablename__ = "chat_feedback"

    id = Column(String(36), primary_key=True, default=_uuid)
    message_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, default="default")
    helpful = Column(Boolean, nullable=False)
    category = Column(String(30), nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now)

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_chat_feedback_message_user"),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(255), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    source_file = Column(String(512), nullable=False)
    page_num = Column(Integer, nullable=True)
    heading = Column(String(512), nullable=True)
    heading_level = Column(Integer, nullable=True)
    section_path = Column(JSON, nullable=False, default=list)
    chunk_index = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    tokenized_content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())

    __table_args__ = (
        Index("ix_document_chunks_workspace_document", "workspace_id", "document_id"),
    )


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id = Column(String(36), primary_key=True, default=_uuid)
    session_id = Column(String(36), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    user_message_id = Column(String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    query = Column(Text, nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    document_ids = Column(JSON, nullable=False, default=list)
    vector_succeeded = Column(Boolean, nullable=False, default=False)
    keyword_succeeded = Column(Boolean, nullable=False, default=False)
    degradation_reason = Column(Text, nullable=True)
    vector_top_k = Column(Integer, nullable=False, default=20)
    keyword_top_k = Column(Integer, nullable=False, default=20)
    selected_top_k = Column(Integer, nullable=False, default=8)
    config_snapshot = Column(JSON, nullable=False, default=dict)
    evidence_status = Column(String(20), nullable=False, default="insufficient")
    top_score = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), index=True)


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"

    id = Column(String(36), primary_key=True, default=_uuid)
    retrieval_run_id = Column(String(36), ForeignKey("retrieval_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(255), nullable=False, index=True)
    document_id = Column(String(36), nullable=True, index=True)
    source_file = Column(String(512), nullable=False, default="")
    page_num = Column(Integer, nullable=True)
    heading = Column(String(512), nullable=True)
    content_snapshot = Column(Text, nullable=False, default="")
    vector_rank = Column(Integer, nullable=True)
    keyword_rank = Column(Integer, nullable=True)
    vector_score = Column(Float, nullable=False, default=0.0)
    keyword_score = Column(Float, nullable=False, default=0.0)
    fusion_score = Column(Float, nullable=False, default=0.0)
    rerank_score = Column(Float, nullable=False, default=0.0)
    final_rank = Column(Integer, nullable=True)
    selected_as_evidence = Column(Boolean, nullable=False, default=False)
    cited_in_answer = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("retrieval_run_id", "chunk_id", name="uq_retrieval_hit_run_chunk"),
    )
