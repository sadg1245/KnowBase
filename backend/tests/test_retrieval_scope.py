"""学习范围（RetrievalScope）解析语义与多库检索契约。"""

import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.chat import ChatSession, DocumentChunk, RetrievalRun
from app.models.document import Document
from app.models.learning import KnowledgePoint
from app.schemas.scope import RetrievalScope
from app.services.hybrid_retrieval import (
    HybridRetrievalService,
    RetrievalRequest,
    tokenize_for_search,
)
from app.services.scope_resolver import ScopeResolver, legacy_scope, scope_from_session
from tests.support import create_user, create_workspace


class ScopeResolverTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await run_compat_migrations(connection)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, password=None)
        self.ai = await create_workspace(self.db, self.user, name="AI", slug="ws-ai")
        self.nlp = await create_workspace(self.db, self.user, name="NLP", slug="ws-nlp")
        self.document = Document(
            workspace_id=self.ai.id,
            filename="agent.pdf",
            file_path="/tmp/agent.pdf",
            file_type="pdf",
            status="ready",
        )
        self.other_document = Document(
            workspace_id=self.nlp.id,
            filename="word2vec.pdf",
            file_path="/tmp/w2v.pdf",
            file_type="pdf",
            status="ready",
        )
        self.db.add_all([self.document, self.other_document])
        await self.db.flush()
        self.point = KnowledgePoint(
            workspace_id=self.ai.id,
            document_id=self.document.id,
            title="LangGraph State",
        )
        self.other_point = KnowledgePoint(
            workspace_id=self.nlp.id,
            document_id=self.other_document.id,
            title="Word2Vec 训练",
        )
        self.db.add_all([self.point, self.other_point])
        await self.db.flush()
        self.resolver = ScopeResolver(
            self.db,
            user=self.user,
            owned_workspaces=[self.ai.id, self.nlp.id],
        )

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_strict_document_scope_hard_filters_and_never_expands(self):
        resolved = await self.resolver.resolve(
            query="Agent 记忆",
            scope=RetrievalScope(mode="strict", document_ids=[self.document.id]),
        )

        self.assertEqual(resolved.mode, "strict")
        self.assertEqual(resolved.hard_document_ids, [self.document.id])
        self.assertEqual(resolved.hard_workspace_ids, [self.ai.id])
        self.assertFalse(resolved.expansion_enabled)
        self.assertIsNone(self.resolver.expand(resolved))

    async def test_strict_workspace_scope_does_not_leak_other_workspaces(self):
        resolved = await self.resolver.resolve(
            query="Agent 记忆",
            scope=RetrievalScope(mode="strict", workspace_ids=[self.ai.id]),
        )

        self.assertEqual(resolved.hard_workspace_ids, [self.ai.id])
        self.assertEqual(resolved.hard_document_ids, [])
        self.assertFalse(resolved.expansion_enabled)
        self.assertIsNone(self.resolver.expand(resolved))

    async def test_focused_scope_expands_from_documents_to_current_workspace(self):
        resolved = await self.resolver.resolve(
            query="Agent 记忆",
            scope=RetrievalScope(
                mode="focused",
                document_ids=[self.document.id],
                allow_workspace_expansion=True,
            ),
        )

        self.assertEqual(resolved.hard_document_ids, [self.document.id])
        self.assertTrue(resolved.expansion_enabled)
        self.assertEqual(resolved.expansion_ceiling, "workspace")

        expanded = self.resolver.expand(resolved)

        self.assertIsNotNone(expanded)
        self.assertEqual(expanded.hard_document_ids, [])
        self.assertEqual(expanded.hard_workspace_ids, [self.ai.id])
        self.assertEqual(expanded.preferred_document_ids, [self.document.id])
        self.assertFalse(expanded.expansion_enabled)
        self.assertIsNone(self.resolver.expand(expanded))

    async def test_smart_scope_expands_from_workspace_to_all_owned(self):
        resolved = await self.resolver.resolve(
            query="Word2Vec 与 Agent 的关系",
            scope=RetrievalScope(mode="smart", workspace_ids=[self.ai.id]),
        )

        self.assertEqual(resolved.hard_workspace_ids, [self.ai.id])
        self.assertTrue(resolved.expansion_enabled)

        expanded = self.resolver.expand(resolved)

        self.assertIsNotNone(expanded)
        self.assertEqual(set(expanded.hard_workspace_ids), {self.ai.id, self.nlp.id})
        self.assertFalse(expanded.expansion_enabled)

    async def test_smart_scope_without_workspace_uses_all_owned(self):
        resolved = await self.resolver.resolve(
            query="任意问题", scope=RetrievalScope(mode="smart")
        )

        self.assertEqual(set(resolved.hard_workspace_ids), {self.ai.id, self.nlp.id})
        self.assertFalse(resolved.expansion_enabled)

    async def test_smart_scope_single_workspace_has_nothing_to_expand(self):
        single = await create_workspace(self.db, self.user, name="Solo", slug="ws-solo")
        resolver = ScopeResolver(self.db, user=self.user, owned_workspaces=[single.id])

        resolved = await resolver.resolve(
            query="任意问题",
            scope=RetrievalScope(mode="smart", workspace_ids=[single.id]),
        )

        self.assertFalse(resolved.expansion_enabled)
        self.assertIsNone(resolver.expand(resolved))

    async def test_global_scope_searches_every_owned_workspace(self):
        resolved = await self.resolver.resolve(
            query="跨领域比较", scope=RetrievalScope(mode="global")
        )

        self.assertEqual(set(resolved.hard_workspace_ids), {self.ai.id, self.nlp.id})
        self.assertFalse(resolved.expansion_enabled)

    async def test_profile_weak_points_steer_soft_preferences_only(self):
        from app.services.learner_profile import (
            LearnerProfileSnapshot,
            ProfileWeakPoint,
        )

        profile = LearnerProfileSnapshot(
            display_name="学习者",
            preferred_mode="simple",
            goal_summary="日目标 30 分钟",
            weak_points=[
                ProfileWeakPoint(
                    knowledge_point_id=self.other_point.id,
                    title="Word2Vec 训练",
                    mastery=0.2,
                    weakness_score=0.88,
                    reason="最近错题集中",
                )
            ],
        )
        global_scope = RetrievalScope(mode="global")

        plain = await self.resolver.resolve(query="Word2Vec 训练", scope=global_scope)
        steered = await self.resolver.resolve(
            query="Word2Vec 训练", scope=global_scope, profile=profile
        )

        # 成员集合不变（画像不扩权、不缩权），只有顺序与软先验变化
        self.assertEqual(
            set(plain.hard_workspace_ids), set(steered.hard_workspace_ids)
        )
        self.assertEqual(plain.hard_workspace_ids, [self.ai.id, self.nlp.id])
        self.assertEqual(steered.hard_workspace_ids, [self.nlp.id, self.ai.id])
        self.assertEqual(steered.preferred_workspace_id, self.nlp.id)
        self.assertIn(self.other_point.id, steered.preferred_knowledge_point_ids)
        self.assertIn(self.other_document.id, steered.preferred_document_ids)
        self.assertTrue(
            any("profile_weak" in reason for reason in steered.resolution_reason)
        )

    async def test_profile_never_widens_a_strict_scope(self):
        from app.services.learner_profile import (
            LearnerProfileSnapshot,
            ProfileWeakPoint,
        )

        profile = LearnerProfileSnapshot(
            display_name="学习者",
            preferred_mode="simple",
            goal_summary="日目标 30 分钟",
            weak_points=[
                ProfileWeakPoint(
                    knowledge_point_id=self.other_point.id,
                    title="Word2Vec 训练",
                    mastery=0.1,
                    weakness_score=0.95,
                )
            ],
        )

        resolved = await self.resolver.resolve(
            query="Word2Vec 训练",
            scope=RetrievalScope(mode="strict", workspace_ids=[self.ai.id]),
            profile=profile,
        )

        self.assertEqual(resolved.hard_workspace_ids, [self.ai.id])
        self.assertEqual(resolved.preferred_workspace_id, self.ai.id)
        self.assertEqual(resolved.preferred_knowledge_point_ids, [self.other_point.id])
        self.assertFalse(resolved.expansion_enabled)

    async def test_knowledge_point_drives_soft_preference(self):
        resolved = await self.resolver.resolve(
            query="State 是什么",
            scope=RetrievalScope(mode="smart", knowledge_point_ids=[self.point.id]),
        )

        self.assertEqual(resolved.hard_workspace_ids, [self.ai.id])
        self.assertEqual(resolved.preferred_knowledge_point_ids, [self.point.id])
        self.assertIn(self.document.id, resolved.preferred_document_ids)

    async def test_legacy_callers_keep_strict_semantics(self):
        scope = legacy_scope(workspace_id=self.ai.id, document_ids=[self.document.id])

        self.assertEqual(scope.mode, "strict")
        self.assertEqual(scope.document_ids, [self.document.id])

        resolved = await self.resolver.resolve(query="旧调用", scope=scope)
        self.assertFalse(resolved.expansion_enabled)

    async def test_scope_from_session_maps_legacy_columns(self):
        legacy = ChatSession(
            user_id=self.user.id,
            workspace_id=self.ai.id,
            selected_document_ids=[self.document.id],
            scope_mode="strict",
            scope_config={},
        )
        self.db.add(legacy)
        await self.db.flush()

        scope = scope_from_session(legacy)

        self.assertEqual(scope.mode, "strict")
        self.assertEqual(scope.document_ids, [self.document.id])

    async def test_migrated_session_without_scope_config_stays_strict(self):
        migrated = ChatSession(
            user_id=self.user.id,
            workspace_id=self.nlp.id,
            selected_document_ids=[],
            scope_mode="strict",
            scope_config={},
        )
        self.db.add(migrated)
        await self.db.flush()

        scope = scope_from_session(migrated)
        resolved = await self.resolver.resolve(query="迁移后的会话", scope=scope)

        self.assertEqual(resolved.mode, "strict")
        self.assertEqual(resolved.hard_workspace_ids, [self.nlp.id])
        self.assertFalse(resolved.expansion_enabled)


class MultiWorkspaceRetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await run_compat_migrations(connection)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = await create_user(self.db, password=None)
        self.ai = await create_workspace(self.db, self.user, name="AI", slug="mw-ai")
        self.nlp = await create_workspace(self.db, self.user, name="NLP", slug="mw-nlp")
        self.ai_document = Document(
            workspace_id=self.ai.id, filename="agent.pdf", file_path="/tmp/1.pdf",
            file_type="pdf", status="ready",
        )
        self.nlp_document = Document(
            workspace_id=self.nlp.id, filename="w2v.pdf", file_path="/tmp/2.pdf",
            file_type="pdf", status="ready",
        )
        self.db.add_all([self.ai_document, self.nlp_document])
        await self.db.flush()
        self.db.add_all([
            DocumentChunk(
                id="chunk-ai",
                workspace_id=self.ai.id,
                document_id=self.ai_document.id,
                source_file=self.ai_document.filename,
                heading="Agent 记忆",
                chunk_index=0,
                content="混合检索用于 Agent 记忆召回。",
                tokenized_content=tokenize_for_search("混合检索用于 Agent 记忆召回。"),
            ),
            DocumentChunk(
                id="chunk-nlp",
                workspace_id=self.nlp.id,
                document_id=self.nlp_document.id,
                source_file=self.nlp_document.filename,
                heading="Word2Vec 训练",
                chunk_index=0,
                content="混合检索也用于 Word2Vec 语料构建。",
                tokenized_content=tokenize_for_search("混合检索也用于 Word2Vec 语料构建。"),
            ),
        ])
        await self.db.flush()

        async def no_vectors(**_kwargs):
            return []

        self.service = HybridRetrievalService(self.db, no_vectors)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    def _request(self, **overrides) -> RetrievalRequest:
        scope = overrides.pop(
            "scope",
            RetrievalScope(mode="smart", workspace_ids=[self.ai.id, self.nlp.id]),
        )
        from app.schemas.scope import ResolvedRetrievalScope

        resolved = overrides.pop(
            "resolved",
            ResolvedRetrievalScope(
                mode=scope.mode,
                hard_workspace_ids=[self.ai.id, self.nlp.id],
            ),
        )
        return RetrievalRequest(
            query=overrides.pop("query", "混合检索"),
            scope=resolved,
            owned_workspace_ids=[self.ai.id, self.nlp.id],
            **overrides,
        )

    async def test_keyword_recall_spans_owned_workspaces(self):
        result = await self.service.retrieve_scoped(self._request())

        self.assertTrue(result.keyword_succeeded)
        self.assertEqual({item.chunk_id for item in result.items}, {"chunk-ai", "chunk-nlp"})
        self.assertEqual({item.workspace_id for item in result.items}, {self.ai.id, self.nlp.id})
        run = (await self.db.execute(select(RetrievalRun))).scalars().one()
        self.assertEqual(run.scope_mode, "smart")
        self.assertEqual(len(run.scope_resolution["hard_workspace_ids"]), 2)

    async def test_hard_document_filter_is_respected_across_workspaces(self):
        from app.schemas.scope import ResolvedRetrievalScope

        result = await self.service.retrieve_scoped(self._request(resolved=ResolvedRetrievalScope(
            mode="strict",
            hard_workspace_ids=[self.ai.id, self.nlp.id],
            hard_document_ids=[self.nlp_document.id],
        )))

        self.assertEqual([item.chunk_id for item in result.items], ["chunk-nlp"])

    async def test_empty_scope_fails_closed_without_leaking_candidates(self):
        from app.schemas.scope import ResolvedRetrievalScope

        result = await self.service.retrieve_scoped(self._request(resolved=ResolvedRetrievalScope(
            mode="strict", hard_workspace_ids=[]
        )))

        self.assertEqual(result.items, [])
        self.assertEqual(result.evidence_status, "insufficient")
        self.assertIn("范围内没有可访问的知识库", result.degradation_reason)

    async def test_profile_bonus_changes_ranking_only(self):
        plain = await self.service.retrieve_scoped(self._request())
        hinted = await self.service.retrieve_scoped(self._request(profile_hints=["Word2Vec 训练"]))

        self.assertEqual(plain.evidence_status, hinted.evidence_status)
        self.assertEqual(
            {item.chunk_id for item in plain.items},
            {item.chunk_id for item in hinted.items},
        )
        boosted = [item for item in hinted.items if item.profile_bonus > 0]
        self.assertTrue(boosted)
        self.assertEqual(boosted[0].chunk_id, "chunk-nlp")
        self.assertLessEqual(boosted[0].profile_bonus, 0.1)


if __name__ == "__main__":
    unittest.main()
