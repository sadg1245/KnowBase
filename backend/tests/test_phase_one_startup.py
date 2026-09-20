"""第一阶段：真实启动路径（环境变量 → 迁移 → 检索索引 → 密钥校验）。

为了走通部署时的真实顺序，这些用例在子进程里用环境变量启动应用，
而不是在导入之后修改 `settings`——引擎是在导入时按配置创建的。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


BOOTSTRAP_PROGRAM = r'''
import asyncio
import json
import os

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def inspect(url: str) -> dict:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            from app.models.user import User

            users = (await session.execute(select(User))).scalars().all()
            return {
                "revision": await session.scalar(text("SELECT version_num FROM alembic_version")),
                "users": [
                    {"username": user.username, "has_password": bool(user.password_hash)}
                    for user in users
                ],
                "fts": await session.scalar(text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'document_chunks_fts'"
                )),
                "avatar_dir": os.path.isdir(os.path.join(os.environ["MEDIA_DIR"], "avatars")),
                "cover_dir": os.path.isdir(os.path.join(os.environ["MEDIA_DIR"], "covers")),
                "secret_file": os.path.isfile(os.path.join(
                    os.environ["KNOWBASE_HOME"], "secrets", "jwt_secret"
                )),
            }
    finally:
        await engine.dispose()


async def activate_account(url: str) -> None:
    """把待设置的占位所有者变成已建号账号，用于校验密钥强度检查。"""
    from app.core.auth import hash_password
    from app.models.user import User

    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            user = (await session.execute(select(User))).scalars().one()
            user.username = "owner"
            user.display_name = "学习者"
            user.password_hash = hash_password("correct-horse-battery")
            await session.commit()
    finally:
        await engine.dispose()


async def main() -> dict:
    from app.main import app, lifespan

    url = os.environ["DATABASE_URL"]
    async with lifespan(app):
        pass
    if os.environ.get("SEED_ACCOUNT") == "1":
        await activate_account(url)
        # 第二次进入启动流程：账号已存在时也必须能正常启动（密钥由程序自管）。
        async with lifespan(app):
            pass
    return await inspect(url)


try:
    print("RESULT " + json.dumps(asyncio.run(main()), ensure_ascii=False))
except Exception as exc:
    print(f"ERROR {type(exc).__name__}: {exc}")
    raise SystemExit(3)
'''


class StartupSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_url = "sqlite+aiosqlite:///" + os.path.join(self.directory.name, "startup.db")
        self.media_dir = os.path.join(self.directory.name, "media")
        self.app_home = os.path.join(self.directory.name, "home")

    def run_bootstrap(self, *, seed_account: bool = False, secret: str = "x" * 40) -> subprocess.CompletedProcess:
        environment = dict(os.environ)
        environment.update({
            "PYTHONPATH": str(BACKEND_ROOT),
            "PYTHONIOENCODING": "utf-8",
            "DATABASE_URL": self.database_url,
            "UPLOAD_DIR": os.path.join(self.directory.name, "uploads"),
            "MEDIA_DIR": self.media_dir,
            "KNOWBASE_HOME": self.app_home,
            "JWT_SECRET": secret,
            "SERVICE_TOKEN": "",
        })
        environment["SEED_ACCOUNT"] = "1" if seed_account else "0"
        return subprocess.run(
            [sys.executable, "-c", BOOTSTRAP_PROGRAM],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )

    @staticmethod
    def result_payload(completed: subprocess.CompletedProcess) -> dict:
        for line in completed.stdout.splitlines():
            if line.startswith("RESULT "):
                return json.loads(line[len("RESULT "):])
        raise AssertionError(f"没有输出结果：{completed.stdout}\n{completed.stderr}")

    def test_fresh_install_migrates_creates_index_and_waits_for_setup(self):
        completed = self.run_bootstrap()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = self.result_payload(completed)

        self.assertEqual(payload["revision"], "0011_learning_coverage")
        self.assertEqual(len(payload["users"]), 1)
        self.assertEqual(payload["users"][0]["username"], "__pending_setup__")
        self.assertFalse(payload["users"][0]["has_password"])
        self.assertEqual(payload["fts"], "document_chunks_fts")
        self.assertTrue(payload["avatar_dir"])
        self.assertTrue(payload["cover_dir"])
        # 运维已显式提供强密钥时不再另外生成，避免出现两套密钥
        self.assertFalse(payload["secret_file"])

    def test_repeated_start_is_idempotent(self):
        first = self.run_bootstrap()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_bootstrap()
        self.assertEqual(second.returncode, 0, second.stderr)

        payload = self.result_payload(second)
        self.assertEqual(payload["revision"], "0011_learning_coverage")
        self.assertEqual(len(payload["users"]), 1)

    def test_default_secret_is_replaced_by_a_managed_one(self):
        """默认/不安全密钥不再让服务无法启动，而是改成程序自管的本机密钥。"""
        completed = self.run_bootstrap(
            seed_account=True, secret="knowbase-secret-key-change-in-production"
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = self.result_payload(completed)
        self.assertEqual(len(payload["users"]), 1)
        self.assertTrue(payload["users"][0]["has_password"])
        self.assertTrue(payload["secret_file"])
        self.assertNotIn("InsecureSecretError", completed.stdout)

    def test_start_accepts_a_strong_secret_when_the_account_exists(self):
        completed = self.run_bootstrap(seed_account=True, secret="s" * 48)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = self.result_payload(completed)
        self.assertEqual(len(payload["users"]), 1)
        self.assertEqual(payload["users"][0]["username"], "owner")
        self.assertTrue(payload["users"][0]["has_password"])


if __name__ == "__main__":
    unittest.main()
