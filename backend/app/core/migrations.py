"""兼容脚本退役与 SQLite 关键词检索索引引导。

阶段一之后，数据库结构完全由 Alembic 管理：

- `run_compat_migrations` 不再执行任何结构 DDL，只保留为兼容入口；
  原来的结构变更与数据回填已转换为明确的 revision
  （见 `alembic/versions/0001_legacy_baseline.py` 与
  `alembic/versions/0002_account_foundation.py`）。
- 仍需要运行时处理的是 SQLite FTS5 虚拟表与触发器。它们是检索实现的一部分，
  不是表结构契约，因此保留为显式、幂等、可审计的引导步骤。
"""

from loguru import logger
from sqlalchemy import text


FTS_STATEMENTS: tuple[str, ...] = (
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
        tokenized_content, heading, source_file,
        content='document_chunks', content_rowid='rowid')
    """,
    """
    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_insert AFTER INSERT ON document_chunks BEGIN
        INSERT INTO document_chunks_fts(rowid, tokenized_content, heading, source_file)
        VALUES (new.rowid, new.tokenized_content, new.heading, new.source_file);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_delete AFTER DELETE ON document_chunks BEGIN
        INSERT INTO document_chunks_fts(document_chunks_fts, rowid, tokenized_content, heading, source_file)
        VALUES ('delete', old.rowid, old.tokenized_content, old.heading, old.source_file);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS document_chunks_fts_update AFTER UPDATE ON document_chunks BEGIN
        INSERT INTO document_chunks_fts(document_chunks_fts, rowid, tokenized_content, heading, source_file)
        VALUES ('delete', old.rowid, old.tokenized_content, old.heading, old.source_file);
        INSERT INTO document_chunks_fts(rowid, tokenized_content, heading, source_file)
        VALUES (new.rowid, new.tokenized_content, new.heading, new.source_file);
    END
    """,
)


async def ensure_search_index(conn) -> bool:
    """幂等地建立 SQLite 关键词检索索引；非 SQLite 方言直接跳过。"""
    if conn.dialect.name != "sqlite":
        return False
    try:
        for statement in FTS_STATEMENTS:
            await conn.execute(text(statement))
    except Exception as exc:
        logger.warning("SQLite FTS5 is unavailable; keyword retrieval will be disabled: {}", exc)
        return False
    return True


async def run_compat_migrations(conn) -> None:
    """已退役的兼容迁移入口。

    保留函数名是为了让旧调用点继续可用，但它不再修改数据库结构；
    唯一保留的运行时准备是检索索引。
    """
    logger.debug("run_compat_migrations is retired; ensuring the keyword search index instead.")
    await ensure_search_index(conn)
