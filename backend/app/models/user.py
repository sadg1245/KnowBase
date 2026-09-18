"""账号、学习偏好与学习领域模型（第一阶段账号基础）。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.models.base import Base


AVATAR_KINDS = ("upload", "url", "none")


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """认证与公开资料。单账号部署下只会有一条可登录记录。"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(80), nullable=False, default="学习者")
    avatar_kind = Column(String(10), nullable=False, default="none")
    avatar_value = Column(String(1024), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now
    )

    @property
    def password_configured(self) -> bool:
        return bool(self.password_hash)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"


class LearningPreference(Base):
    """与用户一对一的当前学习偏好。"""

    __tablename__ = "learning_preferences"

    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    daily_goal_minutes = Column(Integer, nullable=False, default=25)
    daily_review_target = Column(Integer, nullable=False, default=10)
    weekly_goal_days = Column(Integer, nullable=False, default=5)
    timezone_name = Column(String(100), nullable=False, default="Asia/Shanghai")
    preferred_mode = Column(String(30), nullable=False, default="explain")
    reminder_time = Column(String(5), nullable=True, default="20:00")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now
    )


class LearningDomain(Base):
    """用户自有的学习领域；名称在同一用户内唯一。"""

    __tablename__ = "learning_domains"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_learning_domains_user_name"),
    )

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True, default="")
    color = Column(String(20), nullable=False, default="#1f7a8c")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now(), onupdate=_now
    )

    def __repr__(self) -> str:
        return f"<LearningDomain(id={self.id}, name={self.name})>"
