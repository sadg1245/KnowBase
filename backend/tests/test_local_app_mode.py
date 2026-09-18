"""本地优先模式：应用主目录、密钥自管、升级前备份、偏好持久化、嵌入向量库。"""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from sqlalchemy import create_engine

from app.config import Settings
from app.core import app_settings_store
from app.core.app_paths import default_app_home
from app.core.chroma import describe_backend, get_chroma_client, reset_chroma_client
from app.core.db_bootstrap import BASELINE_REVISION, backup_database, ensure_database_ready
from app.core.legacy_schema import legacy_metadata
from app.core.secrets_store import is_strong_secret, resolve_jwt_secret


DEFAULT_SECRET = "replace-with-a-long-random-secret"

# 注意：导入 litellm（评测/生成相关模块会间接导入）时它会执行 load_dotenv()，
# 把仓库根目录的 .env 注入到 os.environ。这些用例要断言"从零推导"的默认值，
# 因此必须先把这些键从进程环境里摘掉，测完再还原。
APP_ENV_KEYS = (
    "DATA_ROOT", "KNOWBASE_HOME", "DATABASE_URL", "UPLOAD_DIR", "UPLOAD_MAX_SIZE_MB",
    "MEDIA_DIR", "CHROMA_DIR", "CHROMA_HOST", "CHROMA_PORT", "JWT_SECRET",
    "DEFAULT_LLM_PROVIDER", "DEFAULT_LLM_MODEL", "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_EMBEDDING", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY", "OLLAMA_BASE_URL", "SERVICE_TOKEN",
)


@contextmanager
def isolated_settings_env():
    """在隔离的进程环境下构造 Settings，避免第三方库注入的 .env 值干扰断言。"""
    saved = {key: os.environ.pop(key, None) for key in APP_ENV_KEYS}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value


class AppHomeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name

    def test_derived_paths_live_under_the_app_home(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, _env_file=None)

        self.assertEqual(config.DATA_ROOT, os.path.abspath(self.root))
        self.assertEqual(
            config.DATABASE_URL,
            f"sqlite+aiosqlite:///{os.path.join(self.root, 'sqlite', 'knowbase.db').replace(chr(92), '/')}",
        )
        self.assertEqual(config.UPLOAD_DIR, os.path.join(self.root, "uploads"))
        self.assertEqual(config.MEDIA_DIR, os.path.join(self.root, "media"))
        self.assertEqual(config.CHROMA_DIR, os.path.join(self.root, "chroma"))
        self.assertEqual(config.SECRETS_DIR, os.path.join(self.root, "secrets"))
        self.assertEqual(config.BACKUPS_DIR, os.path.join(self.root, "backups"))
        self.assertEqual(config.SETTINGS_FILE, os.path.join(self.root, "settings.json"))

    def test_explicit_paths_still_win(self):
        """容器/自托管部署显式配置的路径与远程向量库地址必须保持不变。"""
        with isolated_settings_env():
            config = Settings(
                DATA_ROOT=self.root,
                DATABASE_URL="sqlite+aiosqlite:////app/data/sqlite/knowbase.db",
                UPLOAD_DIR="/app/uploads",
                MEDIA_DIR="/app/data/media",
                CHROMA_HOST="chromadb",
                _env_file=None,
            )

        self.assertEqual(config.DATABASE_URL, "sqlite+aiosqlite:////app/data/sqlite/knowbase.db")
        self.assertEqual(config.UPLOAD_DIR, "/app/uploads")
        self.assertEqual(config.MEDIA_DIR, "/app/data/media")
        self.assertFalse(config.local_chroma_enabled)
        self.assertEqual(describe_backend(config), "http(chromadb:8000)")

    def test_default_home_can_be_redirected_by_environment(self):
        with isolated_settings_env():
            with patch.dict(os.environ, {"KNOWBASE_HOME": self.root}):
                self.assertEqual(default_app_home(), os.path.abspath(self.root))
        self.assertTrue(default_app_home())


class ManagedSecretTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name

    def test_weak_secret_is_replaced_by_a_generated_one_that_survives_restart(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, JWT_SECRET=DEFAULT_SECRET, _env_file=None)

            first = resolve_jwt_secret(config)
            self.assertEqual(first.source, "generated")
            self.assertTrue(is_strong_secret(first.value))
            self.assertNotEqual(first.value, DEFAULT_SECRET)
            secret_file = os.path.join(config.SECRETS_DIR, "jwt_secret")
            self.assertTrue(os.path.isfile(secret_file))
            self.assertEqual(open(secret_file, encoding="utf-8").read().strip(), first.value)

            # 重启后（新的 Settings 对象）复用同一个密钥，已登录用户不会被登出
            restarted = Settings(DATA_ROOT=self.root, JWT_SECRET=DEFAULT_SECRET, _env_file=None)
            second = resolve_jwt_secret(restarted)
        self.assertEqual(second.source, "stored")
        self.assertEqual(second.value, first.value)

    def test_operator_provided_strong_secret_is_used_without_persisting(self):
        strong = "k" * 48
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, JWT_SECRET=strong, _env_file=None)

            resolved = resolve_jwt_secret(config)
        self.assertEqual(resolved.source, "configured")
        self.assertEqual(resolved.value, strong)
        self.assertFalse(os.path.exists(os.path.join(config.SECRETS_DIR, "jwt_secret")))


class PersistedSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name

    def test_model_configuration_and_api_key_survive_restart(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, _env_file=None)
            config.DEFAULT_LLM_PROVIDER = "zhipu"
            config.DEFAULT_LLM_MODEL = "glm-4"
            config.ZHIPU_API_KEY = "sk-zhipu-local"
            app_settings_store.save(config)

            restarted = Settings(DATA_ROOT=self.root, _env_file=None)
            # 清空后应用持久化配置：证明值来自本机文件而不是环境变量
            restarted.DEFAULT_LLM_MODEL = "sentinel"
            restarted.ZHIPU_API_KEY = None
            self.assertTrue(app_settings_store.apply_persisted(restarted))
        self.assertEqual(restarted.DEFAULT_LLM_PROVIDER, "zhipu")
        self.assertEqual(restarted.DEFAULT_LLM_MODEL, "glm-4")
        self.assertEqual(restarted.ZHIPU_API_KEY, "sk-zhipu-local")
        self.assertTrue(app_settings_store.has_llm_api_key(restarted))

    def test_llm_key_presence_depends_on_the_selected_provider(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, DEFAULT_LLM_PROVIDER="zhipu", _env_file=None)
        config.ZHIPU_API_KEY = None
        self.assertFalse(app_settings_store.has_llm_api_key(config))
        config.ZHIPU_API_KEY = "sk-zhipu"
        self.assertTrue(app_settings_store.has_llm_api_key(config))

    def test_ollama_needs_no_api_key(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, DEFAULT_LLM_PROVIDER="ollama", _env_file=None)
        self.assertTrue(app_settings_store.has_llm_api_key(config))

    def test_corrupted_file_is_ignored_instead_of_crashing(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, _env_file=None)
        with open(config.SETTINGS_FILE, "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")

        self.assertEqual(app_settings_store.load_raw(config.SETTINGS_FILE), {})
        self.assertFalse(app_settings_store.apply_persisted(config))

    def test_written_file_is_valid_json_without_leaking_other_secrets(self):
        with isolated_settings_env():
            config = Settings(DATA_ROOT=self.root, DEEPSEEK_API_KEY="sk-1", _env_file=None)
        app_settings_store.save(config)
        payload = json.load(open(config.SETTINGS_FILE, encoding="utf-8"))
        self.assertEqual(payload["version"], app_settings_store.SETTINGS_VERSION)
        self.assertEqual(payload["api_keys"]["deepseek"], "sk-1")
        self.assertNotIn("JWT_SECRET", json.dumps(payload))


class UpgradeBackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.directory.name, "sqlite", "knowbase.db")
        os.makedirs(os.path.dirname(self.database_path), exist_ok=True)
        self.database_url = "sqlite+aiosqlite:///" + self.database_path.replace("\\", "/")
        self.backup_dir = os.path.join(self.directory.name, "backups")

    async def asyncTearDown(self):
        self.directory.cleanup()

    def _build_legacy_database(self) -> None:
        engine = create_engine("sqlite:///" + self.database_path.replace("\\", "/"))
        legacy_metadata.create_all(engine)
        engine.dispose()
        connection = sqlite3.connect(self.database_path)
        connection.executescript(
            "INSERT INTO user_profiles (id, display_name, daily_goal_minutes, "
            "daily_review_target, weekly_goal_days, timezone_name, preferred_mode, "
            "reminder_time, created_at, updated_at) VALUES "
            "('profile-1', '老用户', 30, 10, 5, 'Asia/Shanghai', 'explain', '20:00', "
            "'2025-01-01 00:00:00', '2025-01-02 00:00:00');"
            "INSERT INTO workspaces (id, name, description, learning_goal, domain, "
            "accent_color, archived, slug, created_at, updated_at) VALUES "
            "('ws-1', '数学', '', '', '未分类', '#123456', 0, 'math', "
            "'2025-01-01 00:00:00', '2025-01-02 00:00:00');"
        )
        connection.commit()
        connection.close()

    def _backups(self) -> list[str]:
        if not os.path.isdir(self.backup_dir):
            return []
        return sorted(os.listdir(self.backup_dir))

    async def test_upgrade_backs_up_the_database_before_changing_it(self):
        self._build_legacy_database()

        report = await ensure_database_ready(self.database_url, backup_dir=self.backup_dir)

        self.assertEqual(report.action, "legacy")
        self.assertEqual(report.revision, "0003_ai_tutor_memory")
        self.assertIsNotNone(report.backup_path)
        self.assertTrue(os.path.isfile(report.backup_path))

        # 备份必须是"升级前"的状态：仍带旧表与旧数据
        backup = sqlite3.connect(report.backup_path)
        tables = {row[0] for row in backup.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()}
        self.assertIn("user_profiles", tables)
        self.assertNotIn("users", tables)
        self.assertEqual(
            backup.execute("SELECT display_name FROM user_profiles").fetchone()[0], "老用户"
        )
        backup.close()

    async def test_no_backup_when_the_schema_is_already_current(self):
        self._build_legacy_database()
        await ensure_database_ready(self.database_url, backup_dir=self.backup_dir)
        after_first = self._backups()
        self.assertEqual(len(after_first), 1)

        await ensure_database_ready(self.database_url, backup_dir=self.backup_dir)
        self.assertEqual(self._backups(), after_first)

    async def test_old_backups_are_pruned(self):
        self._build_legacy_database()
        os.makedirs(self.backup_dir, exist_ok=True)
        for index in range(6):
            stale = os.path.join(self.backup_dir, f"knowbase-2020010{index}-000000.db")
            with open(stale, "w", encoding="utf-8") as handle:
                handle.write("stale")
            os.utime(stale, (index, index))

        await ensure_database_ready(
            self.database_url, backup_dir=self.backup_dir, backup_keep=3
        )

        # 最近的一份 + 新备份保留，旧的不超过 3 份
        self.assertLessEqual(len(self._backups()), 3)
        self.assertIsNotNone(await ensure_database_ready(
            self.database_url, backup_dir=self.backup_dir, backup_keep=3
        ))

    def test_direct_backup_helper_is_a_noop_for_missing_files(self):
        self.assertIsNone(
            backup_database("sqlite+aiosqlite:///" + os.path.join(self.directory.name, "absent.db"), self.backup_dir)
        )
        self.assertIsNone(backup_database("postgresql+asyncpg://user@host/db", self.backup_dir))


class EmbeddedVectorStoreTests(unittest.TestCase):
    def setUp(self):
        # Chroma 的本地持久化客户端会一直持有文件句柄，Windows 上无法立刻删除目录
        self.directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.directory.cleanup)
        reset_chroma_client()
        self.addCleanup(reset_chroma_client)

    def test_default_is_embedded_and_works_without_a_server(self):
        with isolated_settings_env():
            config = Settings(
                DATA_ROOT=self.directory.name, CHROMA_HOST="local", _env_file=None
            )
            self.assertTrue(config.local_chroma_enabled)
            self.assertIn("embedded", describe_backend(config))

            client = get_chroma_client(config)
            collection = client.get_or_create_collection(name="ws_demo")
            collection.add(ids=["chunk-1"], documents=["微积分基本定理"], embeddings=[[0.1, 0.2, 0.3]])

            self.assertEqual(collection.count(), 1)
            self.assertEqual(client.list_collections()[0].name, "ws_demo")
            self.assertTrue(os.path.isdir(config.CHROMA_DIR))


if __name__ == "__main__":
    unittest.main()
