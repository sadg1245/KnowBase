"""程序自管的本地密钥。

令牌签名密钥（JWT_SECRET）在本地部署里不需要用户知道，也不需要跨机器一致；
唯一要求是"足够随机 + 重启后保持不变"。因此：

- 运维/自托管显式配置了强密钥 → 直接使用，不落盘；
- 未配置或配置了不安全的值 → 首次启动自动生成，写到 `<应用主目录>/secrets/`（0600），
  之后一直复用。用户永远不需要看到它，丢失它的代价也只是"重新登录一次"。
"""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.config import Settings, settings as global_settings
from app.core.app_paths import ensure_directory


JWT_SECRET_FILENAME = "jwt_secret"
MANAGED_SECRET_BYTES = 48
MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class ResolvedSecret:
    value: str
    source: str  # configured | stored | generated


def is_strong_secret(value: Optional[str], *, insecure: tuple[str, ...] = ()) -> bool:
    normalized = (value or "").strip()
    if len(normalized) < MIN_SECRET_LENGTH:
        return False
    return normalized.lower() not in {item.lower() for item in insecure}


def _write_private_file(path: str, content: str) -> None:
    ensure_directory(os.path.dirname(path))
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - 某些文件系统不支持 chmod
        logger.debug("Could not restrict permissions on '{}'", temporary)
    os.replace(temporary, path)


def read_managed_secret(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        return None
    return value or None


def managed_secret(path: str) -> ResolvedSecret:
    """读取已有的托管密钥，没有就生成一个新的并持久化。"""
    existing = read_managed_secret(path)
    if existing and is_strong_secret(existing):
        return ResolvedSecret(existing, "stored")
    value = secrets.token_urlsafe(MANAGED_SECRET_BYTES)
    _write_private_file(path, value)
    return ResolvedSecret(value, "generated")


def resolve_jwt_secret(
    settings: Settings | None = None,
) -> ResolvedSecret:
    """返回实际用于令牌签名的密钥，并在需要时自动生成并持久化。"""
    config = settings or global_settings
    configured = config.JWT_SECRET
    if is_strong_secret(configured, insecure=config.INSECURE_JWT_SECRETS):
        return ResolvedSecret((configured or "").strip(), "configured")

    if (configured or "").strip():
        logger.warning(
            "检测到不安全的 JWT_SECRET（默认值或长度不足），已改为使用本机自动生成的密钥；"
            "如需沿用旧密钥，请把它设置为不少于 {} 位的随机字符串。",
            MIN_SECRET_LENGTH,
        )
    path = os.path.join(config.SECRETS_DIR, JWT_SECRET_FILENAME)
    resolved = managed_secret(path)
    if resolved.source == "generated":
        logger.info("已生成并保存本机令牌密钥（{}），后续启动会继续使用它。", path)
    return resolved
