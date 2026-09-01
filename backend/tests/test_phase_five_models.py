"""Persistence and validation contracts for phase-five assessments."""

import unittest

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register complete SQLAlchemy metadata
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.assessment import LearningTask
from app.models.workspace import Workspace
from app.schemas.assessment import QuizSetGenerateRequest


class PhaseFiveModelTests(unittest.IsolatedAsyncioTestCase):
    def test_assessment_tables_and_question_extensions_are_registered(self):
        expected_tables = {
            "quiz_sets",
            "quiz_runs",
            "quiz_attempts",
            "mistake_records",
            "weak_knowledge_states",
            "learning_tasks",
        }
        self.assertTrue(expected_tables <= set(Base.metadata.tables))
        question = Base.metadata.tables["quiz_questions"]
        self.assertTrue(
            {
                "quiz_set_id",
                "document_id",
                "difficulty_level",
                "answer_payload",
                "grading_rubric",
                "source_snapshot",
                "strict_sources",
                "generation_model",
                "position",
            }
            <= set(question.c.keys())
        )

    def test_generation_schema_accepts_all_six_question_types(self):
        request = QuizSetGenerateRequest(
            workspace_id="workspace",
            count=12,
            difficulty="hard",
            question_types=[
                "single_choice", "multiple_choice", "true_false",
                "fill_blank", "short_answer", "concept_explanation",
            ],
            strict_sources=True,
            answer_mode="full_paper",
        )
        self.assertEqual(request.count, 12)

    def test_generation_schema_rejects_unknown_question_types(self):
        with self.assertRaises(ValidationError):
            QuizSetGenerateRequest(workspace_id="workspace", question_types=["essay"])

    async def test_compat_migrations_add_assessment_question_columns_idempotently(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                for table in (
                    "workspaces", "documents", "document_chunks", "knowledge_points",
                    "user_profiles", "conversations", "flashcards", "review_logs",
                ):
                    await connection.execute(text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
                await connection.execute(text("CREATE TABLE quiz_questions (id TEXT PRIMARY KEY)"))
                await run_compat_migrations(connection)
                await run_compat_migrations(connection)
                columns = {
                    row[1]
                    for row in (await connection.execute(text("PRAGMA table_info(quiz_questions)"))).fetchall()
                }
                self.assertTrue(
                    {"quiz_set_id", "document_id", "answer_payload", "source_snapshot"} <= columns
                )
        finally:
            await engine.dispose()

    async def test_pending_learning_tasks_are_idempotent_per_knowledge_point_and_type(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                workspace = Workspace(name="Assessments", slug="assessments")
                db.add(workspace)
                await db.flush()
                db.add(LearningTask(
                    workspace_id=workspace.id,
                    knowledge_point_id="point",
                    task_type="review",
                    title="Review point",
                ))
                await db.commit()
                db.add(LearningTask(
                    workspace_id=workspace.id,
                    knowledge_point_id="point",
                    task_type="review",
                    title="Duplicate review",
                ))
                with self.assertRaises(IntegrityError):
                    await db.commit()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
