"""工作空间 ORM 模型。

`Workspace` 是知识库的内部兼容表示。前端继续统一显示“知识库”，
数据库表名与 API 路径保持不变，但所有权由 `owner_id` 强制约束。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, ForeignKey, String, Text, DateTime, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.models.base import Base


LEARNING_STATUSES = ("not_started", "learning", "paused", "completed")
COVER_KINDS = ("upload", "url", "none")


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("owner_id", "slug", name="uq_workspaces_owner_slug"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    owner_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    domain_id = Column(
        String(36),
        ForeignKey("learning_domains.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    learning_goal = Column(Text, nullable=True, default="")
    # 兼容字段：新代码以 domain_id 为准，响应仍返回领域名称。
    domain = Column(String(100), nullable=True, default="未分类")
    learning_status = Column(String(20), nullable=False, default="not_started")
    cover_kind = Column(String(10), nullable=False, default="none")
    cover_value = Column(String(1024), nullable=True)
    accent_color = Column(String(20), nullable=False, default="#1f7a8c")
    archived = Column(Boolean, nullable=False, default=False)
    slug = Column(String(255), nullable=False, index=True)
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
    learning_domain = relationship("LearningDomain", lazy="joined")

    def __repr__(self) -> str:
        return f"<Workspace(id={self.id}, name={self.name}, slug={self.slug})>"
