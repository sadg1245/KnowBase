"""Schemas used by the personal learning experience."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


CardSourceType = Literal["manual", "knowledge_point", "answer", "selection"]


def _normalized_tags(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = value.strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=80)
    daily_goal_minutes: Optional[int] = Field(None, ge=5, le=480)
    daily_review_target: Optional[int] = Field(None, ge=1, le=200)
    weekly_goal_days: Optional[int] = Field(None, ge=1, le=7)
    timezone_name: Optional[str] = Field(None, min_length=1, max_length=100)
    preferred_mode: Optional[str] = None
    reminder_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class KnowledgePointCreate(BaseModel):
    workspace_id: str
    document_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=255)
    summary: str = ""
    explanation: str = ""
    source_page: Optional[int] = None
    source_heading: Optional[str] = None
    importance: int = Field(3, ge=1, le=5)
    difficulty: int = Field(2, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)


class KnowledgePointUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    explanation: Optional[str] = None
    importance: Optional[int] = Field(None, ge=1, le=5)
    difficulty: Optional[int] = Field(None, ge=1, le=5)
    mastery: Optional[float] = Field(None, ge=0, le=1)
    tags: Optional[list[str]] = None
    is_key: Optional[bool] = None
    mastery_status: Optional[Literal["not_started", "learning", "mastered"]] = None


class KnowledgePointMerge(BaseModel):
    target_id: str
    source_ids: list[str] = Field(..., min_length=1, max_length=50)


class FlashcardCreate(BaseModel):
    workspace_id: str
    knowledge_point_id: Optional[str] = None
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    source_label: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    difficulty: int = Field(2, ge=1, le=5)
    source_type: CardSourceType = "manual"
    source_snapshot: Optional[dict[str, Any]] = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return _normalized_tags(values) or []


class FlashcardUpdate(BaseModel):
    workspace_id: Optional[str] = None
    front: Optional[str] = Field(None, min_length=1)
    back: Optional[str] = Field(None, min_length=1)
    source_label: Optional[str] = None
    tags: Optional[list[str]] = None
    difficulty: Optional[int] = Field(None, ge=1, le=5)
    due_at: Optional[datetime] = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str] | None) -> list[str] | None:
        return _normalized_tags(values)


class FlashcardSelectionCreate(BaseModel):
    workspace_id: str
    document_id: str
    front: str = Field(..., min_length=1)
    back: str = Field(..., min_length=1)
    source_excerpt: str = Field(..., min_length=1)
    source_page: Optional[int] = Field(None, ge=1)
    source_heading: Optional[str] = Field(None, max_length=255)
    tags: list[str] = Field(default_factory=list)
    difficulty: int = Field(2, ge=1, le=5)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return _normalized_tags(values) or []


class FlashcardGenerateRequest(BaseModel):
    knowledge_point_ids: list[str] = Field(default_factory=list, max_length=100)


class ReviewRequest(BaseModel):
    rating: Literal[1, 2, 3, 4]
    duration_seconds: int = Field(0, ge=0, le=3600)


class QuizGenerateRequest(BaseModel):
    workspace_id: str
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    count: int = Field(5, ge=1, le=30)
    question_type: Literal["choice", "true_false", "short", "mixed"] = "mixed"


class QuizSubmitRequest(BaseModel):
    answer: str


class ActivityCreate(BaseModel):
    workspace_id: Optional[str] = None
    activity_type: str
    title: str
    duration_seconds: int = Field(0, ge=0, le=3600)
    payload: Optional[dict[str, Any]] = None


class WorkspaceLearningUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    learning_goal: Optional[str] = None
    domain: Optional[str] = Field(None, max_length=100)
    accent_color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    archived: Optional[bool] = None


class AnalyzeRequest(BaseModel):
    document_id: Optional[str] = None
    regenerate: bool = False


class ChatFeedbackRequest(BaseModel):
    message_id: Optional[str] = None
    helpful: bool
    note: Optional[str] = None
