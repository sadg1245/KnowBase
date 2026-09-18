"""Memory persistence contracts and SQLite bootstrap idempotency."""

import unittest

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.core.migrations import MEMORY_FTS_STATEMENTS, ensure_memory_index
from app.models.base import Base


class MemoryModelTests(unittest.TestCase):
    def test_learning_memory_table_is_registered(self):
        table = Base.metadata.tables.get("learning_memories")
        if table is None:
            self.fail("learning_memories is not registered")

        for name in (
            "id",
            "user_id",
            "workspace_id",
            "kind",
            "title",
            "content",
            "source_refs",
            "importance",
            "is_active",
            "embedding_state",
            "last_used_at",
            "use_count",
            "created_at",
            "updated_at",
        ):
            with self.subTest(column=name):
                self.assertIn(name, table.columns)

    def test_conversations_keep_tutor_diagnostics(self):
        columns = Base.metadata.tables["conversations"].columns

        for name in ("answer_policy", "used_memory_ids", "profile_summary"):
            with self.subTest(column=name):
                self.assertIn(name, columns)


class MemoryIndexTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_index_bootstrap_is_idempotent(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            first = await ensure_memory_index(connection)
            second = await ensure_memory_index(connection)
            rows = (
                await connection.execute(
                    sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_memories_fts'")
                )
            ).all()
        await engine.dispose()

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(MEMORY_FTS_STATEMENTS), 4)


if __name__ == "__main__":
    unittest.main()
