"""使用 pydantic-settings 进行应用配置管理。"""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """KnowBase 应用设置，从环境变量和 .env 文件中加载。"""

    # 数据库
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/sqlite/knowbase.db"

    # Redis 缓存
    REDIS_URL: str = "redis://localhost:6379/0"

    # ChromaDB 向量存储
    CHROMA_HOST: str = "localhost"
    CHROMA_PORT: int = 8000

    # 文件上传
    UPLOAD_DIR: str = "./data/uploads"
    UPLOAD_MAX_SIZE_MB: int = 50

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
    AUTH_ENABLED: bool = False
    SESSION_DAYS: int = 30
    SERVICE_TOKEN: Optional[str] = None

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


settings = Settings()
