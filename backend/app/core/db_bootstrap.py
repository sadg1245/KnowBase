"""数据库启动引导：Alembic 接管结构迁移，旧库经受控引导接入。

应用启动不再通过 `Base.metadata.create_all()` 或 `run_compat_migrations()`
修改正式数据库结构；结构由 `alembic upgrade head` 管理。
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from loguru import logger
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.app_paths import ensure_directory, sqlite_path_from_url


# 基线（阶段一之前）必须存在的核心表。
CORE_TABLES: tuple[str, ...] = (
    "workspaces",
    "documents",
    "document_chunks",
    "knowledge_points",
    "flashcards",
    "review_logs",
    "quiz_questions",
    "study_activities",
    "study_sessions",
    "learning_goals",
    "chat_sessions",
    "conversations",
)

# 旧库必须已经具备的关键列，缺失说明不是可接受的旧版本。
CORE_COLUMNS: dict[str, tuple[str, ...]] = {
    "workspaces": ("id", "name", "slug", "created_at"),
    "documents": ("id", "workspace_id", "filename", "file_path", "status"),
    "document_chunks": ("id", "workspace_id", "document_id", "content"),
    "knowledge_points": ("id", "workspace_id", "title", "mastery"),
    "flashcards": ("id", "workspace_id", "front", "back", "due_at"),
    "study_activities": ("id", "activity_type", "title", "occurred_at"),
    "conversations": ("id", "role", "content"),
}

BASELINE_REVISION = "0001_legacy_baseline"


class LegacyDatabaseError(RuntimeError):
    """旧库结构不符合可接受的旧版本，拒绝盲目 stamp。"""


@dataclass
class BootstrapReport:
    action: str
    revision: str | None = None
    backup_path: str | None = None
    missing_tables: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)


DEFAULT_BACKUP_KEEP = 5


def _prune_backups(backup_dir: str, keep: int) -> None:
    """只保留最近若干份备份，避免长期使用后无限增长。"""
    try:
        candidates = [
            os.path.join(backup_dir, name)
            for name in os.listdir(backup_dir)
            if name.endswith(".db")
        ]
    except OSError:
        return
    candidates.sort(key=lambda item: os.path.getmtime(item), reverse=True)
    for stale in candidates[max(1, keep):]:
        try:
            os.remove(stale)
        except OSError:  # pragma: no cover - 尽力清理
            logger.debug("Could not remove stale backup '{}'", stale)


def backup_database(
    database_url: str,
    backup_dir: str,
    *,
    keep: int = DEFAULT_BACKUP_KEEP,
) -> str | None:
    """升级前把 SQLite 数据库整体备份到应用主目录，使用 SQLite 原生备份 API（对 WAL 安全）。"""
    source_path = sqlite_path_from_url(database_url)
    if source_path is None or not os.path.isfile(source_path):
        return None
    ensure_directory(backup_dir)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = os.path.splitext(os.path.basename(source_path))[0]
    target = os.path.join(backup_dir, f"{stem}-{stamp}.db")
    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    try:
        with destination:
            source.backup(destination)
    except sqlite3.Error as exc:
        logger.warning("升级前备份失败（{}），继续执行迁移；建议手动复制数据库文件。", exc)
        return None
    finally:
        source.close()
        destination.close()
    _prune_backups(backup_dir, keep)
    logger.info("已备份升级前的数据库：{}", target)
    return target


async def _tables(connection: AsyncConnection) -> set[str]:
    return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))


async def _columns(connection: AsyncConnection, table: str) -> set[str]:
    return set(await connection.run_sync(
        lambda sync: [column["name"] for column in inspect(sync).get_columns(table)]
    ))


async def inspect_legacy_database(connection: AsyncConnection) -> BootstrapReport:
    """检查核心表、关键列与索引，返回是否可安全接入基线。"""
    tables = await _tables(connection)
    if "alembic_version" in tables:
        return BootstrapReport(action="managed", revision=await current_revision(connection))
    if not tables or not (tables & set(CORE_TABLES)):
        return BootstrapReport(action="empty")

    missing_tables = [name for name in CORE_TABLES if name not in tables]
    missing_columns: list[str] = []
    for table, columns in CORE_COLUMNS.items():
        if table not in tables:
            continue
        existing = await _columns(connection, table)
        missing_columns.extend(
            f"{table}.{name}" for name in columns if name not in existing
        )
    if missing_tables or missing_columns:
        raise LegacyDatabaseError(
            "现有数据库缺少核心结构，无法安全登记基线。"
            f"缺少表：{missing_tables or '无'}；缺少列：{missing_columns or '无'}。"
            "请先备份数据库，并用与旧版本匹配的迁移脚本补齐结构。"
        )
    return BootstrapReport(action="legacy")


async def current_revision(connection: AsyncConnection) -> str | None:
    try:
        return await connection.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception:
        return None


def _alembic_config(database_url: str):
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = Config(os.path.join(here, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(here, "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def ensure_database_ready(
    database_url: str,
    *,
    backup_dir: str | None = None,
    backup_keep: int = DEFAULT_BACKUP_KEEP,
) -> BootstrapReport:
    """确保数据库结构达到 head；全新库与旧库都走同一条可测试路径。

    传入 `backup_dir` 时，会在真正执行升级之前自动备份数据库——用户不会自己备份，
    而结构迁移是就地进行的。
    """
    from alembic import command
    from sqlalchemy import create_engine

    config = _alembic_config(database_url)
    sync_url = database_url.replace("sqlite+aiosqlite", "sqlite").replace(
        "postgresql+asyncpg", "postgresql+psycopg"
    )
    engine = create_engine(sync_url)
    try:
        with engine.connect() as connection:
            report = await _inspect(connection)
        if report.action == "managed" and report.revision and _is_head(config, report.revision):
            logger.info("Database schema already at head ({}).", report.revision)
            return report
        if backup_dir and report.action in {"legacy", "managed"}:
            report.backup_path = backup_database(
                database_url, backup_dir, keep=backup_keep
            )
        if report.action == "legacy":
            logger.warning("Detected a pre-Alembic database; stamping the baseline revision.")
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.stamp(config, BASELINE_REVISION)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            report.revision = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
    finally:
        config.attributes.pop("connection", None)
        engine.dispose()
    logger.info("Database schema upgraded to '{}'.", report.revision)
    return report


async def _inspect(connection) -> BootstrapReport:
    """在同步连接上复用异步的检查逻辑。"""
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" in tables:
        revision = connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar()
        return BootstrapReport(action="managed", revision=revision)
    if not tables or not (tables & set(CORE_TABLES)):
        return BootstrapReport(action="empty")
    missing_tables = [name for name in CORE_TABLES if name not in tables]
    missing_columns: list[str] = []
    for table, columns in CORE_COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspect(connection).get_columns(table)}
        missing_columns.extend(f"{table}.{name}" for name in columns if name not in existing)
    if missing_tables or missing_columns:
        raise LegacyDatabaseError(
            "现有数据库缺少核心结构，无法安全登记基线。"
            f"缺少表：{missing_tables or '无'}；缺少列：{missing_columns or '无'}。"
            "请先备份数据库，并用与旧版本匹配的迁移脚本补齐结构。"
        )
    return BootstrapReport(action="legacy")


def _is_head(config, revision: str) -> bool:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(config)
    return revision in set(script.get_heads())
