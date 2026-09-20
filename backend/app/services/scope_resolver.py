"""把「学习范围」解析成可执行检索范围。

设计依据：docs/superpowers/specs/2026-09-18-ai-learning-scope-dynamic-retrieval-design.md

职责边界：
- 只决定「去哪里找」，不检索、不排序、不判断证据。
- 只在当前用户拥有的知识库内解析（所有权收敛见 `resolve_owned_scope`）。
- `strict` 永不扩展，这是不可破坏契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chat import ChatSession
from app.models.learning import KnowledgePoint
from app.models.user import User
from app.schemas.scope import ResolvedRetrievalScope, RetrievalScope
from app.services.learner_profile import LearnerProfileSnapshot
from app.services.ownership import owned_workspace_ids, resolve_owned_scope


@dataclass
class ProfilePreferences:
    """画像对「软先验」的影响结果；永不含硬过滤。"""

    knowledge_point_ids: list[str] = field(default_factory=list)
    workspace_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.knowledge_point_ids or self.workspace_ids or self.document_ids)


def legacy_scope(*, workspace_id: str | None, document_ids: list[str] | None) -> RetrievalScope:
    """旧调用方（workspace_id + selected_document_ids）的等价范围。

    迁移前的行为 = 单知识库 + 可选文件过滤 + 从不扩展，因此等价于 `strict`。
    """
    documents = [str(value) for value in (document_ids or []) if str(value).strip()]
    if documents:
        return RetrievalScope(mode="strict", document_ids=documents)
    return RetrievalScope(mode="strict", workspace_ids=[workspace_id] if workspace_id else [])


def scope_from_session(session: ChatSession | None) -> RetrievalScope | None:
    """从会话读取范围，并用兼容字段补齐缺失部分。"""
    if session is None:
        return None
    scope = RetrievalScope.from_config(
        getattr(session, "scope_mode", None), getattr(session, "scope_config", None)
    )
    if not scope.document_ids:
        scope.document_ids = [
            str(value) for value in (getattr(session, "selected_document_ids", None) or [])
        ]
    if (
        not scope.workspace_ids
        and getattr(session, "workspace_id", None)
        and scope.mode != "global"
    ):
        scope.workspace_ids = [session.workspace_id]
    return scope


def _dedupe(values) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


class ScopeResolver:
    """按 Scope Mode 计算实际检索范围。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        user: User,
        owned_workspaces: list[str] | None = None,
    ) -> None:
        self.db = db
        self.user = user
        self._owned_workspaces = list(owned_workspaces or [])

    @property
    def owned_workspaces(self) -> list[str]:
        return self._owned_workspaces

    async def _ensure_owned(self) -> list[str]:
        if not self._owned_workspaces:
            self._owned_workspaces = await owned_workspace_ids(self.db, self.user)
        return self._owned_workspaces

    async def profile_preferences(
        self, profile: LearnerProfileSnapshot | None, *, owned: set[str]
    ) -> ProfilePreferences:
        """把画像薄弱点翻译成软先验。

        `LearnerProfileSnapshot.weak_points` 已经按「薄弱 + 与当前问题相关」筛过，
        因此这里不重复做相关性判断。输出只进入 preferred_* 与同集合内排序，
        绝不改变 hard_workspace_ids / hard_document_ids 的成员。
        """
        if profile is None or not profile.weak_points:
            return ProfilePreferences()

        ordered_points: list[str] = []
        for point in sorted(
            profile.weak_points, key=lambda item: -float(item.weakness_score or 0.0)
        ):
            point_id = str(point.knowledge_point_id or "").strip()
            if point_id and point_id not in ordered_points:
                ordered_points.append(point_id)
        if not ordered_points:
            return ProfilePreferences()
        ordered_points = ordered_points[: settings.PROFILE_MAX_KNOWLEDGE_POINTS]

        rows = (await self.db.execute(
            select(
                KnowledgePoint.id,
                KnowledgePoint.workspace_id,
                KnowledgePoint.document_id,
            ).where(KnowledgePoint.id.in_(ordered_points))
        )).all()
        located = {row[0]: (row[1], row[2]) for row in rows}

        counts: dict[str, int] = {}
        workspaces: list[str] = []
        documents: list[str] = []
        for point_id in ordered_points:
            workspace_id, document_id = located.get(point_id, (None, None))
            if not workspace_id or workspace_id not in owned:
                continue
            counts[workspace_id] = counts.get(workspace_id, 0) + 1
            if workspace_id not in workspaces:
                workspaces.append(workspace_id)
            if document_id and document_id not in documents:
                documents.append(document_id)
        # 薄弱点更集中的知识库排前面；list.sort 稳定，原顺序作为次键
        workspaces.sort(key=lambda workspace_id: -counts.get(workspace_id, 0))

        reasons: list[str] = []
        if workspaces:
            reasons.append(f"profile_weak_workspaces={'、'.join(workspaces[:2])}")
        if documents:
            reasons.append(f"profile_weak_documents={len(documents)}")
        return ProfilePreferences(
            knowledge_point_ids=ordered_points,
            workspace_ids=workspaces,
            document_ids=documents,
            reasons=reasons,
        )

    def _with_profile(
        self,
        resolved: ResolvedRetrievalScope,
        preferences: ProfilePreferences,
    ) -> ResolvedRetrievalScope:
        """叠加画像软先验：只动 preferred_* 与同集合内的顺序。"""
        if preferences.is_empty:
            return resolved
        hard = set(resolved.hard_workspace_ids)
        promoted = [
            workspace_id
            for workspace_id in preferences.workspace_ids
            if workspace_id in hard
        ]
        ordered_hard = promoted + [
            workspace_id
            for workspace_id in resolved.hard_workspace_ids
            if workspace_id not in promoted
        ]
        return resolved.model_copy(
            update={
                "hard_workspace_ids": ordered_hard,
                "preferred_workspace_id": promoted[0] if promoted else resolved.preferred_workspace_id,
                "preferred_document_ids": self._merge_unique([
                    *resolved.preferred_document_ids,
                    *preferences.document_ids,
                ]),
                "preferred_knowledge_point_ids": self._merge_unique([
                    *resolved.preferred_knowledge_point_ids,
                    *preferences.knowledge_point_ids,
                ]),
                "resolution_reason": [
                    *resolved.resolution_reason,
                    *preferences.reasons,
                ],
            }
        )

    async def resolve(
        self,
        *,
        query: str,
        scope: RetrievalScope,
        session: ChatSession | None = None,
        workspace_id: str | None = None,
        profile: LearnerProfileSnapshot | None = None,
    ) -> ResolvedRetrievalScope:
        owned = await self._ensure_owned()
        owned_set = set(owned)

        requested_workspaces = _dedupe(scope.workspace_ids) or (
            [workspace_id] if workspace_id else []
        )
        owned_scope = await resolve_owned_scope(
            self.db,
            self.user,
            workspace_ids=requested_workspaces,
            document_ids=scope.document_ids,
            knowledge_point_ids=scope.knowledge_point_ids,
        )

        workspaces = owned_scope.workspace_ids
        documents = owned_scope.document_ids
        document_workspaces = owned_scope.document_workspace_ids
        points = owned_scope.knowledge_point_ids
        dropped = list(owned_scope.dropped_ids)
        preferences = await self.profile_preferences(profile, owned=owned_set)

        # 知识点驱动的软先验（v1）：知识点 → 文档 / 知识库
        point_documents: list[str] = []
        point_document_workspaces: dict[str, str] = {}
        for point_id in points:
            document_id = owned_scope.knowledge_point_document_ids.get(point_id)
            workspace_of_point = owned_scope.knowledge_point_workspace_ids.get(point_id)
            if document_id and workspace_of_point:
                point_document_workspaces.setdefault(document_id, workspace_of_point)
                if document_id not in point_documents:
                    point_documents.append(document_id)
        point_workspaces = sorted(set(point_document_workspaces.values())) or sorted(
            {
                value
                for value in owned_scope.knowledge_point_workspace_ids.values()
                if value
            }
        )
        document_workspaces = {**point_document_workspaces, **document_workspaces}

        resolved_by: str = "explicit" if (
            scope.workspace_ids or scope.document_ids or scope.knowledge_point_ids
        ) else ("session" if session is not None else "fallback")
        reasons: list[str] = [f"mode_{scope.mode}"]

        if scope.mode == "strict":
            if not documents and not workspaces and point_documents:
                documents = list(point_documents)
                workspaces = list(point_workspaces)
            if documents:
                allowed = (set(workspaces) & owned_set) if workspaces else owned_set
                documents = [value for value in documents if document_workspaces[value] in allowed]
                hard_workspaces = sorted({document_workspaces[value] for value in documents})
            elif workspaces:
                hard_workspaces = list(workspaces)
            else:
                hard_workspaces = self._fallback_workspaces(
                    workspace_id, session, owned_set
                )
                if hard_workspaces:
                    resolved_by = "fallback"
                    reasons.append("strict_scope_missing_fallback_to_current_workspace")
            # strict 下没有「当前知识库」信号时，用范围内唯一/首个知识库作为偏好，
            # 保证排序与审计都有确定答案
            preferred_workspace = self._first_owned(
                [workspace_id, getattr(session, "workspace_id", None)], owned_set
            ) or (hard_workspaces[0] if hard_workspaces else None)
            reasons.append("strict_never_expands")
            resolved = ResolvedRetrievalScope(
                mode="strict",
                hard_workspace_ids=hard_workspaces,
                hard_document_ids=list(documents),
                preferred_workspace_id=preferred_workspace,
                resolved_by=resolved_by,
                resolution_reason=reasons,
                dropped_ids=dropped,
            )
            return self._with_profile(resolved, preferences)

        if scope.mode == "focused":
            ceiling = list(workspaces) or sorted(
                {document_workspaces[value] for value in documents}
            ) or self._fallback_workspaces(workspace_id, session, owned_set)
            ceiling_set = set(ceiling)
            if documents and ceiling_set:
                documents = [value for value in documents if document_workspaces[value] in ceiling_set]
            round_workspaces = (
                sorted({document_workspaces[value] for value in documents})
                if documents
                else list(ceiling)
            )
            expansion_enabled = bool(
                scope.allow_workspace_expansion and ceiling and documents
            )
            reasons.append(
                "focused_starts_from_documents" if documents else "focused_starts_from_workspace"
            )
            resolved = ResolvedRetrievalScope(
                mode="focused",
                hard_workspace_ids=round_workspaces,
                hard_document_ids=list(documents),
                preferred_workspace_id=self._first_owned(ceiling, owned_set),
                expansion_enabled=expansion_enabled,
                expansion_ceiling="workspace",
                expansion_workspace_ids=list(ceiling),
                resolved_by=resolved_by,
                resolution_reason=reasons,
                dropped_ids=dropped,
            )
            return self._with_profile(resolved, preferences)

        if scope.mode == "global":
            reasons.append("global_searches_all_owned_workspaces")
            resolved = ResolvedRetrievalScope(
                mode="global",
                hard_workspace_ids=list(owned),
                preferred_workspace_id=self._first_owned([workspace_id], owned_set),
                preferred_document_ids=self._merge_unique(point_documents),
                preferred_knowledge_point_ids=list(points),
                expansion_enabled=False,
                expansion_ceiling="owned_workspaces",
                resolved_by=resolved_by,
                resolution_reason=reasons,
                dropped_ids=dropped,
            )
            return self._with_profile(resolved, preferences)

        # smart
        start = list(workspaces) or self._fallback_workspaces(workspace_id, session, owned_set)
        if not start:
            start = list(point_workspaces)
        if not start:
            reasons.append("smart_scope_without_workspace_falls_back_to_global")
        expansion_enabled = bool(start) and set(start) != owned_set
        reasons.extend(self._smart_reasons(start, profile))
        resolved = ResolvedRetrievalScope(
            mode="smart",
            hard_workspace_ids=list(start) or list(owned),
            preferred_workspace_id=self._first_owned(start, owned_set),
            preferred_document_ids=self._merge_unique([*documents, *point_documents]),
            preferred_knowledge_point_ids=list(points),
            expansion_enabled=expansion_enabled,
            expansion_ceiling="owned_workspaces",
            expansion_workspace_ids=list(owned),
            resolved_by=resolved_by,
            resolution_reason=reasons,
            dropped_ids=dropped,
        )
        return self._with_profile(resolved, preferences)

    def expand(self, resolved: ResolvedRetrievalScope) -> ResolvedRetrievalScope | None:
        """沿扩展阶梯推进一步；返回 None 表示已到上限。"""
        if not resolved.expansion_enabled:
            return None

        if resolved.mode == "focused" and resolved.hard_document_ids:
            ceiling = resolved.expansion_workspace_ids or resolved.hard_workspace_ids
            return resolved.model_copy(
                update={
                    "hard_workspace_ids": list(ceiling),
                    "hard_document_ids": [],
                    "preferred_document_ids": list(resolved.hard_document_ids),
                    "expansion_enabled": False,
                    "resolution_reason": [
                        *resolved.resolution_reason,
                        "focused_scope_expanded_to_current_workspace",
                    ],
                }
            )

        if resolved.mode == "smart":
            target = resolved.expansion_workspace_ids or self._owned_workspaces
            if set(target).issubset(set(resolved.hard_workspace_ids)):
                return None
            return resolved.model_copy(
                update={
                    "hard_workspace_ids": list(target),
                    "expansion_enabled": False,
                    "resolution_reason": [
                        *resolved.resolution_reason,
                        "smart_scope_expanded_to_owned_workspaces",
                    ],
                }
            )

        return None

    @staticmethod
    def _first_owned(candidates, owned: set[str]) -> str | None:
        for value in candidates:
            if value and value in owned:
                return value
        return None

    @staticmethod
    def _merge_unique(values) -> list[str]:
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _fallback_workspaces(
        workspace_id: str | None, session: ChatSession | None, owned: set[str]
    ) -> list[str]:
        for candidate in (workspace_id, getattr(session, "workspace_id", None)):
            if candidate and candidate in owned:
                return [candidate]
        return []

    @staticmethod
    def _smart_reasons(
        start: list[str], profile: LearnerProfileSnapshot | None
    ) -> list[str]:
        reasons = [f"smart_start_workspaces={len(start)}"]
        if profile is not None and profile.weak_points:
            titles = [point.title for point in profile.weak_points[:2] if point.title]
            if titles:
                reasons.append(f"profile_weak_points={'、'.join(titles)}")
        return reasons
