"""飞书机器人配置：设置页可配、落盘、并且机器人能取用。"""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.config import settings as app_settings
from app.core.app_settings_store import apply_persisted, load_raw
from app.main import app
from app.models.base import Base
from app.services import feishu_status
from tests.support import create_user


FEISHU_FIELDS = ("FEISHU_APP_ID", "FEISHU_APP_SECRET")


class FeishuSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {field: getattr(app_settings, field, None) for field in FEISHU_FIELDS}
        self.original_data_root = app_settings.DATA_ROOT
        for field in FEISHU_FIELDS:
            setattr(app_settings, field, None)
        # SETTINGS_FILE 是按 DATA_ROOT 推导的只读属性：把主目录指到临时目录即可隔离落盘
        app_settings.DATA_ROOT = self.temp.name
        self.settings_file = str(Path(self.temp.name) / "settings.json")
        feishu_status.reset()

        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        await self.db.commit()

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()
        feishu_status.reset()
        for field, value in self.original.items():
            setattr(app_settings, field, value)
        app_settings.DATA_ROOT = self.original_data_root
        self.temp.cleanup()

    async def test_unconfigured_state_is_reported(self):
        response = await self.client.get("/api/settings/feishu")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertFalse(body["configured"])
        self.assertEqual(body["source"], "none")
        self.assertIsNone(body["app_secret_masked"])
        self.assertEqual(body["bot"]["state"], "unknown")
        self.assertFalse(body["bot"]["stale"])

    async def test_update_persists_to_settings_json_and_masks_the_secret(self):
        response = await self.client.put("/api/settings/feishu", json={
            "app_id": "cli_baseline",
            "app_secret": "super-secret-value",
        })

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["configured"])
        self.assertEqual(body["source"], "settings")
        self.assertEqual(body["app_id"], "cli_baseline")
        self.assertNotEqual(body["app_secret_masked"], "super-secret-value")
        self.assertNotIn("super-secret-value", response.text)

        stored = load_raw(self.settings_file)["feishu"]
        self.assertEqual(stored["FEISHU_APP_ID"], "cli_baseline")
        self.assertEqual(stored["FEISHU_APP_SECRET"], "super-secret-value")

    async def test_omitted_fields_keep_their_stored_value(self):
        await self.client.put("/api/settings/feishu", json={
            "app_id": "cli_keep", "app_secret": "keep-me",
        })

        # 只改 app_id 时，脱敏后的 app_secret 不会被当成新密钥写回去。
        await self.client.put("/api/settings/feishu", json={"app_id": "cli_renamed"})

        stored = load_raw(self.settings_file)["feishu"]
        self.assertEqual(stored["FEISHU_APP_ID"], "cli_renamed")
        self.assertEqual(stored["FEISHU_APP_SECRET"], "keep-me")

    async def test_explicit_clear_wins_over_env_fallback(self):
        app_settings.FEISHU_APP_ID = "cli_from_env"
        app_settings.FEISHU_APP_SECRET = "env-secret"

        response = await self.client.put("/api/settings/feishu", json={"app_secret": ""})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["configured"])
        # 重启后读回设置文件：显式清除的字段不应被 .env 覆盖回来
        app_settings.FEISHU_APP_SECRET = "env-secret"
        apply_persisted(app_settings, load_raw(self.settings_file))
        self.assertEqual(app_settings.FEISHU_APP_SECRET, "")

    async def test_runtime_endpoint_returns_plaintext_for_the_bot(self):
        await self.client.put("/api/settings/feishu", json={
            "app_id": "cli_runtime", "app_secret": "runtime-secret",
        })

        response = await self.client.get("/api/settings/feishu/runtime")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["app_id"], "cli_runtime")
        self.assertEqual(body["app_secret"], "runtime-secret")
        self.assertTrue(body["configured"])

    async def test_bot_status_is_reported_and_expires(self):
        report = await self.client.post("/api/settings/feishu/status", json={
            "state": "connected", "app_id": "cli_runtime", "detail": "WebSocket 已连接",
        })
        self.assertEqual(report.status_code, 200, report.text)

        body = (await self.client.get("/api/settings/feishu")).json()
        self.assertEqual(body["bot"]["state"], "connected")
        self.assertEqual(body["bot"]["detail"], "WebSocket 已连接")
        self.assertFalse(body["bot"]["stale"])

        # 超过 90 秒没有上报：状态保留但标记过期，避免误导“还在连着”
        feishu_status.record("connected", now=time.time() - 200)
        self.assertTrue(feishu_status.current()["stale"])

    async def test_unknown_status_value_falls_back_to_unknown(self):
        await self.client.post("/api/settings/feishu/status", json={"state": "banana"})

        self.assertEqual(feishu_status.current()["state"], "unknown")


if __name__ == "__main__":
    unittest.main()
