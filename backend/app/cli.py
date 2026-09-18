"""命令行入口：在 API 启动前完成数据库升级。

用法：
    python -m app.cli migrate

全新数据库会从基线创建全部结构；已有旧数据库先经受控引导校验结构，
登记基线后再执行后续 revision。迁移失败时以非零状态退出，API 不应启动。
"""

from __future__ import annotations

import asyncio
import sys

from loguru import logger

from app.config import settings
from app.core.db_bootstrap import LegacyDatabaseError, ensure_database_ready


async def _migrate() -> int:
    try:
        report = await ensure_database_ready(
            settings.DATABASE_URL, backup_dir=settings.BACKUPS_DIR
        )
    except LegacyDatabaseError as exc:
        logger.error("Database bootstrap refused to continue: {}", exc)
        return 2
    except Exception as exc:  # pragma: no cover - 由部署环境触发
        logger.error("Database migration failed: {}", exc)
        return 1
    logger.info("Database ready: action='{}' revision='{}'.", report.action, report.revision)
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] != "migrate":
        print(__doc__)
        return 2
    return asyncio.run(_migrate())


if __name__ == "__main__":
    raise SystemExit(main())
