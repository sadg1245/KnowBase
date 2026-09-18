"""文档 ORM 模型。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON, func
from sqlalchemy.orm import relationship

from app.models.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # 状态值：pending / processing / ready / failed
    pipeline_stage = Column(String(20), nullable=True)
    error_message = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    outline = Column(Text, nullable=True)
    learning_status = Column(String(20), nullable=False, default="not_started")
    tags = Column(JSON, nullable=False, default=list)
    chapter_summaries = Column(JSON, nullable=False, default=list)
    core_concepts = Column(JSON, nullable=False, default=list)
    important_terms = Column(JSON, nullable=False, default=list)
    common_mistakes = Column(JSON, nullable=False, default=list)
    prerequisites = Column(JSON, nullable=False, default=list)
    learning_order = Column(JSON, nullable=False, default=list)
    review_points = Column(JSON, nullable=False, default=list)
    learning_error_message = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    learning_generated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    workspace = relationship("Workspace", back_populates="documents")

    def __repr__(self) -> str:
        return (
            f"<Document(id={self.id}, filename={self.filename}, status={self.status})>"
        )
