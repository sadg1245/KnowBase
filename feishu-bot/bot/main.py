"""
KnowBase 飞书机器人入口。

使用 lark-oapi SDK 的 WebSocket 长连接模式接收飞书平台事件。
如果 ws 模块不可用，则回退到 webhook 模式并输出指引。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import redis.asyncio as redis
from loguru import logger

from bot.auth import TokenManager
from bot.commands import CommandRouter
from bot.config import BotConfig
from bot.handler import MessageHandler

# ---------------------------------------------------------------------------
# 优雅关闭相关的全局变量
# ---------------------------------------------------------------------------
_shutdown_event: Optional[asyncio.Event] = None


def _setup_logging(level: str) -> None:
    """配置 loguru 日志，设定日志级别。"""
    logger.remove()  # 移除默认处理器
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )


async def _create_components(config: BotConfig):
    """初始化所有服务组件。"""
    # Redis 客户端
    redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)
    logger.info(f"Redis client created for {config.REDIS_URL}")

    # Token 管理器
    token_manager = TokenManager(
        app_id=config.FEISHU_APP_ID,
        app_secret=config.FEISHU_APP_SECRET,
    )
    logger.info("TokenManager initialized")

    # 命令路由器
    command_router = CommandRouter(
        backend_url=config.BACKEND_URL,
        redis_client=redis_client,
        access_token=config.BACKEND_ACCESS_TOKEN,
    )
    logger.info(f"CommandRouter initialized (backend: {config.BACKEND_URL})")

    # 消息处理器
    message_handler = MessageHandler(
        token_manager=token_manager,
        command_router=command_router,
        config=config,
    )
    logger.info("MessageHandler initialized")

    return redis_client, token_manager, command_router, message_handler


async def _shutdown(redis_client, token_manager, command_router, message_handler):
    """优雅地关闭所有组件。"""
    logger.info("Shutting down components...")
    try:
        await message_handler.close()
    except Exception:
        pass
    try:
        await command_router.close()
    except Exception:
        pass
    try:
        await token_manager.close()
    except Exception:
        pass
    try:
        await redis_client.aclose()
    except Exception:
        pass
    logger.info("All components shut down")


async def _reminder_loop(config, command_router, message_handler):
    """Send one personal due-review reminder at the learner's chosen local time."""
    while True:
        try:
            if config.REMINDERS_ENABLED:
                now = datetime.now(ZoneInfo(config.REMINDER_TIMEZONE))
                profile_response = await command_router._http_client.get(
                    f"{config.BACKEND_URL.rstrip('/')}/api/learning/profile"
                )
                profile_response.raise_for_status()
                reminder_time = profile_response.json().get("reminder_time") or "20:00"
                if now.strftime("%H:%M") == reminder_time:
                    dashboard_response = await command_router._http_client.get(
                        f"{config.BACKEND_URL.rstrip('/')}/api/learning/dashboard"
                    )
                    dashboard_response.raise_for_status()
                    stats = dashboard_response.json().get("stats", {})
                    due = stats.get("due_cards", 0)
                    if due:
                        users = await command_router._redis.smembers("knowbase:learning-users")
                        for raw_user in users:
                            user_id = raw_user.decode() if isinstance(raw_user, bytes) else raw_user
                            sent_key = f"knowbase:reminded:{user_id}:{now.date().isoformat()}"
                            if await command_router._redis.set(sent_key, "1", ex=172800, nx=True):
                                card = command_router._learning_card(
                                    "⏰ 今天的复习到了",
                                    f"有 **{due}** 张知识卡正在等你。\n\n发送 `/review`，用几分钟把记忆接回来。",
                                )
                                await message_handler.send_message(user_id, card)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"Learning reminder check failed: {exc}")
        await asyncio.sleep(60)


def main() -> None:
    """
    主入口函数。设置 lark-oapi WebSocket 长连接客户端以接收飞书事件。
    """
    # 加载配置
    config = BotConfig()

    # 设置日志
    _setup_logging(config.LOG_LEVEL)
    logger.info(f"Starting {config.BOT_NAME} Feishu Bot...")
    logger.info(f"Backend URL: {config.BACKEND_URL}")
    logger.info(f"App ID: {config.FEISHU_APP_ID[:6]}***")

    # ------------------------------------------------------------------
    # 同步创建组件，以便将 handler 传入 lark 事件回调。
    # 这里使用一个小型 asyncio 事件循环。
    # ------------------------------------------------------------------
    loop = asyncio.new_event_loop()

    redis_client, token_manager, command_router, message_handler = loop.run_until_complete(
        _create_components(config)
    )
    loop_thread = threading.Thread(target=loop.run_forever, name="knowbase-async-loop", daemon=True)
    loop_thread.start()
    reminder_future = asyncio.run_coroutine_threadsafe(
        _reminder_loop(config, command_router, message_handler), loop
    )

    # ------------------------------------------------------------------
    # 尝试使用 lark-oapi WebSocket 长连接
    # ------------------------------------------------------------------
    try:
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

        logger.info("lark-oapi SDK loaded, setting up WebSocket long connection...")

        # 构建事件处理回调
        # lark-oapi v1.4 SDK 使用构建器模式进行事件分发。
        def on_message_receive(data: P2ImMessageReceiveV1) -> None:
            """
            当通过 WebSocket 连接收到 im.message.receive_v1 事件时，
            由 lark-oapi SDK 调用的回调函数。
            """
            try:
                # 将 SDK 事件对象转换为处理器所需的字典格式。
                # P2ImMessageReceiveV1 具有 .event 属性，包含消息数据。
                event_dict = _sdk_event_to_dict(data)
                if event_dict:
                    # 在事件循环中运行异步处理器
                    asyncio.run_coroutine_threadsafe(
                        message_handler.handle_message(event_dict),
                        loop,
                    )
            except Exception as exc:
                logger.exception(f"Error in on_message_receive callback: {exc}")

        # 构建事件分发器
        dispatcher = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message_receive)
            .build()
        )
        logger.info("Event dispatcher built with im.message.receive_v1 handler")

        # 确定 lark SDK 的日志级别
        lark_log_level_map = {
            "DEBUG": lark.LogLevel.DEBUG,
            "INFO": lark.LogLevel.INFO,
            "WARNING": lark.LogLevel.WARNING,
            "ERROR": lark.LogLevel.ERROR,
        }
        lark_log_level = lark_log_level_map.get(
            config.LOG_LEVEL.upper(), lark.LogLevel.INFO
        )

        # 创建 WebSocket 长连接客户端
        ws_client = lark.ws.Client(
            config.FEISHU_APP_ID,
            config.FEISHU_APP_SECRET,
            event_handler=dispatcher,
            log_level=lark_log_level,
        )

        logger.info("WebSocket client created, starting long connection...")
        logger.info(
            "Bot is now listening for messages via WebSocket. "
            "Press Ctrl+C to stop."
        )

        # 启动 WebSocket 客户端（此操作会阻塞）
        ws_client.start()

    except ImportError as exc:
        logger.error(f"Failed to import lark-oapi ws module: {exc}")
        _print_fallback_instructions()
        reminder_future.cancel()
        asyncio.run_coroutine_threadsafe(
            _shutdown(redis_client, token_manager, command_router, message_handler), loop
        ).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)

    except AttributeError as exc:
        # lark_oapi.ws 在较旧版本的 SDK 中可能不存在
        logger.error(f"lark-oapi ws module not available: {exc}")
        _print_fallback_instructions()
        reminder_future.cancel()
        asyncio.run_coroutine_threadsafe(
            _shutdown(redis_client, token_manager, command_router, message_handler), loop
        ).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)

    except Exception as exc:
        logger.exception(f"Unexpected error starting bot: {exc}")
        reminder_future.cancel()
        asyncio.run_coroutine_threadsafe(
            _shutdown(redis_client, token_manager, command_router, message_handler), loop
        ).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)
    finally:
        if loop.is_running():
            reminder_future.cancel()
            try:
                asyncio.run_coroutine_threadsafe(
                    _shutdown(redis_client, token_manager, command_router, message_handler), loop
                ).result(timeout=10)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
            loop_thread.join(timeout=5)


def _sdk_event_to_dict(data) -> Optional[dict]:
    """
    将 lark-oapi SDK 的 P2ImMessageReceiveV1 事件转换为
    MessageHandler 可处理的普通字典。

    SDK 事件结构：
    - data.event.sender.sender_id.open_id
    - data.event.message.message_id
    - data.event.message.chat_type
    - data.event.message.message_type
    - data.event.message.content  (JSON 字符串)
    """
    try:
        event = data.event
        sender = event.sender
        message = event.message

        # 解析消息内容
        content_str = message.content if message.content else "{}"

        event_dict = {
            "event": {
                "sender": {
                    "sender_id": {
                        "open_id": sender.sender_id.open_id if sender and sender.sender_id else "",
                    },
                },
                "message": {
                    "message_id": message.message_id or "",
                    "chat_type": message.chat_type or "",
                    "message_type": message.message_type or "",
                    "content": content_str,
                },
            },
        }

        return event_dict

    except Exception as exc:
        logger.exception(f"Failed to convert SDK event to dict: {exc}")
        return None


def _print_fallback_instructions() -> None:
    """当 WebSocket 不可用时，打印 webhook 模式的使用指引。"""
    print(
        "\n"
        "=" * 60 + "\n"
        "  WebSocket long connection mode is not available.\n"
        "  The lark-oapi SDK version may not support lark_oapi.ws.\n"
        "\n"
        "  To use webhook mode instead:\n"
        "  1. Set up a public-facing HTTPS endpoint\n"
        "  2. Configure the webhook URL in the Feishu Developer Console\n"
        "  3. Use a web framework (Flask/FastAPI) to receive POST events\n"
        "  4. Route them through the MessageHandler\n"
        "\n"
        "  Alternatively, upgrade lark-oapi to version >= 1.3.0:\n"
        "    pip install --upgrade lark-oapi\n"
        + "=" * 60 + "\n"
    )


if __name__ == "__main__":
    main()
