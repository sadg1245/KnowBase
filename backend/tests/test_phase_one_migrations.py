"""第一阶段：Alembic 迁移、旧库引导与数据保留。"""

import asyncio
import os
import sqlite3
import tempfile
import unittest

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.cli import main as cli_main
from app.core.db_bootstrap import BASELINE_REVISION, LegacyDatabaseError, ensure_database_ready
from app.core.legacy_schema import legacy_metadata
from app.models.base import Base


LEGACY_PROFILE = (
    "INSERT INTO user_profiles (id, display_name, daily_goal_minutes, daily_review_target, "
    "weekly_goal_days, timezone_name, preferred_mode, reminder_time, password_hash, "
    "created_at, updated_at) VALUES ('profile-1', '老用户', 40, 15, 6, 'Asia/Shanghai', "
    "'deep', '21:30', 'pbkdf2_sha256$240000$c2FsdA==$ZGVyaXZlZA==', "
    "'2025-01-01 00:00:00', '2025-01-02 00:00:00')"
)

LEGACY_ROWS = """
INSERT INTO workspaces (id, name, description, learning_goal, domain, accent_color,
    archived, slug, created_at, updated_at)
VALUES ('ws-1', '数学', '线性代数', '掌握矩阵', '理工', '#123456', 0, 'math',
        '2025-01-01 00:00:00', '2025-01-02 00:00:00'),
       ('ws-2', '杂项', '', '', '未分类', '#123456', 0, 'misc',
        '2025-01-01 00:00:00', '2025-01-02 00:00:00'),
       ('ws-3', '物理', '', '', '', '#123456', 1, 'physics',
        '2025-01-01 00:00:00', '2025-01-02 00:00:00');
INSERT INTO documents (id, workspace_id, filename, file_path, file_type, file_size,
    chunk_count, status, learning_status, tags, chapter_summaries, core_concepts,
    important_terms, common_mistakes, prerequisites, learning_order, review_points,
    created_at, updated_at)
VALUES ('doc-1', 'ws-1', 'book.pdf', '/data/uploads/ws-1/book.pdf', '.pdf', 100, 3, 'ready',
        'ready', '["A"]', '[]', '[]', '[]', '[]', '[]', '[]', '[]',
        '2025-01-01 00:00:00', '2025-01-02 00:00:00');
INSERT INTO knowledge_points (id, workspace_id, document_id, title, summary, explanation,
    importance, difficulty, mastery, tags, is_key, mastery_status, created_at, updated_at)
VALUES ('kp-1', 'ws-1', 'doc-1', '特征值', 's', 'e', 3, 2, 0.5, '["B"]', 1, 'learning',
        '2025-01-01 00:00:00', '2025-01-02 00:00:00');
INSERT INTO flashcards (id, workspace_id, knowledge_point_id, front, back, tags, difficulty,
    mastery, mastery_status, source_type, due_at, interval_days, ease, review_count,
    algorithm_version, scheduler_data, total_review_seconds, created_at, updated_at)
VALUES ('card-1', 'ws-1', 'kp-1', 'Q', 'A', '[]', 2, 0.5, 'learning', 'manual',
        '2025-01-02 00:00:00', 1, 2.5, 1, 'simple_v1', '{}', 30,
        '2025-01-01 00:00:00', '2025-01-02 00:00:00');
INSERT INTO chat_sessions (id, user_id, workspace_id, title, selected_document_ids,
    preferred_mode, strict_sources, is_favorite, created_at, updated_at, last_message_at)
VALUES ('cs-1', 'default', 'ws-1', '会话', '[]', 'simple', 1, 0,
        '2025-01-01 00:00:00', '2025-01-02 00:00:00', '2025-01-02 00:00:00');
INSERT INTO conversations (id, user_id, workspace_id, session_id, role, content,
    follow_up_questions, generation_status, created_at)
VALUES ('conv-1', 'legacy-open-id', 'ws-1', 'cs-1', 'user', 'hi', '[]', 'complete',
        '2025-01-02 00:00:00');
INSERT INTO study_activities (id, workspace_id, activity_type, title, duration_seconds,
    occurred_at, schema_version, created_at)
VALUES ('act-1', 'ws-1', 'document_read', '阅读', 300, '2025-01-02 00:00:00', 1,
        '2025-01-02 00:00:00');
INSERT INTO study_sessions (id, workspace_id, context_type, context_id, started_at,
    last_heartbeat_at, active_seconds, status, last_sequence, created_at, updated_at)
VALUES ('ss-1', 'ws-1', 'document', 'doc-1', '2025-01-02 00:00:00', '2025-01-02 00:10:00',
        600, 'completed', 3, '2025-01-02 00:00:00', '2025-01-02 00:10:00');
INSERT INTO learning_goals (id, scope_type, workspace_id, metric, target_value, is_active,
    version, created_at, updated_at)
VALUES ('goal-1', 'global', NULL, 'daily_minutes', 30, 1, 1,
        '2025-01-01 00:00:00', '2025-01-02 00:00:00');
INSERT INTO report_suggestions (id, period_type, period_start, period_end, timezone_name,
    stats_hash, stats_snapshot, status, created_at, updated_at)
VALUES ('rs-1', 'week', '2025-01-01 00:00:00', '2025-01-08 00:00:00', 'Asia/Shanghai',
        'hash-1', '{}', 'ready', '2025-01-01 00:00:00', '2025-01-02 00:00:00');
"""


def _table_counts(path: str, tables: tuple[str, ...]) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
    finally:
        connection.close()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        self.directory.cleanup()

    def _path(self, name: str) -> str:
        return os.path.join(self.directory.name, name)

    async def _build_legacy(self, name: str = "legacy.db", seed: bool = True) -> str:
        path = self._path(name)
        engine = create_async_engine("sqlite+aiosqlite:///" + path)
        async with engine.begin() as connection:
            await connection.run_sync(legacy_metadata.create_all)
        await engine.dispose()
        if seed:
            connection = sqlite3.connect(path)
            connection.executescript(LEGACY_PROFILE + ";" + LEGACY_ROWS)
            connection.commit()
            connection.close()
        return path

    async def test_fresh_database_upgrades_to_head_with_the_orm_schema(self):
        path = self._path("fresh.db")
        report = await ensure_database_ready("sqlite+aiosqlite:///" + path)
        self.assertEqual(report.action, "empty")

        engine = create_async_engine("sqlite+aiosqlite:///" + path)
        async with engine.connect() as connection:
            existing_tables = set(await connection.run_sync(
                lambda sync: sa.inspect(sync).get_table_names()
            ))
            self.assertTrue(set(Base.metadata.tables) <= existing_tables)
            for name, table in Base.metadata.tables.items():
                columns = {
                    column["name"]
                    for column in await connection.run_sync(
                        lambda sync, table_name=name: sa.inspect(sync).get_columns(table_name)
                    )
                }
                self.assertEqual(columns, {column.name for column in table.columns}, name)
        await engine.dispose()

        # 全新数据库需要等待首次设置，并且只允许一个账号。
        connection = sqlite3.connect(path)
        rows = connection.execute("SELECT username, password_hash FROM users").fetchall()
        connection.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "__pending_setup__")
        self.assertIsNone(rows[0][1])

    async def test_legacy_database_keeps_ids_paths_and_relations(self):
        path = await self._build_legacy()
        before = _table_counts(path, (
            "documents", "knowledge_points", "flashcards", "conversations",
            "chat_sessions", "study_activities", "study_sessions",
        ))
        connection = sqlite3.connect(path)
        document_path = connection.execute(
            "SELECT file_path FROM documents WHERE id = 'doc-1'"
        ).fetchone()[0]
        connection.close()

        report = await ensure_database_ready("sqlite+aiosqlite:///" + path)
        self.assertEqual(report.action, "legacy")
        self.assertEqual(report.revision, "0004_rag_pipeline_events")

        self.assertEqual(_table_counts(path, tuple(before)), before)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            document = connection.execute("SELECT * FROM documents WHERE id = 'doc-1'").fetchone()
            self.assertEqual(document["file_path"], document_path)
            self.assertEqual(document["workspace_id"], "ws-1")

            user = connection.execute("SELECT * FROM users").fetchone()
            self.assertEqual(user["id"], "profile-1")
            self.assertEqual(user["username"], "owner")
            self.assertEqual(user["display_name"], "老用户")
            self.assertTrue(user["password_hash"])

            preference = connection.execute(
                "SELECT * FROM learning_preferences WHERE user_id = 'profile-1'"
            ).fetchone()
            self.assertEqual(preference["daily_goal_minutes"], 40)
            self.assertEqual(preference["timezone_name"], "Asia/Shanghai")

            owners = {
                row[0] for row in connection.execute(
                    "SELECT DISTINCT owner_id FROM workspaces"
                ).fetchall()
            }
            self.assertEqual(owners, {"profile-1"})
            for table in (
                "study_activities", "study_sessions", "learning_goals", "report_suggestions",
                "conversations", "chat_sessions",
            ):
                values = {
                    row[0] for row in connection.execute(
                        f"SELECT DISTINCT user_id FROM {table}"
                    ).fetchall()
                }
                self.assertEqual(values, {"profile-1"}, table)

            domains = connection.execute(
                "SELECT id, name FROM learning_domains"
            ).fetchall()
            self.assertEqual([row["name"] for row in domains], ["理工"])
            mapping = dict(connection.execute(
                "SELECT id, domain_id FROM workspaces"
            ).fetchall())
            self.assertEqual(mapping["ws-1"], domains[0]["id"])
            self.assertIsNone(mapping["ws-2"])
            self.assertIsNone(mapping["ws-3"])

            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'user_profiles'"
            ).fetchone())
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            connection.close()

        # 重复执行不会重复回填。
        await ensure_database_ready("sqlite+aiosqlite:///" + path)
        self.assertEqual(_table_counts(path, tuple(before)), before)
        connection = sqlite3.connect(path)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM learning_domains").fetchone()[0], 1
        )
        connection.close()

    async def test_legacy_bootstrap_refuses_a_broken_structure(self):
        path = await self._build_legacy("broken.db", seed=False)
        connection = sqlite3.connect(path)
        connection.execute("ALTER TABLE knowledge_points RENAME TO knowledge_points_old")
        connection.execute("CREATE TABLE knowledge_points (id VARCHAR(36) NOT NULL)")
        connection.commit()
        connection.close()

        with self.assertRaises(LegacyDatabaseError) as raised:
            await ensure_database_ready("sqlite+aiosqlite:///" + path)
        self.assertIn("knowledge_points.mastery", str(raised.exception))

        # 结构不合规时不得登记基线。
        connection = sqlite3.connect(path)
        self.assertIsNone(connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'alembic_version'"
        ).fetchone())
        connection.close()

    async def test_stamp_then_upgrade_marks_the_baseline_revision(self):
        path = await self._build_legacy()
        await ensure_database_ready("sqlite+aiosqlite:///" + path)
        connection = sqlite3.connect(path)
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        connection.close()
        self.assertNotEqual(revision, BASELINE_REVISION)

    async def test_cli_migrate_is_the_documented_entry_point(self):
        path = os.path.join(self.directory.name, "cli.db")
        url = "sqlite+aiosqlite:///" + path
        from app.config import settings

        original = settings.DATABASE_URL
        settings.DATABASE_URL = url
        try:
            code = await asyncio.to_thread(cli_main, ["migrate"])
        finally:
            settings.DATABASE_URL = original
        self.assertEqual(code, 0)
        connection = sqlite3.connect(path)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1
        )
        connection.close()

    async def test_cli_without_a_known_command_exits_with_usage(self):
        self.assertEqual(await asyncio.to_thread(cli_main, []), 2)
        self.assertEqual(await asyncio.to_thread(cli_main, ["bogus"]), 2)


if __name__ == "__main__":
    unittest.main()
