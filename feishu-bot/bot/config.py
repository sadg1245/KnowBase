"""
使用 pydantic-settings 的机器人配置模块。
"""

from pydantic_settings import BaseSettings


class BotConfig(BaseSettings):
    """KnowBase 飞书机器人配置。"""

    # 飞书应用凭证
    FEISHU_APP_ID: str
    FEISHU_APP_SECRET: str

    # 后端 API 地址
    BACKEND_URL: str = "http://localhost:8000"

    # Redis 地址，用于状态管理
    REDIS_URL: str = "redis://localhost:6379/1"

    # 机器人显示名称
    BOT_NAME: str = "KnowBase"

    # 日志级别
    LOG_LEVEL: str = "INFO"
    BACKEND_ACCESS_TOKEN: str = ""
    REMINDERS_ENABLED: bool = True
    REMINDER_TIMEZONE: str = "Asia/Shanghai"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }
