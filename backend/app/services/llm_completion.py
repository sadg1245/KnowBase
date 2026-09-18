"""用户可配置大模型的调用参数与响应诊断。

背景：可选模型里有“先思考再回答”的推理模型（如 DeepSeek 的 flash / pro）。
思维链和最终答案共享同一个 ``max_tokens`` 预算：预算偏小的时候接口仍然返回
200 OK，但 ``message.content`` 为空、或 JSON 被截断在半句话上。调用点如果只看到
``content`` 为空，就会抛出 “response content is empty” 这类无从下手的报错。

这里集中三件事，避免每个调用点各自踩坑：

1. 按提供商给出可接受的输出预算，并在截断后用更大的预算重试一次；
2. 对支持 OpenAI 兼容 JSON 模式的提供商带上 ``response_format``，减少无谓输出
   （实测同一请求的思维链 token 明显下降），不支持时自动降级重发；
3. 把空响应、思维链占满预算、输出被截断翻译成可诊断的错误信息。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable


Completion = Callable[..., Awaitable[Any] | Any]

# 这些提供商的 OpenAI 兼容接口接受 response_format={"type": "json_object"}。
# 注意 dashscope / zhipu 在 resolve_provider_configuration 里会被映射成 openai/ 前缀，
# 所以要按用户配置的 provider 名判断，而不是看模型字符串。
JSON_MODE_PROVIDERS = frozenset({"openai", "deepseek", "dashscope", "qwen", "zhipu", "glm"})

# 各提供商单次回答可接受的 max_tokens 上限。取保守值，超限会被提供商直接拒绝。
PROVIDER_OUTPUT_LIMITS: dict[str, int] = {
    "openai": 16_000,
    "deepseek": 32_000,
    "dashscope": 8_000,
    "qwen": 8_000,
    "zhipu": 4_000,
    "glm": 4_000,
}
DEFAULT_OUTPUT_LIMIT = 8_000

# 推理模型的思维链会让单次调用明显变慢，默认给足超时时间。
DEFAULT_TIMEOUT_SECONDS = 180


class CompletionContentError(ValueError):
    """提供商有响应，但没有可用的回答内容。"""


def provider_name(settings: Any, model: str) -> str:
    """解析生效的提供商名称（用于预算与 JSON 模式判断）。"""
    configured = (getattr(settings, "DEFAULT_LLM_PROVIDER", "") or "").strip().lower()
    if configured:
        return configured
    if "/" not in model:
        return "openai"
    return model.split("/", 1)[0].strip().lower()


def supports_json_mode(provider: str) -> bool:
    return provider in JSON_MODE_PROVIDERS


def output_limit(provider: str) -> int:
    return PROVIDER_OUTPUT_LIMITS.get(provider, DEFAULT_OUTPUT_LIMIT)


def plan_max_tokens(provider: str, desired: int) -> int:
    """把期望预算收敛到提供商可接受的范围内。"""
    return max(1, min(int(desired), output_limit(provider)))


def escalate_max_tokens(provider: str, current: int) -> int:
    """截断后的下一次预算：翻倍，但不超过提供商上限。"""
    limit = output_limit(provider)
    if current >= limit:
        return limit
    return min(int(current) * 2, limit)


def completion_kwargs(
    *,
    model: str,
    api_key: str | None,
    api_base: str | None,
    prompt: str,
    provider: str,
    max_tokens: int,
    json_mode: bool = False,
    temperature: float = 0.2,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """构造一次 litellm 调用参数。"""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if json_mode and supports_json_mode(provider):
        kwargs["response_format"] = {"type": "json_object"}
    return kwargs


async def call_completion(completion: Completion, kwargs: dict[str, Any]) -> Any:
    """执行一次调用；提供商不认 JSON 模式时自动去掉该参数重发。"""
    try:
        response = completion(**kwargs)
        if inspect.isawaitable(response):
            response = await response
        return response
    except Exception as exc:
        if "response_format" not in kwargs or getattr(exc, "status_code", None) != 400:
            raise
        fallback = {key: value for key, value in kwargs.items() if key != "response_format"}
        response = completion(**fallback)
        if inspect.isawaitable(response):
            response = await response
        return response


def response_content(response: Any) -> str:
    """取出回答正文；空响应或截断时抛出可诊断的 CompletionContentError。"""
    try:
        choice = response.choices[0]
        message = choice.message
        content = message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise CompletionContentError("provider response shape is invalid") from exc

    text = content if isinstance(content, str) else ""
    finish_reason = getattr(choice, "finish_reason", None)
    reasoning = getattr(message, "reasoning_content", None)

    if finish_reason == "length":
        if text.strip():
            raise CompletionContentError(
                "provider hit the output token limit before finishing the answer; "
                "the response is incomplete"
            )
        raise CompletionContentError(
            "provider spent the whole output token budget without returning an answer; "
            "reasoning models charge their hidden thinking to the same budget"
        )
    if not text.strip():
        if reasoning:
            raise CompletionContentError("provider returned hidden reasoning without an answer")
        raise CompletionContentError("provider returned an empty response")
    return text
