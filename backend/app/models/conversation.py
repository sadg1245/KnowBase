"""对话 ORM 模型，用于存储聊天记录。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, func

from app.models.base import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(255), nullable=False, index=True)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id = Column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    role = Column(
        String(20), nullable=False
    )  # 角色："user" 或 "assistant"
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)
    mode = Column(String(20), nullable=True)
    evidence_status = Column(String(20), nullable=True)
    retrieval_run_id = Column(
        String(36),
        ForeignKey("retrieval_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    follow_up_questions = Column(JSON, nullable=False, default=list)
    generation_status = Column(String(20), nullable=False, default="complete")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, role={self.role}, "
            f"created_at={self.created_at})>"
        )
