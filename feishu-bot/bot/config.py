"""
使用 pydantic-settings 的机器人配置模块。
"""

from pydantic_settings import BaseSettings


class BotConfig(BaseSettings):
    """KnowBase 飞书机器人配置。"""

    # 飞书应用凭证：留空不再是错误——机器人会到后端的「设置 → 飞书机器人」取配置，
    # 拿到之前停在“待配置”状态并定期重试，不退出、不刷栈。
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""

    # 后端 API 地址
    BACKEND_URL: str = "http://localhost:8000"
    # 应用主目录（与后端同一个）：用于读取后端自动生成的服务令牌。留空则按平台默认目录推导
    DATA_ROOT: str = ""
    # 也可以直接指定服务令牌文件；一般不需要
    SERVICE_TOKEN_FILE: str = ""

    # Redis 地址，用于状态管理
    REDIS_URL: str = "redis://localhost:6379/1"

    # 机器人显示名称
    BOT_NAME: str = "KnowBase"

    # 日志级别
    LOG_LEVEL: str = "INFO"
    # 显式指定的服务令牌（可选）。留空时机器人读后端自动生成的那一份，用户不需要填写。
    BACKEND_ACCESS_TOKEN: str = ""
    REMINDERS_ENABLED: bool = True
    REMINDER_TIMEZONE: str = "Asia/Shanghai"
    # 向后端刷新飞书配置的间隔（秒）：设置页改完最多等这么久机器人就会用上
    CONFIG_REFRESH_SECONDS: int = 60
    # 向后端上报运行状态的间隔（秒）
    STATUS_REPORT_SECONDS: int = 30

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }
