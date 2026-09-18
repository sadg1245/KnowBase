"""Alembic 运行环境（异步驱动自动转换为同步驱动）。

支持两种调用方式：
1. 命令行 `alembic upgrade head`，使用应用配置中的 `DATABASE_URL`。
2. 应用启动引导通过 `config.attributes["connection"]` 传入已有连接，
   使检查、登记基线与升级处于同一可控流程。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def sync_url(url: str) -> str:
    """把异步驱动 URL 转换为 Alembic 可用的同步驱动 URL。"""
    return (
        url.replace("sqlite+aiosqlite", "sqlite")
        .replace("postgresql+asyncpg", "postgresql+psycopg")
        .replace("postgresql+psycopg_async", "postgresql+psycopg")
    )


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided = config.attributes.get("connection")
    if provided is not None:
        _configure(provided)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(sync_url(settings.DATABASE_URL), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _configure(connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
