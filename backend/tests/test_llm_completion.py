"""Contracts for the shared provider-call planning and diagnostics."""

import unittest

from app.config import Settings
from app.services.llm_completion import (
    CompletionContentError,
    call_completion,
    completion_kwargs,
    escalate_max_tokens,
    output_limit,
    plan_max_tokens,
    provider_name,
    response_content,
    supports_json_mode,
)


def choice(content, *, finish_reason=None, reasoning=None):
    message = type("Message", (), {"content": content})()
    if reasoning is not None:
        message.reasoning_content = reasoning
    return type("Choice", (), {"message": message, "finish_reason": finish_reason})()


def response(*choices):
    return type("Response", (), {"choices": list(choices)})()


class ProviderPlanningTests(unittest.TestCase):
    def test_configured_provider_wins_over_the_model_prefix(self):
        settings = Settings.model_construct(DEFAULT_LLM_PROVIDER="DeepSeek", DEFAULT_LLM_MODEL="deepseek-flash")
        self.assertEqual(provider_name(settings, "openai/deepseek-flash"), "deepseek")

    def test_bare_model_names_fall_back_to_openai(self):
        settings = Settings.model_construct(DEFAULT_LLM_PROVIDER="", DEFAULT_LLM_MODEL="")
        self.assertEqual(provider_name(settings, "gpt-4o-mini"), "openai")
        self.assertEqual(provider_name(settings, "ollama/llama3"), "ollama")

    def test_unknown_providers_get_the_conservative_budget(self):
        self.assertEqual(output_limit("ollama"), 8_000)
        self.assertEqual(plan_max_tokens("ollama", 16_000), 8_000)
        self.assertEqual(plan_max_tokens("deepseek", 16_000), 16_000)

    def test_escalation_doubles_but_never_exceeds_the_provider_limit(self):
        self.assertEqual(escalate_max_tokens("deepseek", 16_000), 32_000)
        self.assertEqual(escalate_max_tokens("deepseek", 32_000), 32_000)
        self.assertEqual(escalate_max_tokens("zhipu", 4_000), 4_000)

    def test_json_mode_is_requested_only_for_compatible_providers(self):
        self.assertTrue(supports_json_mode("deepseek"))
        self.assertFalse(supports_json_mode("ollama"))
        deepseek = completion_kwargs(
            model="deepseek/deepseek-flash", api_key="key", api_base="https://api.deepseek.com/v1",
            prompt="p", provider="deepseek", max_tokens=100, json_mode=True,
        )
        self.assertEqual(deepseek["response_format"], {"type": "json_object"})
        ollama = completion_kwargs(
            model="ollama/llama3", api_key="ollama", api_base="http://localhost:11434",
            prompt="p", provider="ollama", max_tokens=100, json_mode=True,
        )
        self.assertNotIn("response_format", ollama)


class ResponseDiagnosticsTests(unittest.TestCase):
    def test_plain_content_is_returned(self):
        self.assertEqual(response_content(response(choice("hello"))), "hello")

    def test_hidden_reasoning_without_an_answer_is_reported(self):
        with self.assertRaises(CompletionContentError) as raised:
            response_content(response(choice("", reasoning="thinking")))
        self.assertIn("hidden reasoning", str(raised.exception))

    def test_empty_response_is_reported(self):
        with self.assertRaises(CompletionContentError) as raised:
            response_content(response(choice("   ")))
        self.assertIn("empty response", str(raised.exception))

    def test_exhausted_budget_points_at_the_reasoning_tokens(self):
        with self.assertRaises(CompletionContentError) as raised:
            response_content(response(choice("", finish_reason="length", reasoning="thinking")))
        self.assertIn("output token budget", str(raised.exception))

    def test_truncated_answer_is_reported_as_incomplete(self):
        with self.assertRaises(CompletionContentError) as raised:
            response_content(response(choice('{"questions": [', finish_reason="length")))
        self.assertIn("incomplete", str(raised.exception))

    def test_invalid_response_shape_is_reported(self):
        with self.assertRaises(CompletionContentError) as raised:
            response_content(object())
        self.assertIn("shape", str(raised.exception))


class CompletionFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_json_mode_is_retried_without_the_parameter(self):
        calls = []

        class BadRequestError(RuntimeError):
            status_code = 400

        async def completion(**kwargs):
            calls.append(kwargs)
            if "response_format" in kwargs:
                raise BadRequestError("response_format is not supported")
            return response(choice("ok"))

        kwargs = {"model": "m", "messages": [], "response_format": {"type": "json_object"}}
        result = await call_completion(completion, kwargs)
        self.assertEqual(response_content(result), "ok")
        self.assertEqual(len(calls), 2)
        self.assertIn("response_format", calls[0])
        self.assertNotIn("response_format", calls[1])

    async def test_other_provider_failures_are_not_retried(self):
        calls = []

        class ServerError(RuntimeError):
            status_code = 500

        async def completion(**kwargs):
            calls.append(kwargs)
            raise ServerError("provider exploded")

        with self.assertRaises(ServerError):
            await call_completion(completion, {"model": "m", "response_format": {"type": "json_object"}})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
