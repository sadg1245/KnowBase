"""
命令路由器，用于解析和分发机器人命令。
"""

from __future__ import annotations

import json
from typing import Optional

import httpx
import redis.asyncio as redis
from loguru import logger

from bot.cards import (
    build_answer_card,
    build_error_card,
    build_help_card,
    build_not_found_card,
    build_status_card,
)


class CommandRouter:
    """将用户消息解析为命令并路由到对应的处理函数。"""

    # 支持的命令
    COMMANDS = {"search", "status", "ws", "help", "feedback", "today", "review", "mode"}

    def __init__(self, backend_url: str, redis_client: redis.Redis, access_token: str = ""):
        self._backend_url = backend_url.rstrip("/")
        self._redis = redis_client
        headers = {"X-KnowBase-Service-Token": access_token} if access_token else {}
        self._http_client = httpx.AsyncClient(timeout=60.0, headers=headers)

    def parse_command(self, text: str) -> tuple[str, str]:
        """
        将用户消息解析为 (command_name, args)。

        命令以 '/' 前缀开头。如果没有前缀，则命令为 "ask"
        （默认知识库查询）。

        Returns:
            (command_name, args_string) 元组。
        """
        text = text.strip()

        if not text.startswith("/"):
            return ("ask", text)

        parts = text.split(maxsplit=1)
        command = parts[0][1:].lower()  # 移除 '/' 前缀
        args = parts[1] if len(parts) > 1 else ""

        if command not in self.COMMANDS:
            # 将未知命令视为普通查询
            logger.warning(f"Unknown command '/{command}', treating as query")
            return ("ask", text)

        return (command, args)

    async def route_command(
        self,
        command: str,
        args: str,
        user_id: str,
        context: Optional[dict] = None,
    ) -> dict:
        """
        将已解析的命令路由到对应的处理函数。

        Args:
            command: 命令名称 (ask, search, status, ws, help)。
            args: 参数字符串。
            user_id: 飞书用户的 open_id。
            context: 可选的上下文字典（如 chat_id、message_id）。

        Returns:
            用于发送回复的飞书卡片字典。
        """
        context = context or {}

        try:
            if command == "ask":
                return await self._handle_ask(args, user_id)
            elif command == "search":
                return await self._handle_search(args, user_id)
            elif command == "status":
                return await self._handle_status(user_id)
            elif command == "ws":
                return await self._handle_workspace(args, user_id)
            elif command == "help":
                return build_help_card()
            elif command == "feedback":
                return await self._handle_feedback(args, user_id)
            elif command == "today":
                return await self._handle_today(user_id)
            elif command == "review":
                return await self._handle_review(args, user_id)
            elif command == "mode":
                return await self._handle_mode(args, user_id)
            else:
                return build_error_card(f"\u672a\u77e5\u547d\u4ee4: {command}")
        except httpx.ConnectError as exc:
            logger.error(f"Cannot connect to backend at {self._backend_url}: {exc}")
            return build_error_card(
                "\u65e0\u6cd5\u8fde\u63a5\u5230 KnowBase \u540e\u7aef\u670d\u52a1\uff0c"
                "\u8bf7\u786e\u8ba4\u670d\u52a1\u662f\u5426\u5df2\u542f\u52a8\u3002"
            )
        except httpx.TimeoutException as exc:
            logger.error(f"Backend request timed out: {exc}")
            return build_error_card(
                "\u540e\u7aef\u670d\u52a1\u54cd\u5e94\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
            )
        except Exception as exc:
            logger.exception(f"Error handling command '{command}': {exc}")
            return build_error_card(str(exc))

    async def _get_workspace(self, user_id: str) -> Optional[str]:
        """从 Redis 获取用户当前活跃的工作区。"""
        try:
            ws = await self._redis.get(f"knowbase:ws:{user_id}")
            if ws:
                return ws.decode("utf-8") if isinstance(ws, bytes) else ws
        except Exception as exc:
            logger.warning(f"Failed to read workspace from Redis: {exc}")
        return None

    async def _handle_ask(self, query: str, user_id: str) -> dict:
        """
        处理知识库查询，调用后端 /api/chat 接口。
        """
        if not query.strip():
            return build_help_card()

        workspace = await self._get_workspace(user_id)

        mode = await self._redis.get(f"knowbase:mode:{user_id}")
        if isinstance(mode, bytes):
            mode = mode.decode("utf-8")
        payload: dict = {"question": query, "user_id": user_id, "mode": mode or "simple", "strict_sources": True}
        if workspace:
            payload["workspace_id"] = workspace

        logger.info(f"Querying backend /api/chat: query='{query[:80]}...'")

        answer = ""
        sources: list[dict] = []
        confidence = 0.0
        async with self._http_client.stream(
            "POST", f"{self._backend_url}/api/chat", json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                if "error" in event:
                    raise RuntimeError(event["error"])
                if "token" in event:
                    answer += event["token"]
                if "full_text" in event:
                    answer = event["full_text"]
                if "sources" in event:
                    sources = event["sources"]
                if event.get("done") and "confidence" in event:
                    confidence = event["confidence"]

        if not answer:
            return build_not_found_card(query)

        return build_answer_card(answer, sources, confidence)

    async def _handle_search(self, query: str, user_id: str) -> dict:
        """
        处理搜索命令，调用后端 /api/search 接口。
        """
        if not query.strip():
            return build_error_card(
                "\u8bf7\u63d0\u4f9b\u641c\u7d22\u5173\u952e\u8bcd\u3002"
                "\u7528\u6cd5\uff1a`/search \u5173\u952e\u8bcd`"
            )

        workspace = await self._get_workspace(user_id)

        payload: dict = {"query": query}
        if workspace:
            payload["workspace_id"] = workspace

        logger.info(f"Searching backend /api/search: q='{query[:80]}...'")

        response = await self._http_client.post(
            f"{self._backend_url}/api/search",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])

        if not results:
            return build_not_found_card(query)

        # 构建搜索结果卡片
        result_lines = []
        for i, r in enumerate(results[:5], 1):
            file_name = r.get("source_file", "unknown")
            snippet = r.get("content", "")
            score = r.get("score", 0)
            page = r.get("page_num")

            header = f"**{i}. {file_name}**"
            if page:
                header += f" (Page {page})"
            if score:
                header += f" \u2014 \u76f8\u5173\u5ea6: {score:.0%}"
            result_lines.append(header)

            if snippet:
                short = snippet[:200] + ("..." if len(snippet) > 200 else "")
                result_lines.append(f"> {short}")
            result_lines.append("")

        content = "\n".join(result_lines)

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"\U0001f50d \u641c\u7d22\u7ed3\u679c\uff1a{query}",
                },
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content,
                    },
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "lark_md",
                            "content": (
                                f"\u5171\u627e\u5230 {len(results)} "
                                f"\u6761\u7ed3\u679c\uff0c\u663e\u793a\u524d "
                                f"{min(len(results), 5)} \u6761"
                            ),
                        },
                    ],
                },
            ],
        }

        return card

    async def _handle_status(self, user_id: str) -> dict:
        """
        处理 /status 命令，调用后端 /api/settings/system 接口。
        """
        logger.info("Querying backend /api/settings/system for status")

        response = await self._http_client.get(
            f"{self._backend_url}/api/settings/system",
        )
        response.raise_for_status()
        data = response.json()

        stats = {
            "workspace_count": data.get("workspace_count", 0),
            "document_count": data.get("document_count", 0),
            "total_chunks": data.get("total_chunks", 0),
            "last_updated": data.get("last_updated", "N/A"),
        }

        return build_status_card(stats)

    async def _handle_workspace(self, args: str, user_id: str) -> dict:
        """
        处理 /ws 命令，用于切换工作区。
        将用户选择的工作区存储在 Redis 中。
        """
        if not args.strip():
            # 显示当前工作区
            current = await self._get_workspace(user_id)
            if current:
                msg = (
                    f"\u5f53\u524d\u5de5\u4f5c\u533a\uff1a**{current}**\n\n"
                    "\u4f7f\u7528 `/ws \u5de5\u4f5c\u533a\u540d\u79f0` "
                    "\u5207\u6362\u5de5\u4f5c\u533a"
                )
            else:
                msg = (
                    "\u672a\u9009\u62e9\u5de5\u4f5c\u533a\uff0c\u5f53\u524d\u4f7f\u7528\u9ed8\u8ba4\u5de5\u4f5c\u533a\u3002\n\n"
                    "\u4f7f\u7528 `/ws \u5de5\u4f5c\u533a\u540d\u79f0` "
                    "\u5207\u6362\u5de5\u4f5c\u533a"
                )

            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "\U0001f4c1 \u5de5\u4f5c\u533a",
                    },
                    "template": "orange",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": msg},
                    },
                ],
            }
            return card

        # 切换工作区：后端检索使用 UUID，因此先按 ID 或名称解析。
        workspace_name = args.strip()

        try:
            response = await self._http_client.get(f"{self._backend_url}/api/workspaces")
            response.raise_for_status()
            workspaces = response.json()
            selected = next(
                (
                    ws for ws in workspaces
                    if ws.get("id") == workspace_name or ws.get("name") == workspace_name
                ),
                None,
            )
            if selected is None:
                return build_error_card(f"未找到工作区：{workspace_name}")

            await self._redis.set(
                f"knowbase:ws:{user_id}",
                selected["id"],
                ex=86400 * 7,  # 7 天后过期
            )
            logger.info(f"User {user_id} switched workspace to '{selected['id']}'")

            card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": "\u2705 \u5de5\u4f5c\u533a\u5df2\u5207\u6362",
                    },
                    "template": "green",
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": (
                                f"\u5df2\u5207\u6362\u5230\u5de5\u4f5c\u533a\uff1a"
                                f"**{selected['name']}**\n\n"
                                "\u540e\u7eed\u7684\u67e5\u8be2\u5c06\u5728\u6b64\u5de5\u4f5c\u533a\u4e2d\u8fdb\u884c\u3002"
                            ),
                        },
                    },
                ],
            }
            return card

        except Exception as exc:
            logger.error(f"Failed to set workspace in Redis: {exc}")
            return build_error_card(
                f"\u5207\u6362\u5de5\u4f5c\u533a\u5931\u8d25\uff1a{exc}"
            )

    async def _handle_feedback(self, args: str, user_id: str) -> dict:
        """处理反馈命令（MVP 占位实现）。"""
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "\U0001f4dd \u53cd\u9988\u5df2\u6536\u5230",
                },
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "\u611f\u8c22\u60a8\u7684\u53cd\u9988\uff01"
                            "\u6211\u4eec\u4f1a\u4e0d\u65ad\u6539\u8fdb\u77e5\u8bc6\u5e93\u7684\u56de\u7b54\u8d28\u91cf\u3002"
                        ),
                    },
                },
            ],
        }
        return card

    @staticmethod
    def _learning_card(title: str, content: str, template: str = "turquoise") -> dict:
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
            "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
        }

    async def _handle_today(self, user_id: str) -> dict:
        response = await self._http_client.get(f"{self._backend_url}/api/learning/dashboard")
        response.raise_for_status()
        data = response.json()
        stats = data.get("stats", {})
        tasks = data.get("today_tasks", [])
        lines = [
            f"**今日已学习：** {stats.get('today_minutes', 0)} 分钟",
            f"**连续学习：** {stats.get('streak_days', 0)} 天",
            "",
            "**今天可以完成：**",
        ]
        lines.extend(f"• {item['title']}：{item.get('count', 0)} 项" for item in tasks)
        lines.append("\n发送 `/review` 开始复习，或直接向我提问。")
        return self._learning_card("📖 今日学习", "\n".join(lines))

    async def _handle_review(self, args: str, user_id: str) -> dict:
        ratings = {"1": "忘记了", "2": "有点模糊", "3": "记住了", "4": "非常熟练"}
        current_key = f"knowbase:review:{user_id}"
        if args.strip() in ratings:
            card_id = await self._redis.get(current_key)
            if isinstance(card_id, bytes):
                card_id = card_id.decode("utf-8")
            if card_id:
                response = await self._http_client.post(
                    f"{self._backend_url}/api/learning/cards/{card_id}/review",
                    json={"rating": int(args.strip())},
                )
                response.raise_for_status()
                await self._redis.delete(current_key)
                return self._learning_card("✅ 复习已记录", f"你选择了「{ratings[args.strip()]}」。\n\n发送 `/review` 查看下一张卡片。", "green")

        params = {"due_only": "true"}
        workspace = await self._get_workspace(user_id)
        if workspace:
            params["workspace_id"] = workspace
        response = await self._http_client.get(f"{self._backend_url}/api/learning/cards", params=params)
        response.raise_for_status()
        cards = response.json()
        if not cards:
            return self._learning_card("🎉 今日复习完成", "现在没有到期卡片。可以直接提问，或去 Web 端把回答保存为新卡片。", "green")
        card = cards[0]
        await self._redis.set(current_key, card["id"], ex=3600)
        return self._learning_card(
            "🧠 今日知识卡",
            f"**问题**\n{card['front']}\n\n---\n**答案**\n{card['back']}\n\n回复 `/review 1` 忘记了 · `/review 2` 模糊 · `/review 3` 记住 · `/review 4` 熟练",
        )

    async def _handle_mode(self, args: str, user_id: str) -> dict:
        aliases = {"直接": "direct", "通俗": "simple", "深入": "deep", "引导": "socratic", "费曼": "feynman", "测试": "quiz"}
        value = aliases.get(args.strip(), args.strip())
        if value not in set(aliases.values()):
            return self._learning_card("🎓 学习方式", "使用 `/mode 通俗|深入|引导|费曼|测试|直接` 切换教学方式。")
        await self._redis.set(f"knowbase:mode:{user_id}", value, ex=86400 * 30)
        return self._learning_card("✅ 学习方式已切换", f"后续回答将使用「{args.strip()}」模式。", "green")

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self._http_client.aclose()
        logger.info("CommandRouter HTTP client closed")
