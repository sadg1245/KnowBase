"""应用主目录：用户数据（数据库、上传原文、媒体、向量库、密钥、备份、偏好）的唯一根目录。

解析顺序：
1. 环境变量 `KNOWBASE_HOME`（自托管部署或需要固定位置时使用）；
2. 平台默认目录：
   - Windows  `%APPDATA%\\KnowBase`
   - macOS    `~/Library/Application Support/KnowBase`
   - Linux    `$XDG_DATA_HOME/knowbase` 或 `~/.local/share/knowbase`

容器部署仍然通过显式配置（`DATABASE_URL` / `UPLOAD_DIR` / `MEDIA_DIR` / `CHROMA_DIR`）覆盖，
因此现有的 Docker 卷布局不受影响。
"""

from __future__ import annotations

import os
import sys


APP_DIR_NAME = "KnowBase"


def default_app_home() -> str:
    """返回应用主目录的绝对路径（不做创建，纯解析）。"""
    configured = os.environ.get("KNOWBASE_HOME")
    if configured and configured.strip():
        return os.path.abspath(os.path.expanduser(configured.strip()))

    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.abspath(os.path.join(base, APP_DIR_NAME))
    if sys.platform == "darwin":
        return os.path.abspath(
            os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_DIR_NAME)
        )
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.abspath(os.path.join(base, APP_DIR_NAME.lower()))


def sub_path(root: str, *parts: str) -> str:
    return os.path.abspath(os.path.join(root, *parts))


def sqlite_url_for(path: str) -> str:
    """把磁盘路径转成 SQLAlchemy 的 SQLite 异步 URL（Windows 与 POSIX 都能解析）。"""
    normalized = os.path.abspath(path).replace("\\", "/")
    return f"sqlite+aiosqlite:///{normalized}"


def sqlite_path_from_url(database_url: str) -> str | None:
    """从 DATABASE_URL 提取 SQLite 文件路径；非 SQLite 返回 None。"""
    if not database_url or not database_url.startswith("sqlite"):
        return None
    _, _, remainder = database_url.partition(":///")
    if not remainder:
        return None
    return os.path.abspath(remainder.replace("\\", "/"))


def app_home_subdirectory(root: str, name: str) -> str:
    return sub_path(root, name)


def ensure_directory(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


SECRETS_DIRNAME = "secrets"
BACKUPS_DIRNAME = "backups"
SETTINGS_FILENAME = "settings.json"


def secrets_dir(root: str) -> str:
    return sub_path(root, SECRETS_DIRNAME)


def backups_dir(root: str) -> str:
    return sub_path(root, BACKUPS_DIRNAME)


def settings_file(root: str) -> str:
    return sub_path(root, SETTINGS_FILENAME)
