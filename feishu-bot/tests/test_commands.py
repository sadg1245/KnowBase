"""Regression tests for Feishu-to-backend request contracts."""

import json
import unittest

import httpx

from bot.commands import CommandRouter


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_uses_post_json_contract(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": []})

        router = CommandRouter("http://backend", FakeRedis())
        await router._http_client.aclose()
        router._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await router._handle_search("hello", "user-1")
        await router.close()

        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"], {"query": "hello"})

    async def test_chat_parses_sse_contract(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(json.loads(request.content))
            body = (
                'data: {"token":"Hi"}\n\n'
                'data: {"sources":[]}\n\n'
                'data: {"done":true,"confidence":0.8}\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

        router = CommandRouter("http://backend", FakeRedis())
        await router._http_client.aclose()
        router._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        card = await router._handle_ask("hello", "user-1")
        await router.close()

        self.assertIn("Hi", json.dumps(card, ensure_ascii=False))
        self.assertEqual(captured["question"], "hello")
        # 服务身份在服务端解析；飞书 open_id 不再作为 chat 授权依据。
        self.assertNotIn("user_id", captured)

    async def test_service_token_is_sent_as_the_bound_identity_header(self):
        router = CommandRouter("http://backend", FakeRedis(), access_token="service-secret")
        try:
            self.assertEqual(
                router._http_client.headers.get("X-KnowBase-Service-Token"),
                "service-secret",
            )
        finally:
            await router.close()


if __name__ == "__main__":
    unittest.main()
