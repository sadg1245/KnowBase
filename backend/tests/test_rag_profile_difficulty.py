"""阶段 5：画像折算难度偏好，并只通过排序 Bonus 影响检索。"""

import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.models.learning import KnowledgePoint
from app.schemas.scope import ResolvedRetrievalScope
from app.services.hybrid_retrieval import (
    HybridRetrievalService,
    RetrievalCandidate,
    RetrievalRequest,
    _profile_preference_bonus,
)
from app.services.learner_profile import LearnerProfileService, content_types_for_level
from tests.support import create_user, create_workspace


class ContentTypePreferenceTests(unittest.TestCase):
    def test_level_bands_follow_the_design(self):
        self.assertIn("definition", content_types_for_level(1))
        self.assertIn("intuition", content_types_for_level(2))
        self.assertIn("derivation", content_types_for_level(5))
        self.assertIn("formula", content_types_for_level(3))


class PreferenceBonusTests(unittest.TestCase):
    def _candidate(self, **kwargs) -> RetrievalCandidate:
        return RetrievalCandidate(
            chunk_id="c1",
            document_id="doc",
            source_file="notes.md",
            page_num=1,
            heading=None,
            content="条件概率",
            **kwargs,
        )

    def test_bonus_is_bounded_and_ignores_unknown_metadata(self):
        candidate = self._candidate(content_type="definition", difficulty=2)
        self.assertEqual(
            _profile_preference_bonus(
                candidate, content_types=["definition"], difficulty_range=(1, 3)
            ),
            1.0,
        )
        self.assertEqual(
            _profile_preference_bonus(
                candidate, content_types=["derivation"], difficulty_range=(1, 3)
            ),
            0.5,
        )
        self.assertEqual(
            _profile_preference_bonus(
                self._candidate(), content_types=["definition"], difficulty_range=(1, 3)
            ),
            0.0,
        )


class DifficultyPreferenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db)
        self.workspace = await create_workspace(self.db, self.user, name="画像", slug="difficulty")

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _point(self, title: str, mastery: float) -> KnowledgePoint:
        point = KnowledgePoint(workspace_id=self.workspace.id, title=title, mastery=mastery)
        self.db.add(point)
        await self.db.flush()
        return point

    async def test_novice_mid_and_advanced_mapping(self):
        service = LearnerProfileService(self.db, self.user.id)

        novice_point = await self._point("入门概念", 0.2)
        novice = await service.difficulty_preference(knowledge_point_ids=[novice_point.id])
        self.assertEqual(novice.level, 2)
        self.assertEqual((novice.min_difficulty, novice.max_difficulty), (1, 3))
        self.assertIn("definition", novice.preferred_content_types)
        self.assertTrue(novice.basis)

        advanced_point = await self._point("熟练主题", 0.95)
        advanced = await service.difficulty_preference(knowledge_point_ids=[advanced_point.id])
        self.assertEqual(advanced.level, 5)
        self.assertEqual((advanced.min_difficulty, advanced.max_difficulty), (4, 5))
        self.assertIn("derivation", advanced.preferred_content_types)

        both = await service.difficulty_preference(
            knowledge_point_ids=[novice_point.id, advanced_point.id]
        )
        self.assertEqual(both.level, 3)
        self.assertEqual((both.min_difficulty, both.max_difficulty), (2, 4))

    async def test_missing_evidence_adds_no_preference(self):
        service = LearnerProfileService(self.db, self.user.id)
        empty = await service.difficulty_preference(workspace_id=self.workspace.id)
        self.assertTrue(empty.is_empty)
        self.assertIsNone(empty.min_difficulty)
        self.assertEqual(empty.preferred_content_types, [])
        self.assertIn("no_knowledge_point_evidence", empty.basis)


class PreferenceRankingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preference_bonus_only_lifts_the_ranking_key(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        db = sessions()
        user = await create_user(db)
        workspace = await create_workspace(db, user, name="偏好", slug="pref-bonus")

        candidates = [
            {"chunk_id": "c1", "content": "条件概率的高级推导", "source_file": "a.md",
             "document_id": "doc", "workspace_id": workspace.id, "score": 0.60,
             "content_type": "derivation", "difficulty": 5},
            {"chunk_id": "c2", "content": "条件概率的定义", "source_file": "a.md",
             "document_id": "doc", "workspace_id": workspace.id, "score": 0.60,
             "content_type": "definition", "difficulty": 1},
        ]

        async def recall(**_kwargs):
            return candidates

        service = HybridRetrievalService(db, recall)
        scope = ResolvedRetrievalScope(
            mode="strict",
            hard_workspace_ids=[workspace.id],
            resolved_by="explicit",
        )
        plain = await service.retrieve_scoped(RetrievalRequest(
            query="条件概率", scope=scope, owned_workspace_ids=[workspace.id],
        ))
        preferred = await service.retrieve_scoped(RetrievalRequest(
            query="条件概率", scope=scope, owned_workspace_ids=[workspace.id],
            preference_content_types=["definition", "concept"],
            difficulty_range=(1, 2),
        ))

        bonus_by_id = {item.chunk_id: item.profile_bonus for item in preferred.items}
        self.assertAlmostEqual(bonus_by_id["c2"], 0.1, places=6)
        self.assertEqual(bonus_by_id["c1"], 0.0)
        # 排序键 = rerank_score + profile_bonus，且偏好只抬高命中项、不改证据分级
        base_by_id = {item.chunk_id: item.rerank_score for item in plain.items}
        for item in preferred.items:
            self.assertAlmostEqual(
                item.rerank_score, base_by_id[item.chunk_id], places=6
            )
        keys = [item.rerank_score + item.profile_bonus for item in preferred.items]
        self.assertEqual(keys, sorted(keys, reverse=True))
        lifted = {
            item.chunk_id: item.rerank_score + item.profile_bonus
            for item in preferred.items
        }
        self.assertGreater(lifted["c2"], base_by_id["c2"])
        self.assertEqual(plain.evidence_status, preferred.evidence_status)
        self.assertEqual(
            {item.chunk_id for item in plain.items},
            {item.chunk_id for item in preferred.items},
        )
        self.assertLessEqual(max(item.profile_bonus for item in preferred.items), 0.1)
        await db.close()
        await engine.dispose()


if __name__ == "__main__":
    unittest.main()
