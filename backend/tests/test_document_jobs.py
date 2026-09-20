"""Async document job dispatch contracts."""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.api.routes.documents import upload_documents
from app.config import Settings
from app.collector import tasks
from app.collector.pipeline import DocumentPipeline
from app.models.base import Base
from app.models.document import Document
from app.models.workspace import Workspace
from app.services.learning_content import LearningGenerationError
from tests.support import create_user, create_workspace


class DocumentJobDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "jobs.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            user = await create_user(db)
            self.user = user
            workspace = await create_workspace(db, user, name="Jobs", slug="jobs")
            await db.commit()
            self.workspace_id = workspace.id
        self.settings = Settings.model_construct(
            UPLOAD_DIR=str(Path(self.temp_dir.name) / "uploads"),
            UPLOAD_MAX_SIZE_MB=1,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_upload_commits_processing_before_dispatch(self):
        observed_statuses = []
        observed = asyncio.Event()

        def dispatch(document):
            document_id = document.id

            async def observe():
                async with self.sessions() as observer:
                    visible = (await observer.execute(
                        select(Document).where(Document.id == document_id)
                    )).scalar_one()
                    observed_statuses.append(visible.status)
                observed.set()

            asyncio.get_running_loop().create_task(observe())

        upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"async content"))
        async with self.sessions() as db:
            with patch(
                "app.api.routes.documents.enqueue_document_processing",
                side_effect=dispatch,
            ), patch(
                "app.collector.tasks.process_document_task.delay",
                side_effect=RuntimeError("broker unavailable"),
            ):
                await upload_documents(
            workspace_id=self.workspace_id,
            files=[upload],
            db=db,
            current_user=self.user,
            settings=self.settings,
                )
            await db.commit()

        await asyncio.wait_for(observed.wait(), timeout=1)
        self.assertEqual(observed_statuses, ["processing"])

    async def test_broker_failure_marks_document_failed_without_inline_processing(self):
        upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"async content"))
        async with self.sessions() as db:
            with (
                patch(
                    "app.api.routes.documents.enqueue_document_processing",
                    side_effect=RuntimeError("broker unavailable"),
                ),
                patch(
                    "app.collector.tasks.process_document_task.delay",
                    side_effect=RuntimeError("broker unavailable"),
                ),
            ):
                response = await upload_documents(
            workspace_id=self.workspace_id,
            files=[upload],
            db=db,
            current_user=self.user,
            settings=self.settings,
                )

            self.assertEqual(response[0]["status"], "failed")
            self.assertIn("queue", response[0]["document"].error_message.lower())

    async def test_ready_document_commits_learning_queue_before_dispatch(self):
        observed_statuses = []
        observed = asyncio.Event()
        async with self.sessions() as db:
            document = Document(
                workspace_id=self.workspace_id,
                filename="notes.txt",
                file_path="notes.txt",
                file_type=".txt",
                status="ready",
            )
            db.add(document)
            await db.commit()
            document_id = document.id

            def dispatch(queued_document_id):
                async def observe():
                    async with self.sessions() as observer:
                        visible = (await observer.execute(
                            select(Document).where(Document.id == queued_document_id)
                        )).scalar_one()
                        observed_statuses.append(visible.learning_status)
                    observed.set()

                asyncio.get_running_loop().create_task(observe())

            with patch(
                "app.services.document_jobs.enqueue_learning_generation",
                side_effect=dispatch,
            ):
                await tasks._queue_learning_generation(db, document_id)

        await asyncio.wait_for(observed.wait(), timeout=1)
        self.assertEqual(observed_statuses, ["queued"])

    async def test_status_commit_failure_rolls_back_and_propagates(self):
        class FailingSession:
            rolled_back = False

            async def execute(self, _statement):
                return None

            async def commit(self):
                raise RuntimeError("database unavailable")

            async def rollback(self):
                self.rolled_back = True

        db = FailingSession()
        with self.assertRaisesRegex(RuntimeError, "database unavailable"):
            await DocumentPipeline._update_document_status(
                db,
                "document-id",
                status="ready",
            )
        self.assertTrue(db.rolled_back)

    async def test_non_ready_document_is_not_queued_or_dispatched(self):
        class Result:
            def scalar_one_or_none(self):
                return document

        class DurableSession:
            async def execute(self, _statement):
                return Result()

            async def commit(self):
                raise AssertionError("a non-ready document must not be committed as queued")

        document = Document(
            id="document-id",
            workspace_id=self.workspace_id,
            filename="notes.txt",
            file_path="notes.txt",
            file_type=".txt",
            status="processing",
            learning_status="not_started",
        )
        with patch("app.services.document_jobs.enqueue_learning_generation") as dispatch:
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                await tasks._queue_learning_generation(DurableSession(), document.id)
        dispatch.assert_not_called()
        self.assertEqual(document.learning_status, "not_started")


class LearningGenerationRetryTests(unittest.TestCase):
    def test_litellm_transient_errors_are_recognized_through_learning_error(self):
        error_names = [
            "Timeout",
            "APIConnectionError",
            "RateLimitError",
            "ServiceUnavailableError",
            "InternalServerError",
        ]
        for error_name in error_names:
            with self.subTest(error_type=error_name):
                error_type = type(error_name, (Exception,), {"__module__": "litellm.exceptions"})
                transient = error_type("temporary")
                try:
                    raise LearningGenerationError("generation failed") from transient
                except LearningGenerationError as wrapped:
                    self.assertTrue(tasks._is_transient_exception(wrapped))

    def test_four_eager_transient_failures_mark_learning_failed(self):
        class Result:
            def scalar_one_or_none(self):
                return document

        class Session:
            async def execute(self, _statement):
                return Result()

            async def commit(self):
                return None

            async def rollback(self):
                return None

            async def close(self):
                return None

        document = Document(
            id="document-id",
            workspace_id="workspace-id",
            filename="notes.txt",
            file_path="notes.txt",
            file_type=".txt",
            status="ready",
            learning_status="queued",
        )
        attempts = 0

        async def always_timeout(_db, _document_id, _overwrite_tags=False, _force=False):
            nonlocal attempts
            attempts += 1
            raise TimeoutError("temporary outage")

        original_eager = tasks.celery_app.conf.task_always_eager
        original_propagates = tasks.celery_app.conf.task_eager_propagates
        tasks.celery_app.conf.update(task_always_eager=True, task_eager_propagates=False)
        try:
            with patch("app.collector.tasks._get_db_session", side_effect=Session), patch(
                "app.collector.tasks._generate_learning_content",
                side_effect=always_timeout,
            ):
                result = tasks.generate_learning_content_task.apply(args=(document.id,))
        finally:
            tasks.celery_app.conf.update(
                task_always_eager=original_eager,
                task_eager_propagates=original_propagates,
            )

        self.assertEqual(attempts, 4)
        self.assertEqual(result.result["status"], "failed")
        self.assertEqual(document.learning_status, "failed")


class DocumentProcessingRetryTests(unittest.TestCase):
    def test_four_eager_transient_failures_mark_document_failed(self):
        class Session:
            async def close(self):
                return None

        class FailingPipeline:
            async def process_document(self, **_kwargs):
                nonlocal attempts
                attempts += 1
                raise TimeoutError("temporary outage")

            async def _update_document_status(self, _db, _document_id, **values):
                document.status = values["status"]
                document.error_message = values["error_message"]

        document = Document(
            id="document-id",
            workspace_id="workspace-id",
            filename="notes.txt",
            file_path="notes.txt",
            file_type=".txt",
            status="processing",
        )
        attempts = 0
        original_eager = tasks.celery_app.conf.task_always_eager
        original_propagates = tasks.celery_app.conf.task_eager_propagates
        tasks.celery_app.conf.update(task_always_eager=True, task_eager_propagates=False)
        try:
            with patch("app.collector.tasks._get_db_session", side_effect=Session), patch(
                "app.collector.tasks._build_pipeline",
                side_effect=FailingPipeline,
            ):
                result = tasks.process_document_task.apply(
                    args=(document.id, document.file_path, document.file_type, document.workspace_id)
                )
        finally:
            tasks.celery_app.conf.update(
                task_always_eager=original_eager,
                task_eager_propagates=original_propagates,
            )

        self.assertEqual(attempts, 4)
        self.assertEqual(result.result["status"], "failed")
        self.assertEqual(document.status, "failed")
        self.assertEqual(document.error_message, "temporary outage")
