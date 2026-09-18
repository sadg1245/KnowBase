"""账号、当前用户与学习领域的请求/响应契约。"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class AuthStatus(BaseModel):
    configured: bool
    setup_required: bool
    login_required: bool = True


class SetupRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=200)
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class SessionResponse(BaseModel):
    token: str
    user: "UserProfileResponse"


class UserProfileResponse(BaseModel):
    id: str
    username: str
    display_name: str
    avatar_kind: Literal["upload", "url", "none"] = "none"
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None


class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    avatar_url: Optional[str] = None
    clear_avatar: bool = False


class PreferenceResponse(BaseModel):
    daily_goal_minutes: int = 25
    daily_review_target: int = 10
    weekly_goal_days: int = 5
    timezone_name: str = "Asia/Shanghai"
    preferred_mode: str = "explain"
    reminder_time: Optional[str] = None


class PreferenceUpdate(BaseModel):
    daily_goal_minutes: Optional[int] = Field(None, ge=5, le=480)
    daily_review_target: Optional[int] = Field(None, ge=1, le=200)
    weekly_goal_days: Optional[int] = Field(None, ge=1, le=7)
    timezone_name: Optional[str] = Field(None, min_length=1, max_length=100)
    preferred_mode: Optional[str] = Field(None, max_length=30)
    reminder_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class LearningDomainCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field("", max_length=500)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class LearningDomainUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class LearningDomainResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    color: str = "#1f7a8c"
    workspace_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


SessionResponse.model_rebuild()
