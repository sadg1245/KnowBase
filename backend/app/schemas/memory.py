"""Request and response schemas for tutor profile and learning memory."""

from typing import Literal

from pydantic import BaseModel, Field


MemoryKind = Literal["session_summary", "mistake_pattern", "preference", "insight", "manual"]


class MemoryCreate(BaseModel):
    kind: MemoryKind = "manual"
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=2000)
    workspace_id: str | None = None
    importance: float = Field(0.5, ge=0.0, le=1.0)


class MemoryUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    content: str | None = Field(None, min_length=1, max_length=2000)
    importance: float | None = Field(None, ge=0.0, le=1.0)
    is_active: bool | None = None


class MemoryResponse(BaseModel):
    id: str
    kind: str
    title: str
    content: str
    workspace_id: str | None
    source_refs: dict
    importance: float
    is_active: bool
    embedding_state: str
    use_count: int
    last_used_at: str | None
    created_at: str
    updated_at: str


class MemoryListResponse(BaseModel):
    items: list[MemoryResponse]
    total: int


class ProfileWeakPointResponse(BaseModel):
    knowledge_point_id: str
    title: str
    mastery: float
    weakness_score: float
    reason: str


class ProfileMistakeResponse(BaseModel):
    knowledge_point_title: str
    pattern: str
    count: int


class LearnerProfileResponse(BaseModel):
    display_name: str
    preferred_mode: str
    goal_summary: str
    mastery: list[dict]
    weak_points: list[ProfileWeakPointResponse]
    recent_topics: list[str]
    common_mistakes: list[ProfileMistakeResponse]
    next_actions: list[str]
    generated_at: str
