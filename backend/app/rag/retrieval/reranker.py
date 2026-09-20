"""Reranker 三态（§18.3）：none / local / api，超时或异常一律降级并留痕。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from loguru import logger

RERANK_MODES = frozenset({"none", "local", "api"})


@dataclass
class RerankOutcome:
    items: list
    mode: str
    degraded_reason: str | None = None
    reordered: bool = False
    notes: list[str] = field(default_factory=list)


class Reranker:
    """`local` 沿用混合检索已算好的分数；`api` 需要一个打分回调。"""

    def __init__(
        self,
        *,
        mode: str = "local",
        scorer: Callable[..., Sequence[float] | Awaitable[Sequence[float]]] | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.mode = mode if mode in RERANK_MODES else "none"
        self.scorer = scorer
        self.timeout_seconds = timeout_seconds

    async def rerank(self, query: str, items: list) -> RerankOutcome:
        if self.mode == "api" and self.scorer is None:
            return RerankOutcome(items, self.mode, "reranker_unavailable")
        if self.mode == "none" or self.scorer is None or not items:
            return RerankOutcome(items, self.mode)
        try:
            scored = self.scorer(query, [getattr(item, "content", "") for item in items])
            if inspect.isawaitable(scored):
                scored = await asyncio.wait_for(scored, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("Reranker timed out after {}s; keeping hybrid order.", self.timeout_seconds)
            return RerankOutcome(items, self.mode, "reranker_timeout")
        except Exception as exc:
            logger.warning("Reranker failed ({}); keeping hybrid order.", exc)
            return RerankOutcome(items, self.mode, "reranker_unavailable")

        scores = list(scored or [])
        if len(scores) != len(items):
            return RerankOutcome(items, self.mode, "reranker_score_mismatch")
        ranked = [
            item for _, item in sorted(zip(scores, items), key=lambda pair: -float(pair[0]))
        ]
        return RerankOutcome(ranked, self.mode, None, reordered=True)

