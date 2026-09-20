"""飞书机器人运行状态（内存态，供设置页展示）。

机器人每 30 秒用服务令牌 POST 一次自己的状态；状态本身是易失信息，因此只留在内存里，
超过 `STALE_AFTER_SECONDS` 没有上报就标记为过期，而不是继续显示上一次的“已连接”。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional


STALE_AFTER_SECONDS = 90
_KNOWN_STATES = frozenset(
    {"pending", "connecting", "connected", "error", "restart_required", "unknown"}
)

_lock = threading.Lock()
_state: dict[str, Any] = {}


def record(
    state: str,
    *,
    detail: Optional[str] = None,
    app_id: Optional[str] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    """记录一次机器人上报，返回写入后的视图。"""
    normalized = state if state in _KNOWN_STATES else "unknown"
    timestamp = time.time() if now is None else now
    with _lock:
        _state.clear()
        _state.update({
            "state": normalized,
            "detail": (detail or "").strip() or None,
            "app_id": (app_id or "").strip() or None,
            "updated_at": timestamp,
        })
        return _view(timestamp)


def current(*, now: Optional[float] = None) -> dict[str, Any]:
    """返回当前状态视图；从未上报过时是 `unknown`。"""
    timestamp = time.time() if now is None else now
    with _lock:
        return _view(timestamp)


def reset() -> None:
    """测试或重新绑定账号时清空。"""
    with _lock:
        _state.clear()


def _view(now: float) -> dict[str, Any]:
    if not _state:
        return {
            "state": "unknown",
            "detail": None,
            "app_id": None,
            "updated_at": None,
            "stale": False,
        }
    updated_at = float(_state.get("updated_at") or 0.0)
    return {
        "state": str(_state.get("state") or "unknown"),
        "detail": _state.get("detail"),
        "app_id": _state.get("app_id"),
        "updated_at": datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat(),
        "stale": (now - updated_at) > STALE_AFTER_SECONDS,
    }
