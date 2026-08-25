"""工作空间 ORM 模型。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, String, Text, DateTime, func
from sqlalchemy.orm import relationship

from app.models.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    learning_goal = Column(Text, nullable=True, default="")
    domain = Column(String(100), nullable=True, default="未分类")
    accent_color = Column(String(20), nullable=False, default="#1f7a8c")
    archived = Column(Boolean, nullable=False, default=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
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

    documents = relationship(
        "Document",
        back_populates="workspace",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    knowledge_points = relationship(
        "KnowledgePoint", back_populates="workspace", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, name={self.name}, slug={self.slug})>"
