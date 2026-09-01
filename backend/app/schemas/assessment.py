"""Request contracts shared by phase-five assessment routes."""

from typing import Any, Literal

from pydantic import BaseModel, Field


QuestionType = Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "concept_explanation"]
DifficultyLevel = Literal["easy", "medium", "hard"]
AnswerMode = Literal["sequential", "full_paper"]
QuizSetStatus = Literal["generating", "ready", "failed"]
QuizRunStatus = Literal["not_started", "in_progress", "submitted"]
AttemptEvaluationStatus = Literal["graded", "pending_ai", "grading_failed"]
MistakeMasteryStatus = Literal["unresolved", "improving", "mastered"]
LearningTaskType = Literal["reread", "simple_explanation", "new_example", "targeted_practice", "review"]
LearningTaskStatus = Literal["pending", "completed", "dismissed"]


class QuizSetGenerateRequest(BaseModel):
    workspace_id: str
    title: str | None = Field(None, max_length=255)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    knowledge_point_ids: list[str] = Field(default_factory=list, max_length=100)
    section_filters: list[str] = Field(default_factory=list, max_length=100)
    count: int = Field(5, ge=1, le=100)
    difficulty: DifficultyLevel = "medium"
    question_types: list[QuestionType] = Field(default_factory=lambda: ["single_choice"], min_length=1, max_length=6)
    strict_sources: bool = False
    answer_mode: AnswerMode = "sequential"
    duration_limit_seconds: int | None = Field(None, ge=1, le=14400)


class QuizRunCreateRequest(BaseModel):
    answer_mode: AnswerMode | None = None
    resume_unsubmitted: bool = False


class QuestionSubmitRequest(BaseModel):
    answer: Any
    duration_seconds: int = Field(0, ge=0, le=14400)


class PaperSubmitRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: int = Field(0, ge=0, le=14400)


class MistakeRedoRequest(BaseModel):
    answer: Any
    duration_seconds: int = Field(0, ge=0, le=14400)
