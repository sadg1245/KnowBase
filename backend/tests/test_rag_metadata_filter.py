"""阶段 4：元数据硬预过滤（Chroma where 与 FTS SQL 两条路径语义一致）。"""

import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.schemas.scope import ResolvedRetrievalScope
from app.services.hybrid_retrieval import (
    HybridRetrievalService,
    RetrievalRequest,
    build_metadata_where,
    build_sql_metadata_filter,
)
from tests.support import create_user, create_workspace


class MetadataWhereTests(unittest.TestCase):
    def test_empty_filters_produce_no_clause(self):
        self.assertIsNone(build_metadata_where(None))
        self.assertIsNone(build_metadata_where({}))
        self.assertIsNone(build_metadata_where({"content_types": []}))
        self.assertEqual(build_sql_metadata_filter(None), ("", {}))

    def test_single_clause_is_not_wrapped(self):
        self.assertEqual(
            build_metadata_where({"content_types": ["question", "definition"]}),
            {"content_type": {"$in": ["question", "definition"]}},
        )

    def test_multiple_clauses_are_combined_with_and(self):
        where = build_metadata_where({
            "content_types": ["question"],
            "exclude_content_types": ["answer"],
            "document_types": ["exam"],
            "subjects": ["概率论"],
            "difficulty_range": (1, 3),
        })
        self.assertEqual(where["$and"][0], {"content_type": {"$in": ["question"]}})
        self.assertEqual(where["$and"][1], {"content_type": {"$nin": ["answer"]}})
        self.assertEqual(where["$and"][2], {"document_type": {"$in": ["exam"]}})
        self.assertEqual(where["$and"][3], {"subject": {"$in": ["概率论"]}})
        self.assertEqual(where["$and"][4], {"difficulty": {"$gte": 1, "$lte": 3}})

    def test_sql_filter_matches_where_semantics(self):
        fragment, params = build_sql_metadata_filter({
            "content_types": ["question"],
            "exclude_content_types": ["answer", "solution"],
            "difficulty_range": (2, 4),
        })

        self.assertIn("c.content_type IN (:md_content_type_0)", fragment)
        self.assertIn("c.content_type NOT IN (:md_exclude_type_0, :md_exclude_type_1)", fragment)
        self.assertIn("c.difficulty BETWEEN :md_difficulty_low AND :md_difficulty_high", fragment)
        self.assertEqual(params["md_content_type_0"], "question")
        self.assertEqual(params["md_exclude_type_1"], "solution")
        self.assertEqual(params["md_difficulty_low"], 2)
        self.assertEqual(params["md_difficulty_high"], 4)


class MetadataFilterPropagationTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_passes_filters_to_the_vector_recall(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        db = sessions()
        user = await create_user(db)
        workspace = await create_workspace(db, user, name="过滤", slug="metadata-filter")
        captured: dict = {}

        async def recall(**kwargs):
            captured.update(kwargs)
            return []

        service = HybridRetrievalService(db, recall)
        scope = ResolvedRetrievalScope(
            mode="strict", hard_workspace_ids=[workspace.id], resolved_by="explicit"
        )
        filters = {"exclude_content_types": ["answer", "solution"], "content_types": ["question"]}
        await service.retrieve_scoped(RetrievalRequest(
            query="练习",
            scope=scope,
            owned_workspace_ids=[workspace.id],
            metadata_filter=filters,
        ))

        self.assertEqual(captured.get("filters"), filters)
        await db.close()
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
