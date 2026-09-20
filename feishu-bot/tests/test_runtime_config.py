"""飞书凭证来源：本机 .env 优先，其次取后端设置页里保存的那一份。"""

import threading
import unittest

import httpx

from bot.config import BotConfig
from bot.runtime_config import (
    StatusReporter,
    fetch_credentials,
    local_credentials,
    resolve_credentials,
)
from bot.main import _watch_connection


def build_config(**overrides) -> BotConfig:
    values = {
        "FEISHU_APP_ID": "",
        "FEISHU_APP_SECRET": "",
        "BACKEND_URL": "http://backend:8000",
        "BACKEND_ACCESS_TOKEN": "service-token",
    }
    values.update(overrides)
    return BotConfig(**values)


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class RuntimeConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_env_credentials_win_without_calling_the_backend(self):
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("本机已配置时不应访问后端")

        config = build_config(FEISHU_APP_ID="cli_env", FEISHU_APP_SECRET="env-secret")
        async with client_for(handler) as client:
            credentials, reason = await resolve_credentials(config, client=client)

        self.assertEqual(reason, "")
        self.assertEqual(credentials.app_id, "cli_env")
        self.assertEqual(credentials.source, "env")

    async def test_backend_credentials_are_used_when_env_is_empty(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/settings/feishu/runtime")
            self.assertEqual(
                request.headers.get("X-KnowBase-Service-Token"), "service-token"
            )
            return httpx.Response(200, json={
                "app_id": "cli_settings", "app_secret": "settings-secret", "configured": True,
            })

        async with client_for(handler) as client:
            credentials, reason = await resolve_credentials(build_config(), client=client)

        self.assertEqual(reason, "")
        self.assertEqual(credentials.app_id, "cli_settings")
        self.assertEqual(credentials.app_secret, "settings-secret")
        self.assertEqual(credentials.source, "backend")

    async def test_unconfigured_backend_reports_actionable_reason(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"app_id": "", "app_secret": "", "configured": False})

        async with client_for(handler) as client:
            credentials, reason = await resolve_credentials(build_config(), client=client)

        self.assertIsNone(credentials)
        self.assertIn("还没有填写", reason)

    async def test_unreachable_backend_and_rejected_token_are_explained(self):
        def offline(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        async with client_for(offline) as client:
            credentials, reason = await fetch_credentials(build_config(), client=client)
        self.assertIsNone(credentials)
        self.assertIn("连不上后端", reason)

        def unauthorized(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "请先登录私人知识库"})

        async with client_for(unauthorized) as client:
            credentials, reason = await fetch_credentials(build_config(), client=client)
        self.assertIsNone(credentials)
        self.assertIn("SERVICE_TOKEN", reason)

        def unbound(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "服务身份尚未绑定账号"})

        async with client_for(unbound) as client:
            credentials, reason = await fetch_credentials(build_config(), client=client)
        self.assertIsNone(credentials)
        self.assertIn("首次建号", reason)

    async def test_credentials_compare_by_value_so_changes_are_detected(self):
        base = build_config(FEISHU_APP_ID="cli_a", FEISHU_APP_SECRET="secret-a")
        changed = build_config(FEISHU_APP_ID="cli_a", FEISHU_APP_SECRET="secret-b")

        self.assertEqual(local_credentials(base), local_credentials(base))
        self.assertNotEqual(local_credentials(base), local_credentials(changed))

    async def test_status_reporter_posts_state_and_swallows_failures(self):
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/settings/feishu/status")
            captured.append(request.read().decode("utf-8"))
            return httpx.Response(200, json={"state": "connected"})

        async with client_for(handler) as client:
            reporter = StatusReporter(build_config(), client=client)
            await reporter.report("connected", app_id="cli_x", detail="WebSocket 已连接")

        self.assertEqual(len(captured), 1)
        self.assertIn("connected", captured[0])

        def broken(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        async with client_for(broken) as client:
            reporter = StatusReporter(build_config(), client=client)
            await reporter.report("connected")  # 不应抛出


class ConnectionWatchTests(unittest.TestCase):
    """心跳要压过后端 90 秒的过期判定；凭证变了要如实上报“需要重启”。"""

    def test_heartbeat_keeps_status_fresh_and_flags_credential_changes(self):
        active = local_credentials(
            build_config(FEISHU_APP_ID="cli_a", FEISHU_APP_SECRET="secret-a")
        )
        changed = local_credentials(
            build_config(FEISHU_APP_ID="cli_a", FEISHU_APP_SECRET="secret-b")
        )
        config = build_config()
        config.STATUS_REPORT_SECONDS = 1
        config.CONFIG_REFRESH_SECONDS = 2

        events: list[tuple[str, str | None]] = []
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_watch_connection,
            kwargs={
                "config": config,
                "active": active,
                "report": lambda state, **kwargs: events.append((state, kwargs.get("app_id"))),
                "resolve": lambda: (changed, ""),
                "stop_event": stop_event,
            },
            daemon=True,
        )
        worker.start()
        worker.join(timeout=5)

        self.assertFalse(worker.is_alive(), "识别到凭证变化后监视线程应结束")
        self.assertEqual(events[:2], [("connected", "cli_a"), ("connected", "cli_a")])
        self.assertEqual(events[-1], ("restart_required", "cli_a"))

    def test_unchanged_credentials_keep_reporting_heartbeats(self):
        active = local_credentials(
            build_config(FEISHU_APP_ID="cli_a", FEISHU_APP_SECRET="secret-a")
        )
        config = build_config()
        config.STATUS_REPORT_SECONDS = 1
        config.CONFIG_REFRESH_SECONDS = 1

        events: list[str] = []
        stop_event = threading.Event()
        worker = threading.Thread(
            target=_watch_connection,
            kwargs={
                "config": config,
                "active": active,
                "report": lambda state, **kwargs: events.append(state),
                "resolve": lambda: (active, ""),
                "stop_event": stop_event,
            },
            daemon=True,
        )
        worker.start()
        threading.Event().wait(2.5)
        stop_event.set()
        worker.join(timeout=5)

        self.assertGreaterEqual(events.count("connected"), 2)
        self.assertNotIn("restart_required", events)


if __name__ == "__main__":
    unittest.main()
