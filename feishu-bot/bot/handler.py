"""
飞书机器人消息处理核心模块。
"""

from __future__ import annotations

import json
from typing import Optional

import httpx
from loguru import logger

from bot.auth import TokenManager
from bot.cards import build_error_card
from bot.commands import CommandRouter
from bot.config import BotConfig


class MessageHandler:
    """处理飞书收到的消息并发送回复。"""

    REPLY_URL_TEMPLATE = (
        "https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
    )
    SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(
        self,
        token_manager: TokenManager,
        command_router: CommandRouter,
        config: BotConfig,
    ):
        self._token_manager = token_manager
        self._command_router = command_router
        self._config = config
        self._http_client = httpx.AsyncClient(timeout=30.0)

    async def handle_message(self, event_data: dict) -> None:
        """
        处理飞书收到的消息事件。

        步骤：
        1. 提取 sender_id、message_id、chat_type、消息内容
        2. 仅处理文本消息（MVP 阶段忽略图片、文件等）
        3. 从飞书 JSON 格式中解析文本内容
        4. 通过命令路由器进行路由
        5. 构建响应卡片
        6. 发送回复
        """
        try:
            # 提取事件结构
            # 飞书事件数据可能有不同的封装格式。
            # v2.0 事件 schema 包含：header + event
            event = event_data.get("event", event_data)

            sender = event.get("sender", {})
            sender_id = sender.get("sender_id", {}).get("open_id", "")

            message_info = event.get("message", {})
            message_id = message_info.get("message_id", "")
            chat_type = message_info.get("chat_type", "")
            msg_type = message_info.get("message_type", "")

            logger.info(
                f"Received message: sender={sender_id}, "
                f"message_id={message_id}, chat_type={chat_type}, "
                f"msg_type={msg_type}"
            )

            # MVP 阶段仅处理文本消息
            if msg_type != "text":
                logger.info(f"Ignoring non-text message type: {msg_type}")
                return

            # 从飞书 JSON 格式中解析文本内容
            # 飞书发送的文本格式为：{"text":"实际文本内容"}
            text = self._extract_text(message_info)
            if not text:
                logger.warning("Empty text content, ignoring")
                return

            logger.info(f"Processing text from {sender_id}: '{text[:100]}...'")
            if sender_id:
                try:
                    await self._command_router._redis.sadd("knowbase:learning-users", sender_id)
                except Exception:
                    logger.warning("Could not remember the learner for reminders")

            # 通过命令路由器进行路由
            command, args = self._command_router.parse_command(text)
            logger.info(f"Parsed command: '{command}', args: '{args[:80]}...'")

            context = {
                "chat_type": chat_type,
                "message_id": message_id,
                "sender_id": sender_id,
            }

            card = await self._command_router.route_command(
                command, args, sender_id, context
            )

            # 发送回复
            await self.reply_message(message_id, card)

        except Exception as exc:
            logger.exception(f"Error handling message: {exc}")
            # 尝试向用户发送错误卡片
            try:
                message_id = (
                    event_data.get("event", event_data)
                    .get("message", {})
                    .get("message_id", "")
                )
                if message_id:
                    error_card = build_error_card(
                        f"\u5904\u7406\u6d88\u606f\u65f6\u53d1\u751f\u9519\u8bef\uff0c"
                        f"\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
                    )
                    await self.reply_message(message_id, error_card)
            except Exception:
                logger.exception("Failed to send error reply")

    def _extract_text(self, message_info: dict) -> str:
        """
        从飞书消息对象中提取纯文本。

        飞书以 JSON 格式发送文本消息：{"text":"内容"}
        文本字段中可能包含 @_user_1 形式的 @提及，需要清理。
        """
        content_str = message_info.get("content", "{}")
        try:
            content = json.loads(content_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse message content: {content_str}")
            return ""

        text = content.get("text", "")

        # 移除文本中的 @_user_N @提及占位符
        # 这些占位符在用户 @机器人 时出现
        import re
        text = re.sub(r"@_user_\d+", "", text).strip()

        return text

    async def reply_message(self, message_id: str, card: dict) -> None:
        """
        使用交互式卡片回复指定消息。

        POST https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply
        请求体中 msg_type="interactive"，card JSON 作为 content。
        """
        token = await self._token_manager.get_token()

        url = self.REPLY_URL_TEMPLATE.format(message_id=message_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "content": json.dumps(card, ensure_ascii=False),
            "msg_type": "interactive",
        }

        try:
            response = await self._http_client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(
                    f"Reply failed: code={result.get('code')}, "
                    f"msg={result.get('msg')}"
                )
            else:
                logger.info(f"Successfully replied to message {message_id}")

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"HTTP error replying to {message_id}: "
                f"{exc.response.status_code} - {exc.response.text}"
            )
            raise
        except httpx.RequestError as exc:
            logger.error(f"Request error replying to {message_id}: {exc}")
            raise

    async def send_message(self, user_id: str, card: dict) -> None:
        """
        通过 open_id 直接向用户发送消息。

        POST https://open.feishu.cn/open-apis/im/v1/messages
        请求参数中 receive_id_type="open_id"。
        """
        token = await self._token_manager.get_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"receive_id_type": "open_id"}
        payload = {
            "receive_id": user_id,
            "content": json.dumps(card, ensure_ascii=False),
            "msg_type": "interactive",
        }

        try:
            response = await self._http_client.post(
                self.SEND_URL,
                headers=headers,
                params=params,
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(
                    f"Send message failed: code={result.get('code')}, "
                    f"msg={result.get('msg')}"
                )
            else:
                logger.info(f"Successfully sent message to user {user_id}")

        except httpx.HTTPStatusError as exc:
            logger.error(
                f"HTTP error sending to {user_id}: "
                f"{exc.response.status_code} - {exc.response.text}"
            )
            raise
        except httpx.RequestError as exc:
            logger.error(f"Request error sending to {user_id}: {exc}")
            raise

    async def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self._http_client.aclose()
        logger.info("MessageHandler HTTP client closed")
