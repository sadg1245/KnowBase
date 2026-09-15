"""Validated contracts for learning activity, goals, dashboards, and reports."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


PeriodType = Literal["day", "week", "month"]
GoalScope = Literal["global", "workspace"]
GoalMetric = Literal[
    "daily_minutes",
    "daily_reviews",
    "weekly_days",
    "overall_mastery",
    "workspace_mastery",
]
StudyContextType = Literal["document", "conversation"]


class GoalUpdate(BaseModel):
    scope_type: GoalScope
    workspace_id: str | None = None
    metric: GoalMetric
    target_value: float = Field(gt=0, le=480)
    target_date: date | None = None

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "global" and self.workspace_id is not None:
            raise ValueError("Global goals cannot belong to a workspace")
        if self.scope_type == "workspace" and self.workspace_id is None:
            raise ValueError("Workspace goals require a workspace")
        if self.scope_type == "workspace" and self.metric != "workspace_mastery":
            raise ValueError("Workspace goals must measure workspace mastery")
        if self.scope_type == "global" and self.metric == "workspace_mastery":
            raise ValueError("Workspace mastery cannot be a global goal")
        return self


class GlobalGoalsUpdate(BaseModel):
    daily_minutes: int = Field(ge=5, le=480)
    daily_reviews: int = Field(ge=1, le=200)
    weekly_days: int = Field(ge=1, le=7)
    target_completion_date: date
    timezone_name: str = Field(min_length=1, max_length=100)


class WorkspaceGoalUpdate(BaseModel):
    target_mastery: float = Field(ge=1, le=100)
    target_date: date


class StudySessionStart(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    context_type: StudyContextType
    context_id: str = Field(min_length=1, max_length=36)
    workspace_id: str | None = Field(default=None, max_length=36)


class StudySessionHeartbeat(BaseModel):
    sequence: int = Field(ge=1)
    client_active_at: datetime | None = None


class StudySessionFinish(BaseModel):
    sequence: int = Field(ge=0)
