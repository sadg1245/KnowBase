"""RAG 检索端点契约（设计文档 §22.1）。

练习检索只返回资料中的题干（`content_type="question"`）；解答与答案在召回层就被排除，
与 `app/rag/query/router.py` 的 practice 路由保持同一语义。
"""

from pydantic import BaseModel, Field


class PracticeQuestionsRequest(BaseModel):
    workspace_id: str = Field(..., min_length=1)
    document_ids: list[str] = Field(default_factory=list, max_length=50)
    knowledge_point_ids: list[str] = Field(default_factory=list, max_length=50)
    difficulty_min: int | None = Field(None, ge=1, le=5)
    difficulty_max: int | None = Field(None, ge=1, le=5)
    limit: int = Field(10, ge=1, le=50)


class PracticeQuestionItem(BaseModel):
    chunk_id: str
    document_id: str
    source_file: str = ""
    page_num: int | None = None
    heading: str | None = None
    content: str
    content_type: str = "question"
    difficulty: int | None = None
    parent_id: str | None = None
    unit_id: str | None = None


class PracticeQuestionsResponse(BaseModel):
    items: list[PracticeQuestionItem] = Field(default_factory=list)
    total: int = 0
    excluded_content_types: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
