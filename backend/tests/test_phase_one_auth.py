"""第一阶段：账号创建、登录、当前用户与安全边界。"""

import time
import unittest
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.api.deps import get_db
from app.config import InsecureSecretError, settings, validate_security_configuration
from app.core.auth import create_token, hash_password, verify_password
from app.main import app
from app.models.base import Base
from app.models.user import LearningPreference, User
from tests.support import TEST_PASSWORD, create_workspace


class AuthFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()

        async def database():
            yield self.db
            await self.db.commit()

        app.dependency_overrides[get_db] = database
        app.state.session_factory = self.sessions
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        app.dependency_overrides.clear()
        if hasattr(app.state, "session_factory"):
            del app.state.session_factory
        await self.client.aclose()
        await self.db.close()
        await self.engine.dispose()

    async def _setup(self, username="learner", password=TEST_PASSWORD):
        return await self.client.post("/api/auth/setup", json={
            "username": username,
            "password": password,
            "display_name": "小明",
        })

    async def test_status_setup_login_and_logout_flow(self):
        status = await self.client.get("/api/auth/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json(), {
            "configured": False, "setup_required": True, "login_required": True,
        })

        created = await self._setup()
        self.assertEqual(created.status_code, 201, created.text)
        token = created.json()["token"]
        self.assertNotIn("password", created.text)
        self.assertEqual(created.json()["user"]["username"], "learner")

        after = await self.client.get("/api/auth/status")
        self.assertTrue(after.json()["configured"])
        self.assertFalse(after.json()["setup_required"])

        duplicate = await self._setup(username="second")
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(await self.db.scalar(select(func.count(User.id))), 1)

        wrong = await self.client.post("/api/auth/login", json={
            "username": "learner", "password": "not-the-password",
        })
        self.assertEqual(wrong.status_code, 401)
        unknown = await self.client.post("/api/auth/login", json={
            "username": "nobody", "password": TEST_PASSWORD,
        })
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json()["detail"], wrong.json()["detail"])

        login = await self.client.post("/api/auth/login", json={
            "username": "learner", "password": TEST_PASSWORD,
        })
        self.assertEqual(login.status_code, 200, login.text)

        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        me = await self.client.get("/api/me", headers=headers)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["display_name"], "小明")
        self.assertNotIn("password_hash", me.text)

        logout = await self.client.post("/api/auth/logout", headers=headers)
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(token[:8], login.json()["token"][:8])

    async def test_private_routes_reject_missing_expired_and_forged_tokens(self):
        created = await self._setup()
        user_id = created.json()["user"]["id"]

        anonymous = await self.client.get("/api/workspaces")
        self.assertEqual(anonymous.status_code, 401)

        forged = await self.client.get(
            "/api/workspaces",
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        self.assertEqual(forged.status_code, 401)

        async def expired(subject: str) -> str:
            application = settings.SESSION_DAYS
            settings.SESSION_DAYS = -1
            try:
                return create_token(subject)
            finally:
                settings.SESSION_DAYS = application

        stale = await expired(user_id)
        response = await self.client.get(
            "/api/workspaces", headers={"Authorization": f"Bearer {stale}"}
        )
        self.assertEqual(response.status_code, 401)

    async def test_deactivated_user_loses_access_immediately(self):
        created = await self._setup()
        headers = {"Authorization": f"Bearer {created.json()['token']}"}
        self.assertEqual((await self.client.get("/api/me", headers=headers)).status_code, 200)

        user = await self.db.scalar(select(User))
        user.is_active = False
        await self.db.commit()

        self.assertEqual((await self.client.get("/api/me", headers=headers)).status_code, 401)

    async def test_setup_completes_a_placeholder_owner_without_creating_a_second_account(self):
        placeholder = User(username="__pending_setup__", display_name="学习者")
        self.db.add(placeholder)
        await self.db.flush()
        self.db.add(LearningPreference(user_id=placeholder.id))
        await self.db.commit()

        status = await self.client.get("/api/auth/status")
        self.assertTrue(status.json()["setup_required"])

        created = await self._setup(username="owner")
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["user"]["id"], placeholder.id)
        self.assertEqual(await self.db.scalar(select(func.count(User.id))), 1)

    async def test_migrated_owner_without_password_is_not_a_dead_end(self):
        """旧库迁移出的账号（用户名 owner、从未设过密码）必须能通过建号补全。"""
        migrated = User(username="owner", display_name="学习者")
        self.db.add(migrated)
        await self.db.flush()
        self.db.add(LearningPreference(user_id=migrated.id))
        await self.db.commit()

        status = await self.client.get("/api/auth/status")
        self.assertTrue(status.json()["setup_required"])

        created = await self._setup(username="哈喽")
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["user"]["id"], migrated.id)
        self.assertEqual(created.json()["user"]["username"], "哈喽")
        self.assertEqual(await self.db.scalar(select(func.count(User.id))), 1)

        # 建号完成后入口关闭
        again = await self._setup(username="另一个")
        self.assertEqual(again.status_code, 409)

        # 新用户名与新密码可以正常登录
        login = await self.client.post("/api/auth/login", json={
            "username": "哈喽", "password": TEST_PASSWORD,
        })
        self.assertEqual(login.status_code, 200, login.text)

    async def test_service_token_binds_to_the_single_account_and_never_wide_opens(self):
        await self._setup()
        original = settings.SERVICE_TOKEN
        settings.SERVICE_TOKEN = "service-secret"
        try:
            bound = await self.client.get(
                "/api/workspaces", headers={"X-KnowBase-Service-Token": "service-secret"}
            )
            self.assertEqual(bound.status_code, 200, bound.text)

            rejected = await self.client.get(
                "/api/workspaces", headers={"X-KnowBase-Service-Token": "wrong-secret"}
            )
            self.assertEqual(rejected.status_code, 401)

            await self.db.execute(User.__table__.delete())
            await self.db.commit()
            unbound = await self.client.get(
                "/api/workspaces", headers={"X-KnowBase-Service-Token": "service-secret"}
            )
            self.assertEqual(unbound.status_code, 503)
        finally:
            settings.SERVICE_TOKEN = original

    async def test_preferences_and_profile_edits_are_scoped_to_the_current_user(self):
        created = await self._setup()
        headers = {"Authorization": f"Bearer {created.json()['token']}"}

        defaults = await self.client.get("/api/me/preferences", headers=headers)
        self.assertEqual(defaults.status_code, 200, defaults.text)
        self.assertEqual(defaults.json()["daily_goal_minutes"], 25)

        updated = await self.client.put(
            "/api/me/preferences",
            headers=headers,
            json={"daily_goal_minutes": 45, "timezone_name": "Asia/Shanghai"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["daily_goal_minutes"], 45)

        invalid = await self.client.put(
            "/api/me/preferences", headers=headers, json={"timezone_name": "Mars/Olympus"}
        )
        self.assertEqual(invalid.status_code, 422)

        renamed = await self.client.patch(
            "/api/me", headers=headers, json={"display_name": "小红"}
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["display_name"], "小红")

        insecure = await self.client.patch(
            "/api/me", headers=headers, json={"avatar_url": "http://example.com/a.png"}
        )
        self.assertEqual(insecure.status_code, 422)
        external = await self.client.patch(
            "/api/me", headers=headers, json={"avatar_url": "https://example.com/a.png"}
        )
        self.assertEqual(external.status_code, 200)
        self.assertEqual(external.json()["avatar_kind"], "url")
        cleared = await self.client.patch(
            "/api/me", headers=headers, json={"clear_avatar": True}
        )
        self.assertEqual(cleared.json()["avatar_url"], None)

        workspaces = await self.client.get("/api/workspaces", headers=headers)
        self.assertEqual(workspaces.json(), [])


class PasswordAndSecretTests(unittest.TestCase):
    def test_password_hashes_are_salted_and_constant_time_verified(self):
        first = hash_password("same-password")
        second = hash_password("same-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("same-password", first))
        self.assertFalse(verify_password("other-password", first))
        self.assertFalse(verify_password("same-password", "malformed"))

    def test_insecure_jwt_secrets_are_rejected_once_an_account_exists(self):
        with self.assertRaises(InsecureSecretError):
            validate_security_configuration(
                "knowbase-secret-key-change-in-production", account_configured=True
            )
        with self.assertRaises(InsecureSecretError):
            validate_security_configuration("short-secret", account_configured=True)
        validate_security_configuration("x" * 40, account_configured=True)
        # 建号之前允许启动设置流程。
        validate_security_configuration("knowbase-secret-key-change-in-production", account_configured=False)


if __name__ == "__main__":
    unittest.main()
