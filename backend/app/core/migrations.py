"""Small, idempotent compatibility migrations for existing SQLite installs.

The project still supports PostgreSQL through normal schema creation.  These
ALTER statements only bridge older local SQLite databases created before the
learning fields existed.
"""

import uuid

from loguru import logger
from sqlalchemy import text


async def _run_postgresql_phase_six_migrations(conn) -> None:
    """Bridge pre-Phase-6 PostgreSQL tables before ORM queries touch new columns."""
    additions = {
        "user_profiles": {
            "weekly_goal_days": "INTEGER NOT NULL DEFAULT 5",
            "timezone_name": "VARCHAR(100) NOT NULL DEFAULT 'Asia/Shanghai'",
        },
        "study_activities": {
            "event_key": "VARCHAR(255)",
            "source_type": "VARCHAR(40)",
            "source_id": "VARCHAR(64)",
            "occurred_at": "TIMESTAMP WITH TIME ZONE",
            "schema_version": "INTEGER NOT NULL DEFAULT 1",
        },
    }
    tables = set((await conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema()"
    ))).scalars())
    for table, columns in additions.items():
        if table not in tables:
            continue
        existing = set((await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table"
        ), {"table": table})).scalars())
        for name, ddl in columns.items():
            if name not in existing:
                await conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {ddl}'))
    if "study_activities" in tables:
        await conn.execute(text(
            "UPDATE study_activities SET occurred_at = created_at WHERE occurred_at IS NULL"
        ))
        await conn.execute(text(
            "ALTER TABLE study_activities ALTER COLUMN occurred_at SET NOT NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_study_activities_event_key "
            "ON study_activities(event_key) WHERE event_key IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_study_activities_type_occurred "
            "ON study_activities(activity_type, occurred_at)"
        ))


async def run_compat_migrations(conn) -> None:
    if conn.dialect.name == "postgresql":
        await _run_postgresql_phase_six_migrations(conn)
        return
    if conn.dialect.name != "sqlite":
        return

    table_rows = await conn.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
    tables = {row[0] for row in table_rows.fetchall()}
    additions = {
        "workspaces": {
            "learning_goal": "TEXT DEFAULT ''",
            "domain": "VARCHAR(100) DEFAULT '未分类'",
            "accent_color": "VARCHAR(20) NOT NULL DEFAULT '#1f7a8c'",
            "archived": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "documents": {
            "summary": "TEXT",
            "outline": "TEXT",
            "learning_status": "VARCHAR(20) NOT NULL DEFAULT 'not_started'",
            "tags": "JSON NOT NULL DEFAULT '[]'",
            "chapter_summaries": "JSON NOT NULL DEFAULT '[]'",
            "core_concepts": "JSON NOT NULL DEFAULT '[]'",
            "important_terms": "JSON NOT NULL DEFAULT '[]'",
            "common_mistakes": "JSON NOT NULL DEFAULT '[]'",
            "prerequisites": "JSON NOT NULL DEFAULT '[]'",
            "learning_order": "JSON NOT NULL DEFAULT '[]'",
            "review_points": "JSON NOT NULL DEFAULT '[]'",
            "learning_error_message": "TEXT",
            "processed_at": "DATETIME",
            "learning_generated_at": "DATETIME",
        },
        "document_chunks": {
            "heading_level": "INTEGER",
            "section_path": "JSON NOT NULL DEFAULT '[]'",
        },
        "knowledge_points": {
            "is_key": "BOOLEAN NOT NULL DEFAULT 0",
            "mastery_status": "VARCHAR(20) NOT NULL DEFAULT 'not_started'",
        },
        "user_profiles": {
            "password_hash": "VARCHAR(255)",
            "weekly_goal_days": "INTEGER NOT NULL DEFAULT 5",
            "timezone_name": "VARCHAR(100) NOT NULL DEFAULT 'Asia/Shanghai'",
        },
        "conversations": {
            "session_id": "VARCHAR(36)",
            "mode": "VARCHAR(20)",
            "evidence_status": "VARCHAR(20)",
            "retrieval_run_id": "VARCHAR(36)",
            "follow_up_questions": "JSON NOT NULL DEFAULT '[]'",
            "generation_status": "VARCHAR(20) NOT NULL DEFAULT 'complete'",
        },
        "quiz_questions": {
            "origin_message_id": "VARCHAR(36)",
            "quiz_set_id": "VARCHAR(36)",
            "document_id": "VARCHAR(36)",
            "difficulty_level": "VARCHAR(20) NOT NULL DEFAULT 'medium'",
            "answer_payload": "JSON",
            "grading_rubric": "JSON",
            "source_snapshot": "JSON NOT NULL DEFAULT '[]'",
            "strict_sources": "BOOLEAN NOT NULL DEFAULT 0",
            "generation_model": "VARCHAR(255)",
            "position": "INTEGER NOT NULL DEFAULT 0",
        },
        "flashcards": {
            "origin_message_id": "VARCHAR(36)",
            "tags": "JSON NOT NULL DEFAULT '[]'",
            "difficulty": "INTEGER NOT NULL DEFAULT 2",
            "mastery": "FLOAT NOT NULL DEFAULT 0.0",
            "mastery_status": "VARCHAR(20) NOT NULL DEFAULT 'not_started'",
            "source_type": "VARCHAR(30) NOT NULL DEFAULT 'manual'",
            "source_snapshot": "JSON",
            "algorithm_version": "VARCHAR(20) NOT NULL DEFAULT 'simple_v1'",
            "scheduler_data": "JSON NOT NULL DEFAULT '{}'",
            "last_reviewed_at": "DATETIME",
            "total_review_seconds": "INTEGER NOT NULL DEFAULT 0",
            # SQLite rejects non-constant defaults when ALTER TABLE adds a
            # column. Add it nullable, then backfill legacy rows below.
            "updated_at": "DATETIME",
        },
        "review_logs": {
            "duration_seconds": "INTEGER NOT NULL DEFAULT 0",
            "previous_mastery": "FLOAT NOT NULL DEFAULT 0.0",
            "next_mastery": "FLOAT NOT NULL DEFAULT 0.0",
            "previous_status": "VARCHAR(20) NOT NULL DEFAULT 'not_started'",
            "next_status": "VARCHAR(20) NOT NULL DEFAULT 'learning'",
            "algorithm_version": "VARCHAR(20) NOT NULL DEFAULT 'simple_v1'",
        },
        "study_activities": {
            "event_key": "VARCHAR(255)",
            "source_type": "VARCHAR(40)",
            "source_id": "VARCHAR(64)",
            "occurred_at": "DATETIME",
            "schema_version": "INTEGER NOT NULL DEFAULT 1",
        },
    }
    for table, columns in additions.items():
        if table not in tables:
            continue
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in rows.fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    if "flashcards" in tables:
        await conn.execute(text(
            "UPDATE flashcards SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        ))
    if "study_activities" in tables:
        await conn.execute(text(
            "UPDATE study_activities SET occurred_at = created_at WHERE occurred_at IS NULL"
        ))

    if "flashcards" in tables:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_flashcards_origin_message_id "
            "ON flashcards(origin_message_id) WHERE origin_message_id IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_flashcards_mastery_status ON flashcards(mastery_status)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_flashcards_source_type ON flashcards(source_type)"
        ))
    if "quiz_questions" in tables:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_quiz_questions_origin_message_id "
            "ON quiz_questions(origin_message_id) WHERE origin_message_id IS NOT NULL"
        ))
    if "study_activities" in tables:
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_study_activities_event_key "
            "ON study_activities(event_key) WHERE event_key IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_study_activities_type_occurred "
            "ON study_activities(activity_type, occurred_at)"
        ))
    if "quiz_runs" in tables:
        columns = {row[1] for row in (await conn.execute(text("PRAGMA table_info(quiz_runs)"))).fetchall()}
        if "question_ids" not in columns:
            await conn.execute(text("ALTER TABLE quiz_runs ADD COLUMN question_ids JSON"))
    assessment_indexes = {
        "quiz_questions": (
            "CREATE INDEX IF NOT EXISTS ix_quiz_questions_quiz_set_id ON quiz_questions(quiz_set_id)",
            "CREATE INDEX IF NOT EXISTS ix_quiz_questions_document_id ON quiz_questions(document_id)",
        ),
        "mistake_records": (
            "CREATE INDEX IF NOT EXISTS ix_mistake_records_mastery_status ON mistake_records(mastery_status)",
        ),
        "weak_knowledge_states": (
            "CREATE INDEX IF NOT EXISTS ix_weak_knowledge_states_weakness_score ON weak_knowledge_states(weakness_score)",
        ),
        "learning_tasks": (
            "CREATE INDEX IF NOT EXISTS ix_learning_tasks_due_at ON learning_tasks(due_at)",
            "CREATE INDEX IF NOT EXISTS ix_learning_tasks_status ON learning_tasks(status)",
        ),
    }
    for table, statements in assessment_indexes.items():
        if table in tables:
            for statement in statements:
                await conn.execute(text(statement))
    if "learning_goals" in tables and "user_profiles" in tables:
        profile_columns = {
            row[1]
            for row in (await conn.execute(text("PRAGMA table_info(user_profiles)"))).fetchall()
        }
        required = {"daily_goal_minutes", "daily_review_target", "weekly_goal_days"}
        if required <= profile_columns:
            profile = (await conn.execute(text(
                "SELECT daily_goal_minutes, daily_review_target, weekly_goal_days "
                "FROM user_profiles ORDER BY created_at LIMIT 1"
            ))).one_or_none()
            if profile is not None:
                defaults = (
                    ("daily_minutes", float(profile.daily_goal_minutes)),
                    ("daily_reviews", float(profile.daily_review_target)),
                    ("weekly_days", float(profile.weekly_goal_days)),
                )
                for metric, target_value in defaults:
                    exists = await conn.scalar(text(
                        "SELECT COUNT(*) FROM learning_goals "
                        "WHERE scope_type = 'global' AND metric = :metric"
                    ), {"metric": metric})
                    if not exists:
                        await conn.execute(text(
                            "INSERT INTO learning_goals "
                            "(id, scope_type, workspace_id, metric, target_value, target_date, "
                            "is_active, version, created_at, updated_at) VALUES "
                            "(:id, 'global', NULL, :metric, :target_value, NULL, 1, 1, "
                            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                        ), {"id": str(uuid.uuid4()), "metric": metric, "target_value": target_value})
    try:
        await conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5("
            "tokenized_content, heading, source_file, content='document_chunks', content_rowid='rowid')"
        ))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_fts_insert AFTER INSERT ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(rowid, tokenized_content, heading, source_file)
                VALUES (new.rowid, new.tokenized_content, new.heading, new.source_file);
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_fts_delete AFTER DELETE ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(document_chunks_fts, rowid, tokenized_content, heading, source_file)
                VALUES ('delete', old.rowid, old.tokenized_content, old.heading, old.source_file);
            END
        """))
        await conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS document_chunks_fts_update AFTER UPDATE ON document_chunks BEGIN
                INSERT INTO document_chunks_fts(document_chunks_fts, rowid, tokenized_content, heading, source_file)
                VALUES ('delete', old.rowid, old.tokenized_content, old.heading, old.source_file);
                INSERT INTO document_chunks_fts(rowid, tokenized_content, heading, source_file)
                VALUES (new.rowid, new.tokenized_content, new.heading, new.source_file);
            END
        """))
    except Exception as exc:
        logger.warning("SQLite FTS5 is unavailable; keyword retrieval will be disabled: {}", exc)
