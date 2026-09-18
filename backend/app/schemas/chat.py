"""Request schemas for learning sessions and message actions."""

from typing import Literal

from pydantic import BaseModel, Field


LearningMode = Literal["direct", "simple", "deep", "socratic", "feynman", "quiz"]


class ChatSessionCreate(BaseModel):
    workspace_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    mode: LearningMode = "simple"
    # Retained for backward compatibility only: the server ignores this field, because the answer
    # policy is always source-first with an explicit model fallback.
    strict_sources: bool = False
    title: str = Field("新学习会话", max_length=255)


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(None, max_length=255)
    workspace_id: str | None = None
    document_ids: list[str] | None = Field(None, max_length=50)
    mode: LearningMode | None = None
    strict_sources: bool | None = None
    is_favorite: bool | None = None


class MessageNoteCreate(BaseModel):
    title: str | None = Field(None, max_length=255)
    content: str | None = None


class SummaryNoteCreate(BaseModel):
    title: str | None = Field(None, max_length=255)
    content: str | None = None


class FeedbackUpdate(BaseModel):
    helpful: bool
    category: Literal["accurate", "unclear", "unsupported", "citation", "other"] | None = None
    note: str | None = None
