"""飞书凭证的运行时来源：优先本机 .env，其次后端设置页里保存的那一份。

设置页保存的凭证落在后端的 `settings.json`，机器人用服务令牌走内网取用，
因此用户不需要再改任何文件；没有配置时机器人停在“待配置”状态而不是崩溃。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from bot.config import BotConfig


RUNTIME_PATH = "/api/settings/feishu/runtime"
STATUS_PATH = "/api/settings/feishu/status"
SERVICE_TOKEN_FILENAME = "service_token"


@dataclass(frozen=True)
class FeishuCredentials:
    app_id: str
    app_secret: str
    source: str  # env / backend

    @property
    def label(self) -> str:
        prefix = f"{self.app_id[:6]}***" if self.app_id else "***"
        origin = "本机 .env" if self.source == "env" else "设置页"
        return f"{prefix}（来自{origin}）"


def local_credentials(config: BotConfig) -> Optional[FeishuCredentials]:
    """本机 .env 里两个值都填了就直接用，行为与改造前一致。"""
    app_id = (config.FEISHU_APP_ID or "").strip()
    app_secret = (config.FEISHU_APP_SECRET or "").strip()
    if app_id and app_secret:
        return FeishuCredentials(app_id=app_id, app_secret=app_secret, source="env")
    return None


def service_headers(config: BotConfig) -> dict[str, str]:
    token, _source = resolve_access_token(config)
    return {"X-KnowBase-Service-Token": token} if token else {}


def default_app_home() -> Path:
    """与后端 `app/core/app_paths.default_app_home()` 保持一致的平台默认目录。"""
    configured = os.environ.get("KNOWBASE_HOME")
    if configured and configured.strip():
        return Path(configured.strip()).expanduser().resolve()
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "KnowBase"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "KnowBase"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "knowbase"


def service_token_file(config: BotConfig) -> Path:
    """服务令牌文件位置：显式指定优先，否则用应用主目录推导。"""
    if (config.SERVICE_TOKEN_FILE or "").strip():
        return Path(config.SERVICE_TOKEN_FILE.strip()).expanduser()
    root = Path(config.DATA_ROOT.strip()).expanduser() if (config.DATA_ROOT or "").strip() else default_app_home()
    return root / "secrets" / SERVICE_TOKEN_FILENAME


def resolve_access_token(config: BotConfig) -> tuple[str, str]:
    """返回 (服务令牌, 来源)。来源是 configured / file / missing。

    令牌由后端首次启动自动生成到 `<应用主目录>/secrets/service_token`，两个进程读同一份；
    机器人这边读不到时（后端还没起来、卷没挂上）会保持等待并重试，用户不需要填任何令牌。
    """
    configured = (config.BACKEND_ACCESS_TOKEN or "").strip()
    if configured:
        return configured, "configured"
    path = service_token_file(config)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "", f"missing:{path}"
    return (value, "file") if value else ("", f"missing:{path}")


async def fetch_credentials(
    config: BotConfig, *, client: Optional[httpx.AsyncClient] = None
) -> tuple[Optional[FeishuCredentials], str]:
    """向后端要凭证；返回 (凭证, 失败原因)。"""
    url = f"{config.BACKEND_URL.rstrip('/')}{RUNTIME_PATH}"
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0)
    try:
        response = await http.get(url, headers=service_headers(config))
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            _token, source = resolve_access_token(config)
            if source.startswith("missing:"):
                return None, f"还在等后端生成服务令牌（{source.split(':', 1)[1]}），稍后自动重试"
            return None, "后端拒绝了机器人身份，请确认服务令牌与后端一致（自定义 SERVICE_TOKEN 时两边都要设成同一个值）"
        if exc.response.status_code == 503:
            return None, "后端还没有绑定账号，请先在网页完成首次建号并填好飞书配置"
        return None, f"后端返回 HTTP {exc.response.status_code}"
    except Exception as exc:  # 网络不通、后端还没起来等
        return None, f"暂时连不上后端（{exc.__class__.__name__}）"
    finally:
        if owns_client:
            await http.aclose()

    app_id = str(body.get("app_id") or "").strip()
    app_secret = str(body.get("app_secret") or "").strip()
    if not (app_id and app_secret):
        return None, "设置页里还没有填写飞书 App ID / App Secret"
    return FeishuCredentials(app_id=app_id, app_secret=app_secret, source="backend"), ""


async def resolve_credentials(
    config: BotConfig, *, client: Optional[httpx.AsyncClient] = None
) -> tuple[Optional[FeishuCredentials], str]:
    local = local_credentials(config)
    if local is not None:
        return local, ""
    return await fetch_credentials(config, client=client)


class StatusReporter:
    """把机器人状态上报给后端，供设置页显示；失败只记 debug，不影响机器人。"""

    def __init__(self, config: BotConfig, *, client: Optional[httpx.AsyncClient] = None) -> None:
        self._config = config
        self._client = client

    async def report(
        self,
        state: str,
        *,
        detail: Optional[str] = None,
        app_id: Optional[str] = None,
    ) -> None:
        url = f"{self._config.BACKEND_URL.rstrip('/')}{STATUS_PATH}"
        payload = {"state": state, "detail": detail, "app_id": app_id}
        owns_client = self._client is None
        http = self._client or httpx.AsyncClient(timeout=5.0)
        try:
            await http.post(url, json=payload, headers=service_headers(self._config))
        except Exception as exc:
            logger.debug(f"状态上报失败（不影响机器人运行）：{exc}")
        finally:
            if owns_client:
                await http.aclose()
