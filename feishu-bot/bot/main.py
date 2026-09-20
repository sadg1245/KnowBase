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
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

import redis.asyncio as redis
from loguru import logger

from bot.auth import TokenManager
from bot.commands import CommandRouter
from bot.config import BotConfig
from bot.handler import MessageHandler
from bot.runtime_config import (
    FeishuCredentials,
    StatusReporter,
    resolve_credentials,
)

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


async def _create_components(config: BotConfig, credentials: FeishuCredentials):
    """初始化所有服务组件。"""
    # Redis 客户端
    redis_client = redis.from_url(config.REDIS_URL, decode_responses=True)
    logger.info(f"Redis client created for {config.REDIS_URL}")

    # Token 管理器
    token_manager = TokenManager(
        app_id=credentials.app_id,
        app_secret=credentials.app_secret,
    )
    logger.info(f"TokenManager initialized for {credentials.label}")

    # 命令路由器
    command_router = CommandRouter(
        backend_url=config.BACKEND_URL,
        redis_client=redis_client,
        access_token=config.BACKEND_ACCESS_TOKEN,
    )
    if not config.BACKEND_ACCESS_TOKEN:
        logger.warning(
            "BACKEND_ACCESS_TOKEN 为空：后端会以 401 拒绝机器人的私人数据请求。"
            "请在 .env 中把 SERVICE_TOKEN 与 BACKEND_ACCESS_TOKEN 设为同一个随机值。"
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


def _report_status(loop, reporter: StatusReporter, state: str, **kwargs) -> None:
    """在后台事件循环上发一条状态（失败不影响机器人）。"""
    try:
        asyncio.run_coroutine_threadsafe(reporter.report(state, **kwargs), loop)
    except Exception as exc:
        logger.debug(f"状态上报调度失败：{exc}")


def _wait_for_credentials(config: BotConfig, loop, reporter: StatusReporter) -> FeishuCredentials:
    """等到拿到凭证再上线。

    没有配置时停在“待配置”状态并定期重试，而不是像以前那样直接抛异常退出；
    用户在设置页填好以后，最迟一个刷新周期后机器人自动连上。
    """
    guidance_printed = False
    while True:
        credentials, reason = asyncio.run_coroutine_threadsafe(
            resolve_credentials(config), loop
        ).result()
        if credentials is not None:
            logger.info(f"飞书凭证已就绪：{credentials.label}")
            _report_status(loop, reporter, "connecting", app_id=credentials.app_id)
            return credentials
        _report_status(loop, reporter, "pending", detail=reason)
        if not guidance_printed:
            logger.warning(
                "飞书机器人尚未配置（{}）。打开网页「设置 → 飞书机器人」填写 App ID 与 App Secret 即可，"
                "机器人会自动上线；继续使用 .env 里的 FEISHU_APP_ID / FEISHU_APP_SECRET 也支持。",
                reason,
            )
            guidance_printed = True
        time.sleep(max(5, int(config.CONFIG_REFRESH_SECONDS)))


def _watch_credentials(
    config: BotConfig,
    loop,
    reporter: StatusReporter,
    active: FeishuCredentials,
    stop_event: threading.Event,
) -> None:
    """连接期间盯住设置页有没有换凭证。

    lark-oapi 的长连接没有受支持的停止/重建入口，硬拆会造成重复收消息，
    所以这里如实上报「需要重启」，而不是偷偷半重启。
    """
    while not stop_event.wait(max(5, int(config.CONFIG_REFRESH_SECONDS))):
        try:
            latest, _reason = asyncio.run_coroutine_threadsafe(
                resolve_credentials(config), loop
            ).result()
        except Exception:
            continue
        if latest is None or latest == active:
            continue
        logger.warning(
            f"设置页里的飞书凭证已更新（{latest.label}），但当前长连接仍在用旧凭证："
            "请重启机器人容器（docker compose restart feishu-bot）后生效。"
        )
        _report_status(
            loop,
            reporter,
            "restart_required",
            detail="设置页已更新飞书凭证，重启机器人后生效",
            app_id=latest.app_id,
        )
        return


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

    # ------------------------------------------------------------------
    # 先起后台事件循环（状态上报与取配置都要用它），拿到凭证后再建组件。
    # ------------------------------------------------------------------
    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, name="knowbase-async-loop", daemon=True)
    loop_thread.start()
    reporter = StatusReporter(config)

    redis_client = token_manager = command_router = message_handler = None
    reminder_future = None
    credentials: Optional[FeishuCredentials] = None

    try:
        credentials = _wait_for_credentials(config, loop, reporter)
        redis_client, token_manager, command_router, message_handler = (
            asyncio.run_coroutine_threadsafe(
                _create_components(config, credentials), loop
            ).result()
        )
        reminder_future = asyncio.run_coroutine_threadsafe(
            _reminder_loop(config, command_router, message_handler), loop
        )
    except KeyboardInterrupt:
        logger.info("收到退出信号，尚未建立连接。")
        _report_status(loop, reporter, "pending", detail="机器人已停止")
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        return

    # ------------------------------------------------------------------
    # 尝试使用 lark-oapi WebSocket 长连接
    # ------------------------------------------------------------------
    watcher_stop = threading.Event()
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
            credentials.app_id,
            credentials.app_secret,
            event_handler=dispatcher,
            log_level=lark_log_level,
        )

        logger.info("WebSocket client created, starting long connection...")
        logger.info(
            "Bot is now listening for messages via WebSocket. "
            "Press Ctrl+C to stop."
        )

        # 连接期间盯住设置页有没有换凭证（换了要重启才生效，如实上报）
        watcher = threading.Thread(
            target=_watch_credentials,
            args=(config, loop, reporter, credentials, watcher_stop),
            name="knowbase-credential-watch",
            daemon=True,
        )
        watcher.start()
        _report_status(loop, reporter, "connected", app_id=credentials.app_id)

        # 启动 WebSocket 客户端（此操作会阻塞）
        ws_client.start()

    except ImportError as exc:
        logger.error(f"Failed to import lark-oapi ws module: {exc}")
        _report_status(loop, reporter, "error", detail="缺少 lark-oapi 长连接模块")
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
        _report_status(loop, reporter, "error", detail="当前 lark-oapi 不支持长连接")
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
        _report_status(loop, reporter, "error", detail=f"{exc.__class__.__name__}: {exc}"[:200])
        reminder_future.cancel()
        asyncio.run_coroutine_threadsafe(
            _shutdown(redis_client, token_manager, command_router, message_handler), loop
        ).result(timeout=10)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=5)
        sys.exit(1)
    finally:
        watcher_stop.set()
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
