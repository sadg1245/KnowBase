"""Async document job dispatch contracts."""

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all model metadata
from app.api.routes.documents import upload_documents
from app.config import Settings
from app.collector import tasks
from app.models.base import Base
from app.models.document import Document
from app.models.workspace import Workspace


class DocumentJobDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "jobs.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            workspace = Workspace(name="Jobs", slug="jobs")
            db.add(workspace)
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
            ), patch(
                "app.api.routes.documents._process_document",
                new=AsyncMock(),
            ):
                await upload_documents(
                    workspace_id=self.workspace_id,
                    files=[upload],
                    db=db,
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
                patch(
                    "app.api.routes.documents._process_document",
                    new=AsyncMock(side_effect=AssertionError("inline processing is forbidden")),
                ) as inline_processing,
            ):
                response = await upload_documents(
                    workspace_id=self.workspace_id,
                    files=[upload],
                    db=db,
                    settings=self.settings,
                )

            self.assertEqual(response[0]["status"], "failed")
            self.assertIn("queue", response[0]["document"].error_message.lower())
            inline_processing.assert_not_awaited()

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
