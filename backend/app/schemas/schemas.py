"""用于请求/响应校验的 Pydantic Schema 定义。"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 工作空间 Schema
# ---------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Workspace name")
    description: Optional[str] = Field("", description="Workspace description")
    learning_goal: Optional[str] = ""
    domain: Optional[str] = "未分类"
    domain_id: Optional[str] = None
    learning_status: Optional[str] = Field("not_started", pattern="^(not_started|learning|paused|completed)$")
    cover_url: Optional[str] = None
    accent_color: Optional[str] = "#1f7a8c"


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    learning_goal: Optional[str] = None
    domain: Optional[str] = None
    domain_id: Optional[str] = None
    learning_status: Optional[str] = Field(None, pattern="^(not_started|learning|paused|completed)$")
    cover_url: Optional[str] = None
    clear_cover: bool = False
    accent_color: Optional[str] = None
    archived: Optional[bool] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    slug: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    knowledge_point_count: int = 0
    learning_progress: int = 0
    last_studied_at: Optional[datetime] = None
    learning_goal: str = ""
    learning_status: str = "not_started"
    domain: str = "未分类"
    domain_id: Optional[str] = None
    cover_kind: str = "none"
    cover_url: Optional[str] = None
    accent_color: str = "#1f7a8c"
    archived: bool = False

    model_config = {"from_attributes": True}


class WorkspaceDetailResponse(WorkspaceResponse):
    document_count: int = 0


# ---------------------------------------------------------------------------
# 文档 Schema
# ---------------------------------------------------------------------------

class DocumentUpdate(BaseModel):
    filename: Optional[str] = Field(None, min_length=1, max_length=512)
    tags: Optional[list[str]] = Field(None, max_length=30)


class DocumentResponse(BaseModel):
    id: str
    workspace_id: str
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    error_message: Optional[str] = None
    summary: Optional[str] = None
    outline: Optional[str] = None
    learning_status: str = "not_started"
    tags: list[str] = Field(default_factory=list)
    chapter_summaries: list[Any] = Field(default_factory=list)
    core_concepts: list[Any] = Field(default_factory=list)
    important_terms: list[Any] = Field(default_factory=list)
    common_mistakes: list[Any] = Field(default_factory=list)
    prerequisites: list[Any] = Field(default_factory=list)
    learning_order: list[Any] = Field(default_factory=list)
    review_points: list[Any] = Field(default_factory=list)
    learning_error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    learning_generated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentStatusResponse(BaseModel):
    id: str
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    learning_status: str = "not_started"
    learning_error_message: Optional[str] = None
    processed_at: Optional[datetime] = None
    learning_generated_at: Optional[datetime] = None


class DocumentSectionItem(BaseModel):
    chunk_id: str
    chunk_index: int
    page_num: Optional[int] = None
    heading: Optional[str] = None
    heading_level: Optional[int] = None
    section_path: list[str] = Field(default_factory=list)
    content: str


class DocumentSectionsResponse(BaseModel):
    document_id: str
    outline: list[dict[str, Any]] = Field(default_factory=list)
    items: list[DocumentSectionItem] = Field(default_factory=list)


class DocumentSectionDetail(DocumentSectionItem):
    document_id: str
    previous_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 对话 Schema
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    # 归属由认证状态决定；不再接受客户端提交的 user_id。
    workspace_id: Optional[str] = Field(None, description="Associated workspace")
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)
    sources: Optional[list[dict[str, Any]]] = None


class ConversationResponse(BaseModel):
    id: str
    user_id: str
    workspace_id: Optional[str] = None
    role: str
    content: str
    sources: Optional[list[dict[str, Any]]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# 聊天 / RAG Schema
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, description="User question")
    workspace_id: Optional[str] = Field(
        None, description="Limit search to this workspace"
    )
    document_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Limit search to these documents; an empty list means all documents",
    )
    conversation_id: Optional[str] = Field(
        None, description="Existing conversation thread id"
    )
    session_id: Optional[str] = Field(
        None, description="Persistent learning session id; preferred over conversation_id"
    )
    mode: str = Field("explain", pattern="^(direct|simple|deep|socratic|feynman|quiz|explain)$")
    strict_sources: bool = True


class SourceItem(BaseModel):
    content: str = ""
    source_file: str = ""
    page_num: Optional[int] = None
    score: float = 0.0
    document_id: Optional[str] = None
    heading: Optional[str] = None
    chunk_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    conversation_id: Optional[str] = None


# ---------------------------------------------------------------------------
# 搜索 Schema
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query")
    workspace_id: Optional[str] = Field(
        None, description="Limit search to this workspace"
    )
    document_ids: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Limit search to these documents; an empty list means all documents",
    )
    top_k: int = Field(5, ge=1, le=50, description="Number of results")


class SearchResult(BaseModel):
    content: str
    source_file: str
    page_num: Optional[int] = None
    score: float
    document_id: Optional[str] = None
    heading: Optional[str] = None
    chunk_id: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 上传 Schema
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    document: DocumentResponse
    status: str = "pending"


# ---------------------------------------------------------------------------
# 设置 Schema
# ---------------------------------------------------------------------------

class LLMSettings(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key_masked: Optional[str] = None
    base_url: Optional[str] = None
    configured: bool = False


class EmbeddingSettings(BaseModel):
    provider: str = "local"
    model: str = "BAAI/bge-small-zh-v1.5"
    dimension: Optional[int] = None


class FeishuSettings(BaseModel):
    app_id: Optional[str] = None
    app_secret_masked: Optional[str] = None


class SettingsResponse(BaseModel):
    llm: LLMSettings
    embedding: EmbeddingSettings
    feishu: FeishuSettings


class LLMSettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class EmbeddingSettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


class SystemInfoResponse(BaseModel):
    version: str = "0.1.0"
    document_count: int = 0
    workspace_count: int = 0
    total_chunks: int = 0
    backend_uptime: int = 0
    storage_used_bytes: int = 0
    storage_used_human: str = "0 B"


class LLMTestRequest(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


class LLMTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: Optional[float] = None
