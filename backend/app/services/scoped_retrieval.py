"""按学习范围检索，并在证据驱动下受预算约束地扩展范围。

设计依据：docs/superpowers/specs/2026-09-18-ai-learning-scope-dynamic-retrieval-design.md §13

契约：
- 证据 `supported` 立即停止；
- 证据 `limited` 只扩展一轮，倾向用现有证据作答；
- 证据 `insufficient` 沿阶梯扩展到上限；
- `expansion_enabled` 为 False（含 strict）时永不扩展；
- 扩展轮数 ≤ `max_rounds`；
- 累计耗时超过 `latency_budget_ms` 时停止扩展，用已有证据作答。

本模块把这段策略从路由里抽出来，便于用假检索器与假时钟做确定性测试。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from app.schemas.scope import ResolvedRetrievalScope, RetrievalScope
from app.services.hybrid_retrieval import HybridRetrievalResult, RetrievalRequest


@dataclass
class ScopedRetrievalOutcome:
    result: HybridRetrievalResult
    scope: ResolvedRetrievalScope
    rounds: int
    trace: list[dict]


async def retrieve_with_expansion(
    *,
    service,
    resolver,
    base_request: RetrievalRequest,
    initial_scope: ResolvedRetrievalScope,
    input_scope: RetrievalScope,
    max_rounds: int,
    latency_budget_ms: int,
    clock=time.monotonic,
) -> ScopedRetrievalOutcome:
    scope = initial_scope
    rounds = 0
    trace: list[dict] = []
    initial_workspaces = list(initial_scope.hard_workspace_ids)
    started_at = clock()
    result: HybridRetrievalResult | None = None

    while True:
        request = replace(
            base_request,
            scope=scope,
            expansion_rounds=rounds,
            expanded_scope=rounds > 0,
            scope_snapshot={
                "input_scope": input_scope.model_dump(),
                "round": rounds,
                "initial_hard_workspace_ids": initial_workspaces,
                "resolved_by": scope.resolved_by,
            },
        )
        result = await service.retrieve_scoped(request)
        trace.append({
            "round": rounds,
            "workspace_ids": list(scope.hard_workspace_ids),
            "document_ids": list(scope.hard_document_ids),
            "evidence_status": result.evidence_status,
        })
        if result.evidence_status == "supported":
            break
        if not scope.expansion_enabled:
            break
        if result.evidence_status == "limited" and rounds >= 1:
            break
        if rounds >= max_rounds:
            break
        if (clock() - started_at) * 1000 >= latency_budget_ms:
            break
        expanded = resolver.expand(scope)
        if expanded is None:
            break
        scope = expanded
        rounds += 1

    assert result is not None  # 循环至少执行一次
    return ScopedRetrievalOutcome(
        result=result, scope=scope, rounds=rounds, trace=trace
    )
