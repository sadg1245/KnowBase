"""Retrieval scope contracts for AI learning sessions.

设计依据：docs/superpowers/specs/2026-09-18-ai-learning-scope-dynamic-retrieval-design.md

用户可见的概念只有「学习范围」；本模块是它的内部表示。
`RetrievalScope` 描述用户意图，`ResolvedRetrievalScope` 是每次请求实时计算出的
可执行范围（含所有权收敛结果），检索层只接受后者。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ScopeMode = Literal["strict", "focused", "smart", "global"]
ExpansionCeiling = Literal["none", "workspace", "owned_workspaces"]


class RetrievalScope(BaseModel):
    """用户视角的范围描述，持久化在 `chat_sessions.scope_config`。"""

    mode: ScopeMode = "smart"

    workspace_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)

    # 仅 focused 生效：是否允许从「优先文件」扩展到「当前知识库」
    allow_workspace_expansion: bool = False

    def config_payload(self) -> dict:
        """只保留可持久化的用户语义，不写入解析结果。"""
        return {
            "workspace_ids": list(self.workspace_ids),
            "document_ids": list(self.document_ids),
            "knowledge_point_ids": list(self.knowledge_point_ids),
            "allow_workspace_expansion": bool(self.allow_workspace_expansion),
        }

    @classmethod
    def from_config(cls, mode: str | None, config: dict | None) -> "RetrievalScope":
        payload = config or {}
        return cls(
            mode=mode if mode in ("strict", "focused", "smart", "global") else "strict",
            workspace_ids=_string_list(payload.get("workspace_ids")),
            document_ids=_string_list(payload.get("document_ids")),
            knowledge_point_ids=_string_list(payload.get("knowledge_point_ids")),
            allow_workspace_expansion=bool(payload.get("allow_workspace_expansion", False)),
        )


class ResolvedRetrievalScope(BaseModel):
    """可直接驱动检索的可执行范围。

    不变式：`hard_workspace_ids` 始终是**已收敛到当前用户所有权**的具体知识库集合。
    空列表表示该用户没有任何知识库（fail-closed），检索层不得把空列表解释为「不过滤」。
    """

    mode: ScopeMode

    hard_workspace_ids: list[str] = Field(default_factory=list)
    hard_document_ids: list[str] = Field(default_factory=list)

    # 软优先：只影响排序权重，不排除任何候选
    preferred_workspace_id: str | None = None
    preferred_document_ids: list[str] = Field(default_factory=list)
    preferred_knowledge_point_ids: list[str] = Field(default_factory=list)

    # 扩展控制
    expansion_enabled: bool = False
    expansion_ceiling: ExpansionCeiling = "none"
    # 扩展到上限后允许使用的知识库集合（仅 focused 使用，见 scope_resolver.expand）
    expansion_workspace_ids: list[str] = Field(default_factory=list)

    # 审计
    resolved_by: Literal["explicit", "session", "fallback"] = "explicit"
    resolution_reason: list[str] = Field(default_factory=list)
    dropped_ids: list[str] = Field(default_factory=list)

    def audit_snapshot(self) -> dict:
        return {
            "mode": self.mode,
            "hard_workspace_ids": list(self.hard_workspace_ids),
            "hard_document_ids": list(self.hard_document_ids),
            "preferred_workspace_id": self.preferred_workspace_id,
            "preferred_document_ids": list(self.preferred_document_ids),
            "preferred_knowledge_point_ids": list(self.preferred_knowledge_point_ids),
            "expansion_enabled": self.expansion_enabled,
            "expansion_ceiling": self.expansion_ceiling,
            "resolved_by": self.resolved_by,
            "resolution_reason": list(self.resolution_reason),
            "dropped_ids": list(self.dropped_ids),
        }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    seen: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in seen:
            seen.append(text)
    return seen
