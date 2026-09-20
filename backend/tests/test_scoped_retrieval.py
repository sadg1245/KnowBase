"""扩展预算：轮数、延迟熔断、阶梯耗尽与 strict 契约。"""

import unittest

from app.schemas.scope import ResolvedRetrievalScope, RetrievalScope
from app.services.hybrid_retrieval import RetrievalRequest
from app.services.scoped_retrieval import retrieve_with_expansion


class FakeResult:
    def __init__(self, evidence_status: str, request: RetrievalRequest) -> None:
        self.evidence_status = evidence_status
        self.expansion_rounds = request.expansion_rounds
        self.expanded_scope = request.expanded_scope
        self.scope_snapshot = request.scope_snapshot


class FakeService:
    """按预设证据序列返回结果，并记录每次请求。"""

    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.requests: list[RetrievalRequest] = []

    async def retrieve_scoped(self, request: RetrievalRequest) -> FakeResult:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.statuses) - 1)
        return FakeResult(self.statuses[index], request)


class SteppingResolver:
    """模拟多级扩展阶梯：每一步都返回更大的范围。"""

    def __init__(self, steps: int = 5) -> None:
        self.steps = steps
        self.calls = 0

    def expand(self, scope: ResolvedRetrievalScope) -> ResolvedRetrievalScope | None:
        if self.calls >= self.steps:
            return None
        self.calls += 1
        return scope.model_copy(
            update={
                "hard_workspace_ids": [
                    *scope.hard_workspace_ids,
                    f"ws-step-{self.calls}",
                ],
                "expansion_enabled": True,
            }
        )


class AdvancingClock:
    """每次读取前进固定毫秒数，用于确定性触发延迟熔断。"""

    def __init__(self, step_ms: int = 0) -> None:
        self.step = step_ms / 1000
        self.value = 0.0

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def _scope(**overrides) -> ResolvedRetrievalScope:
    payload = {
        "mode": "smart",
        "hard_workspace_ids": ["ws-1"],
        "expansion_enabled": True,
        "expansion_ceiling": "owned_workspaces",
        "resolution_reason": ["mode_smart"],
    }
    payload.update(overrides)
    return ResolvedRetrievalScope(**payload)


def _request(scope: ResolvedRetrievalScope) -> RetrievalRequest:
    return RetrievalRequest(
        query="什么是向量检索", scope=scope, owned_workspace_ids=["ws-1"]
    )


class ExpansionBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, service, resolver, *, scope=None, max_rounds=2, budget=3000, clock=None):
        resolved = scope or _scope()
        return await retrieve_with_expansion(
            service=service,
            resolver=resolver,
            base_request=_request(resolved),
            initial_scope=resolved,
            input_scope=RetrievalScope(mode="smart", workspace_ids=["ws-1"]),
            max_rounds=max_rounds,
            latency_budget_ms=budget,
            clock=clock or AdvancingClock(),
        )

    async def test_sufficient_evidence_stops_immediately(self):
        service = FakeService(["supported"])

        outcome = await self._run(service, SteppingResolver())

        self.assertEqual(len(service.requests), 1)
        self.assertEqual(outcome.rounds, 0)
        self.assertFalse(outcome.result.expanded_scope)

    async def test_expansion_stops_at_max_rounds(self):
        service = FakeService(["insufficient"])
        resolver = SteppingResolver(steps=5)

        outcome = await self._run(service, resolver, max_rounds=2)

        self.assertEqual(len(service.requests), 3)
        self.assertEqual(outcome.rounds, 2)
        self.assertTrue(outcome.result.expanded_scope)
        self.assertEqual([item["round"] for item in outcome.trace], [0, 1, 2])

    async def test_limited_evidence_expands_only_once(self):
        service = FakeService(["limited", "limited", "limited"])

        outcome = await self._run(
            service, SteppingResolver(steps=5), max_rounds=3
        )

        self.assertEqual(len(service.requests), 2)
        self.assertEqual(outcome.rounds, 1)
        self.assertEqual(outcome.result.evidence_status, "limited")

    async def test_latency_budget_stops_expansion_before_extra_round(self):
        service = FakeService(["insufficient"])

        outcome = await self._run(
            service, SteppingResolver(), max_rounds=5, budget=3000, clock=AdvancingClock(4000)
        )

        self.assertEqual(len(service.requests), 1)
        self.assertEqual(outcome.rounds, 0)

    async def test_scope_without_expansion_never_retries(self):
        service = FakeService(["insufficient"])

        outcome = await self._run(
            service, SteppingResolver(), scope=_scope(expansion_enabled=False)
        )

        self.assertEqual(len(service.requests), 1)
        self.assertEqual(outcome.rounds, 0)

    async def test_exhausted_ladder_stops_expansion(self):
        service = FakeService(["insufficient"])

        outcome = await self._run(service, SteppingResolver(steps=0), max_rounds=3)

        self.assertEqual(len(service.requests), 1)
        self.assertEqual(outcome.rounds, 0)

    async def test_audit_snapshot_records_round_and_initial_scope(self):
        service = FakeService(["insufficient", "supported"])

        outcome = await self._run(service, SteppingResolver())

        first, second = service.requests
        self.assertEqual(first.scope_snapshot["round"], 0)
        self.assertEqual(first.scope_snapshot["initial_hard_workspace_ids"], ["ws-1"])
        self.assertEqual(first.scope_snapshot["input_scope"]["mode"], "smart")
        self.assertEqual(second.scope_snapshot["round"], 1)
        self.assertEqual(second.scope_snapshot["initial_hard_workspace_ids"], ["ws-1"])
        self.assertEqual(len(outcome.trace), 2)
        self.assertEqual(outcome.scope.hard_workspace_ids, ["ws-1", "ws-step-1"])


if __name__ == "__main__":
    unittest.main()
