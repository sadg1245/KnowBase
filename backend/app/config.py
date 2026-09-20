"""使用 pydantic-settings 进行应用配置管理。

普通用户只需要配置自己的模型 API Key；数据库、上传、媒体、向量库、密钥、备份等位置
都由"应用主目录"（见 `app.core.app_paths`）推导，不需要用户填写。
"""

import os
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings

from app.core.app_paths import (
    backups_dir,
    default_app_home,
    secrets_dir,
    settings_file,
    sqlite_url_for,
    sub_path,
)


class Settings(BaseSettings):
    """KnowBase 应用设置，从环境变量和 .env 文件中加载。"""

    # 应用主目录：下面所有未显式配置的路径都由它推导
    DATA_ROOT: str = ""

    # 数据库（留空 = <DATA_ROOT>/sqlite/knowbase.db）
    DATABASE_URL: Optional[str] = None

    # Redis 缓存
    REDIS_URL: str = "redis://localhost:6379/0"

    # ChromaDB 向量存储：默认嵌入到应用进程，使用 <DATA_ROOT>/chroma；
    # 自托管部署可显式设置 CHROMA_HOST/CHROMA_PORT 走远程服务。
    CHROMA_HOST: str = "local"
    CHROMA_PORT: int = 8000
    CHROMA_DIR: Optional[str] = None

    # 文件上传
    UPLOAD_DIR: Optional[str] = None
    UPLOAD_MAX_SIZE_MB: int = 50

    # 头像与知识库封面（受控本地上传目录）
    MEDIA_DIR: Optional[str] = None
    MEDIA_URL_PREFIX: str = "/api/media"
    IMAGE_MAX_SIZE_MB: int = 4
    IMAGE_MAX_PIXELS: int = 20_000_000
    IMAGE_MIN_WIDTH: int = 16
    IMAGE_MIN_HEIGHT: int = 16
    EXTERNAL_IMAGE_URL_MAX_LENGTH: int = 1024

    # 标签规范化边界
    TAG_MAX_LENGTH: int = 32
    TAG_MAX_COUNT: int = 30

    # 分块配置
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # RAG 配置
    RAG_TOP_K: int = 5
    RAG_VECTOR_TOP_K: int = 20
    RAG_KEYWORD_TOP_K: int = 20
    RAG_SELECTED_TOP_K: int = 8
    RAG_SUPPORTED_THRESHOLD: float = 0.58
    RAG_SECOND_THRESHOLD: float = 0.45
    RAG_LIMITED_THRESHOLD: float = 0.42
    # 切分与语义分块
    SEMANTIC_SPLIT_THRESHOLD: float = 0.62
    SEMANTIC_SPLIT_MAX_SENTENCES: int = 400
    RAG_PARENT_MAX_TOKENS: int = 2000
    # 富化与索引版本
    RAG_ENRICH_ENABLED: bool = False
    RAG_ENRICH_CONCURRENCY: int = 3
    RAG_ENRICH_BATCH_SIZE: int = 10
    RAG_ENRICH_MAX_TOKENS: int = 4000
    RAG_INDEX_VERSION: int = 2
    RAG_MULTIVECTOR_KINDS: str = "content,summary,question"
    # 检索调试端点（默认关闭，开启后可用 /api/debug/retrieval 查看逐条打分）
    RAG_DEBUG_ENDPOINT_ENABLED: bool = False

    # 学习范围（RetrievalScope）配置
    SCOPE_DEFAULT_MODE: str = "smart"
    SCOPE_MAX_EXPANSION_ROUNDS: int = 2
    SCOPE_EXPANSION_LATENCY_BUDGET_MS: int = 3000
    SCOPE_PER_WORKSPACE_TOP_K: int = 10
    PROFILE_RANK_BONUS_MAX: float = 0.10

    # AI 导师画像与长期记忆
    MEMORY_RECALL_K: int = 8
    MEMORY_SELECTED_K: int = 5
    MEMORY_DEDUP_SIMILARITY: float = 0.92
    MEMORY_MAX_CONTENT_LENGTH: int = 2000
    PROFILE_CACHE_TTL_SECONDS: int = 30
    PROFILE_MAX_KNOWLEDGE_POINTS: int = 5
    PROFILE_MAX_MISTAKES: int = 3

    # LLM 默认配置
    DEFAULT_LLM_PROVIDER: str = "deepseek"
    DEFAULT_LLM_MODEL: str = "deepseek-chat"
    DEFAULT_EMBEDDING_PROVIDER: str = "local"
    DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-small"
    DEFAULT_EMBEDDING: str = "BAAI/bge-small-zh-v1.5"

    # 对话配置
    CONVERSATION_HISTORY_LIMIT: int = 10

    # API 密钥
    OPENAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DASHSCOPE_API_KEY: Optional[str] = None
    ZHIPU_API_KEY: Optional[str] = None
    OLLAMA_BASE_URL: Optional[str] = None

    # 飞书集成
    FEISHU_APP_ID: Optional[str] = None
    FEISHU_APP_SECRET: Optional[str] = None

    # 认证配置
    JWT_SECRET: str = "knowbase-secret-key-change-in-production"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    SESSION_DAYS: int = 30
    SERVICE_TOKEN: Optional[str] = None

    # 公开路径：只有健康检查、认证状态、首次设置和登录不需要令牌。
    PUBLIC_API_PATHS: tuple[str, ...] = (
        "/api/auth/status",
        "/api/auth/setup",
        "/api/auth/login",
    )
    PUBLIC_API_PREFIXES: tuple[str, ...] = ("/api/media/",)

    INSECURE_JWT_SECRETS: tuple[str, ...] = (
        "knowbase-secret-key-change-in-production",
        "replace-with-a-long-random-secret",
        "changeme",
        "secret",
        "",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _resolve_data_root(self) -> "Settings":
        root = (self.DATA_ROOT or "").strip() or default_app_home()
        self.DATA_ROOT = os.path.abspath(os.path.expanduser(root))
        if not (self.DATABASE_URL or "").strip():
            self.DATABASE_URL = sqlite_url_for(sub_path(self.DATA_ROOT, "sqlite", "knowbase.db"))
        if not (self.UPLOAD_DIR or "").strip():
            self.UPLOAD_DIR = sub_path(self.DATA_ROOT, "uploads")
        if not (self.MEDIA_DIR or "").strip():
            self.MEDIA_DIR = sub_path(self.DATA_ROOT, "media")
        if not (self.CHROMA_DIR or "").strip():
            self.CHROMA_DIR = sub_path(self.DATA_ROOT, "chroma")
        return self

    # ---- 主目录派生位置（不由用户配置） ----
    @property
    def SECRETS_DIR(self) -> str:
        return secrets_dir(self.DATA_ROOT)

    @property
    def BACKUPS_DIR(self) -> str:
        return backups_dir(self.DATA_ROOT)

    @property
    def SETTINGS_FILE(self) -> str:
        return settings_file(self.DATA_ROOT)

    @property
    def local_chroma_enabled(self) -> bool:
        """未显式指定远程地址时，向量库以嵌入模式运行在应用进程内。"""
        host = (self.CHROMA_HOST or "").strip().lower()
        return host in {"", "local", "embedded", "persistent"}


settings = Settings()


class InsecureSecretError(RuntimeError):
    """启动时检测到不安全的 JWT 密钥。"""


def validate_security_configuration(secret: str, *, account_configured: bool) -> None:
    """账号启用后禁止默认或低熵密钥；未建号时允许先启动设置流程。"""
    if not account_configured:
        return
    normalized = (secret or "").strip()
    if normalized.lower() in {value.lower() for value in settings.INSECURE_JWT_SECRETS}:
        raise InsecureSecretError(
            "JWT_SECRET 仍为默认值，请在 .env 中设置至少 32 位的随机密钥后重新启动。"
        )
    if len(normalized) < 32:
        raise InsecureSecretError("JWT_SECRET 长度不足 32 位，请使用高熵随机密钥。")
