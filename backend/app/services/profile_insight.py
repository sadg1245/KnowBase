"""AI learning insight: deterministic metrics in, natural language out.

画像洞察与学习报告建议一样遵循“确定性指标 → AI 解释 → AI 建议”的顺序：

- 输入快照只包含由 SQL 算出的事实，模型没有编造学习事实的空间；
- 结果按快照哈希缓存，页面反复打开不会反复调用模型；
- 模型不可用时这只是附加信息，完整画像的确定性结论照常返回。
"""

from __future__ import annotations

import inspect
import json
import time
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.profile import LearnerProfileOverview
from app.services.assessment_ai import _provider
from app.services.llm_completion import (
    call_completion,
    completion_kwargs,
    escalate_max_tokens,
    plan_max_tokens,
    provider_name,
    response_content,
)
from app.services.profile_overview import (
    LearnerProfileOverviewService,
    insight_snapshot,
    snapshot_hash,
)

# 洞察本身很短，但推理模型的思维链与答案共享同一个输出预算。
INSIGHT_MAX_TOKENS = 2_000
CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_MAX_ENTRIES = 256

_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


class ProfileInsightError(RuntimeError):
    """The insight provider failed; the deterministic profile stays authoritative."""


def invalidate_insight_cache(user_id: str) -> None:
    for key in [key for key in _CACHE if key[0] == user_id]:
        _CACHE.pop(key, None)


def _prune_cache(now: float) -> None:
    for key, (stamp, _) in list(_CACHE.items()):
        if now - stamp >= CACHE_TTL_SECONDS:
            _CACHE.pop(key, None)
    if len(_CACHE) <= CACHE_MAX_ENTRIES:
        return
    for key, _ in sorted(_CACHE.items(), key=lambda item: item[1][0])[
        : len(_CACHE) - CACHE_MAX_ENTRIES
    ]:
        _CACHE.pop(key, None)


def _prompt(snapshot: dict) -> str:
    return (
        "你是学习教练。下面是系统用确定性数据算出的学习者画像指标。"
        "请用 2 到 3 句中文总结：当前学习状态、最该补的薄弱点、一个可以立刻执行的下一步。"
        "只能使用给定数字，不得编造未提供的学习事实，不要输出 Markdown 表格，不要罗列项目符号。\n"
        + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    )


async def _default_completion(settings, prompt: str) -> tuple[str, str]:
    import litellm

    model, api_key, api_base = _provider(settings)
    provider = provider_name(settings, model)
    kwargs = completion_kwargs(
        model=model,
        api_key=api_key,
        api_base=api_base,
        prompt=prompt,
        provider=provider,
        max_tokens=plan_max_tokens(provider, INSIGHT_MAX_TOKENS),
    )
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await call_completion(litellm.acompletion, kwargs)
            return response_content(response), model
        except ValueError as exc:
            # 空响应或被截断：多半是推理占满了预算，放大预算再问一次。
            last_error = exc
            if attempt == 0:
                kwargs = {
                    **kwargs,
                    "max_tokens": escalate_max_tokens(provider, int(kwargs["max_tokens"])),
                }
    raise last_error if last_error is not None else ValueError("provider returned no insight")


async def build_profile_for_insight(
    db: AsyncSession, *, now: datetime, user_id: str, workspace_id: str | None = None
) -> LearnerProfileOverview:
    return await LearnerProfileOverviewService(db, user_id).build(
        now=now,
        workspace_id=workspace_id,
        mastery_limit=8,
        weak_limit=3,
        include_children=False,
        include_evidence=False,
    )


def cached_insight(user_id: str, digest: str, *, now: float | None = None) -> dict | None:
    entry = _CACHE.get((user_id, digest))
    if entry is None:
        return None
    stamp, payload = entry
    if (now if now is not None else time.monotonic()) - stamp >= CACHE_TTL_SECONDS:
        _CACHE.pop((user_id, digest), None)
        return None
    return {**payload, "cached": True}


def store_insight(user_id: str, digest: str, payload: dict) -> None:
    now = time.monotonic()
    _prune_cache(now)
    _CACHE[(user_id, digest)] = (now, payload)


async def generate_insight(
    db: AsyncSession,
    settings,
    *,
    now: datetime,
    user_id: str,
    workspace_id: str | None = None,
    completion=None,
) -> dict:
    """Return the AI insight for the current deterministic metrics, cached by hash."""
    profile = await build_profile_for_insight(
        db, now=now, user_id=user_id, workspace_id=workspace_id
    )
    snapshot = insight_snapshot(profile)
    digest = snapshot_hash(snapshot)
    hit = cached_insight(user_id, digest)
    if hit is not None:
        return hit
    if profile.is_empty:
        raise ProfileInsightError("暂无学习记录，画像洞察要等有了学习行为再生成")
    try:
        if completion is not None:
            response = completion(_prompt(snapshot))
            if inspect.isawaitable(response):
                response = await response
            text, model = response
        else:
            text, model = await _default_completion(settings, _prompt(snapshot))
        if not isinstance(text, str) or not text.strip():
            raise ValueError("provider returned an empty insight")
    except Exception as exc:  # provider failure must not look like a profile failure
        raise ProfileInsightError(str(exc)) from exc
    payload = {
        "text": text.strip()[:800],
        "generated_by": "ai",
        "based_on": profile.insight.based_on or ["mastery", "weak_points", "recent_activity"],
        "evidence": profile.insight.evidence,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_hash": digest,
    }
    store_insight(user_id, digest, payload)
    return {**payload, "cached": False}
