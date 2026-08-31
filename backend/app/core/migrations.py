"""Small, idempotent compatibility migrations for existing SQLite installs.

The project still supports PostgreSQL through normal schema creation.  These
ALTER statements only bridge older local SQLite databases created before the
learning fields existed.
"""

from loguru import logger
from sqlalchemy import text


async def run_compat_migrations(conn) -> None:
    if conn.dialect.name != "sqlite":
        return

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
    }
    for table, columns in additions.items():
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing = {row[1] for row in rows.fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))

    await conn.execute(text(
        "UPDATE flashcards SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
    ))

    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_flashcards_origin_message_id "
        "ON flashcards(origin_message_id) WHERE origin_message_id IS NOT NULL"
    ))
    await conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_quiz_questions_origin_message_id "
        "ON quiz_questions(origin_message_id) WHERE origin_message_id IS NOT NULL"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_flashcards_mastery_status ON flashcards(mastery_status)"
    ))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_flashcards_source_type ON flashcards(source_type)"
    ))
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
