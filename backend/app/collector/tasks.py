"""用于异步文档处理的 Celery 任务定义。

本模块定义了 ``process_document_task``，它封装了
:class:`~app.collector.pipeline.DocumentPipeline`，以便通过
Celery / Redis 进行调度。

**优雅降级**：如果未安装 ``celery`` 或其 Redis 传输层，
本模块仍可正常导入——``celery_app`` 和任务对象将为 ``None``，
调用方可以回退到在进程内运行流水线。
"""

import asyncio
from typing import Any

from loguru import logger
from sqlalchemy import select

# ---------------------------------------------------------------------------
# 尝试创建 Celery 应用。如果未安装 Celery，则将 ``celery_app`` 设为
# ``None``，以便文件的其余部分仍可正常导入。
# ---------------------------------------------------------------------------
celery_app: Any = None

try:
    from celery import Celery

    # 默认 Broker URL——可通过 CELERY_BROKER_URL 环境变量或在导入后
    # 调用 ``celery_app.conf.update(...)`` 来覆盖。
    import os

    _broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    _result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

    celery_app = Celery(
        "knowbase.collector",
        broker=_broker_url,
        backend=_result_backend,
    )

    # 合理的默认配置
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        # Broker 连接重试策略
        broker_connection_retry_on_startup=True,
    )

except ImportError:
    logger.warning(
        "celery is not installed — process_document_task will not be available "
        "as a Celery task. Install celery[redis] to enable async processing.",
    )
except Exception as exc:
    logger.warning(
        "Failed to initialise Celery app: {}. "
        "process_document_task will not be available as a Celery task.",
        exc,
    )


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_db_session() -> Any:
    """为任务工作器创建新的异步数据库会话。"""
    from app.models.base import async_session_factory
    return async_session_factory()


def _build_pipeline() -> Any:
    """使用项目中的服务构建 :class:`DocumentPipeline` 实例。

    请调整以下导入路径以匹配你项目中的服务初始化方式。
    """
    try:
        from app.core.embedding import get_embedding_service  # 绝对导入
        from app.core.vector_store import get_vector_store  # 绝对导入
        from app.core.text_splitter import get_text_splitter  # 绝对导入
    except ImportError as exc:
        logger.error(
            "Cannot import required services (embedding / vector_store / "
            "text_splitter). Check app.core modules. Error: {}", exc,
        )
        raise

    embedding_service = get_embedding_service()
    vector_store = get_vector_store()
    text_splitter = get_text_splitter()

    from .pipeline import DocumentPipeline  # 包内相对导入

    return DocumentPipeline(
        embedding_service=embedding_service,
        vector_store=vector_store,
        text_splitter=text_splitter,
    )


async def _queue_learning_generation(db_session: Any, document_id: str) -> None:
    """Persist the learning job state before asking Celery to execute it."""
    from app.models.document import Document

    document = (await db_session.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if document is None:
        raise ValueError(f"Document {document_id} was not found after processing")
    if document.status != "ready":
        raise RuntimeError(f"Document {document_id} is not ready for learning generation")

    document.learning_status = "queued"
    document.learning_error_message = None
    await db_session.commit()

    try:
        from app.services.document_jobs import enqueue_learning_generation

        enqueue_learning_generation(document_id)
    except Exception as exc:
        document.learning_status = "failed"
        document.learning_error_message = f"Learning queue dispatch failed: {exc}"[:1000]
        await db_session.commit()
        logger.exception("Failed to dispatch learning generation for {}", document_id)


async def _generate_learning_content(
    db_session: Any, document_id: str, overwrite_tags: bool = False
) -> dict[str, Any]:
    """Run one durable learning-generation attempt in the worker session."""
    from app.config import settings
    from app.models.document import Document
    from app.services.learning_content import generate_document_learning_content

    document = (await db_session.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if document is None:
        raise ValueError(f"Document {document_id} was not found")

    document.learning_status = "generating"
    document.learning_error_message = None
    await db_session.commit()
    await generate_document_learning_content(
        db_session, document_id, settings, overwrite_tags=overwrite_tags
    )
    await db_session.commit()
    return {"document_id": document_id, "status": "ready"}


async def _mark_learning_failed(db_session: Any, document_id: str, exc: Exception) -> None:
    """Make terminal worker errors visible on the document record."""
    await db_session.rollback()
    from app.models.document import Document

    document = (await db_session.execute(
        select(Document).where(Document.id == document_id)
    )).scalar_one_or_none()
    if document is None:
        return
    document.learning_status = "failed"
    document.learning_error_message = str(exc)[:1000]
    await db_session.commit()


def _is_transient_exception(exc: Exception) -> bool:
    """Retry known transport/service failures, including wrapped LiteLLM errors."""
    litellm_transient_names = {
        "Timeout",
        "APIConnectionError",
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
    }

    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        error_type = type(current)
        is_litellm_transient = (
            error_type.__name__ in litellm_transient_names
            and error_type.__module__.split(".", 1)[0] == "litellm"
        )
        if isinstance(current, (ConnectionError, TimeoutError, OSError)) or is_litellm_transient:
            return True
        status_code = getattr(current, "status_code", None)
        response = getattr(current, "response", None)
        status_code = status_code or getattr(response, "status_code", None)
        if status_code in {408, 429, 500, 501, 502, 503, 504}:
            return True
        current = current.__cause__ or current.__context__
    return False


# ---------------------------------------------------------------------------
# Celery 任务
# ---------------------------------------------------------------------------

if celery_app is not None:

    @celery_app.task(
        name="collector.process_document",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        acks_late=True,
    )
    def process_document_task(
        self,
        document_id: str,
        file_path: str,
        file_type: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        """运行完整文档处理流水线的 Celery 任务。

        本任务会创建自己的数据库会话，实例化流水线，
        并端到端地处理文档。失败时最多重试 ``max_retries`` 次，
        超过重试上限后将文档标记为 ``failed``。

        参数
        ----------
        document_id : str
            数据库中文档记录的 UUID。
        file_path : str
            磁盘上已上传文件的绝对路径。
        file_type : str
            文件扩展名（例如 ``"pdf"``、``"docx"``）。
        workspace_id : str
            拥有该文档的工作区的 UUID。

        返回
        -------
        dict
            流水线摘要：``{chunks_count, embedding_count, status}``。
        """
        logger.info(
            "[Celery] Processing document {} (type={}, file={})",
            document_id, file_type, file_path,
        )

        pipeline = None
        db_session = None

        try:
            pipeline = _build_pipeline()
            db_session = _get_db_session()

            # 流水线是异步的；由于 Celery 工作器是同步的，
            # 因此在一个新的事件循环中运行它。
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    pipeline.process_document(
                        document_id=document_id,
                        file_path=file_path,
                        file_type=file_type,
                        workspace_id=workspace_id,
                        db_session=db_session,
                    )
                )
                if result.get("status") == "ready":
                    loop.run_until_complete(
                        _queue_learning_generation(db_session, document_id)
                    )
            finally:
                loop.close()

            logger.info(
                "[Celery] Document {} processing complete: {}", document_id, result,
            )
            return result

        except Exception as exc:
            logger.error(
                "[Celery] Document {} processing failed: {}", document_id, exc,
            )

            # 如果未超过重试上限则尝试重试
            if self.request.retries < self.max_retries:
                raise self.retry(exc=exc)
            if self.request.retries >= self.max_retries:
                logger.error(
                    "[Celery] Max retries exceeded for document {}. "
                    "Marking as failed.",
                    document_id,
                )
                # 尽力而为：在数据库中将文档标记为失败
                if pipeline is not None and db_session is not None:
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(
                            pipeline._update_document_status(
                                db_session, document_id,
                                status="failed",
                                error_message=str(exc),
                            )
                        )
                        loop.close()
                    except Exception:
                        pass

                return {
                    "chunks_count": 0,
                    "embedding_count": 0,
                    "status": "failed",
                    "error": str(exc),
                }
        finally:
            # 清理数据库会话
            if db_session is not None:
                try:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(db_session.close())
                    loop.close()
                except Exception:
                    pass


    @celery_app.task(
        name="collector.generate_learning_content",
        bind=True,
        max_retries=3,
        default_retry_delay=30,
        acks_late=True,
    )
    def generate_learning_content_task(
        self,
        document_id: str,
        overwrite_tags: bool = False,
    ) -> dict[str, Any]:
        """Generate learning material after document parsing has completed."""
        db_session = None
        try:
            db_session = _get_db_session()
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    _generate_learning_content(db_session, document_id, overwrite_tags)
                )
            finally:
                loop.close()
        except Exception as exc:
            logger.error("[Celery] Learning generation failed for {}: {}", document_id, exc)
            if _is_transient_exception(exc) and self.request.retries < self.max_retries:
                if db_session is not None:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(db_session.rollback())
                    finally:
                        loop.close()
                raise self.retry(exc=exc)

            if db_session is not None:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        _mark_learning_failed(db_session, document_id, exc)
                    )
                finally:
                    loop.close()
            return {
                "document_id": document_id,
                "status": "failed",
                "error": str(exc),
            }
        finally:
            if db_session is not None:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(db_session.close())
                finally:
                    loop.close()

else:
    class _UnavailableTask:
        """Reject dispatch when Celery is unavailable; never run work inline."""

        def delay(self, **_kwargs: Any) -> None:
            raise RuntimeError("Celery is unavailable")


    process_document_task = _UnavailableTask()
    generate_learning_content_task = _UnavailableTask()
