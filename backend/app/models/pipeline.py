"""Per-stage ingestion audit rows."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentPipelineEvent(Base):
    __tablename__ = "document_pipeline_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    detail = Column(Text, nullable=True)
    started_at = Column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_document_pipeline_events_document_node", "document_id", "node"),
    )
