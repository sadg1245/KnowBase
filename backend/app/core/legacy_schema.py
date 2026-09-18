"""阶段一之前的完整结构快照（第一条 Alembic revision 的基线）。

该文件在迁移前冻结，不随 ORM 模型演进：它让全新数据库从旧结构起步，
也为旧数据库的引导校验提供唯一对照。
"""

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, text

legacy_metadata = MetaData()

chat_feedback = Table(
    'chat_feedback',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('message_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('helpful', sa.Boolean(), nullable=False),
        sa.Column('category', sa.String(30), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', 'user_id', name='uq_chat_feedback_message_user'),
        sa.ForeignKeyConstraint(['message_id'], ['conversations.id'], ondelete='CASCADE'),
)

sa.Index('ix_chat_feedback_message_id', chat_feedback.c["message_id"])

chat_sessions = Table(
    'chat_sessions',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('selected_document_ids', sa.JSON(), nullable=False),
        sa.Column('preferred_mode', sa.String(20), nullable=False),
        sa.Column('strict_sources', sa.Boolean(), nullable=False),
        sa.Column('is_favorite', sa.Boolean(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
)

sa.Index('ix_chat_sessions_is_favorite', chat_sessions.c["is_favorite"])
sa.Index('ix_chat_sessions_last_message_at', chat_sessions.c["last_message_at"])
sa.Index('ix_chat_sessions_user_activity', chat_sessions.c["user_id"], chat_sessions.c["last_message_at"])
sa.Index('ix_chat_sessions_user_id', chat_sessions.c["user_id"])
sa.Index('ix_chat_sessions_workspace_id', chat_sessions.c["workspace_id"])

conversations = Table(
    'conversations',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sources', sa.JSON(), nullable=True),
        sa.Column('mode', sa.String(20), nullable=True),
        sa.Column('evidence_status', sa.String(20), nullable=True),
        sa.Column('retrieval_run_id', sa.String(36), nullable=True),
        sa.Column('follow_up_questions', sa.JSON(), nullable=False),
        sa.Column('generation_status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['retrieval_run_id'], ['retrieval_runs.id'], ondelete='SET NULL'),
)

sa.Index('ix_conversations_retrieval_run_id', conversations.c["retrieval_run_id"])
sa.Index('ix_conversations_session_id', conversations.c["session_id"])
sa.Index('ix_conversations_user_id', conversations.c["user_id"])
sa.Index('ix_conversations_workspace_id', conversations.c["workspace_id"])

document_chunks = Table(
    'document_chunks',
    legacy_metadata,
        sa.Column('id', sa.String(255), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=False),
        sa.Column('source_file', sa.String(512), nullable=False),
        sa.Column('page_num', sa.Integer(), nullable=True),
        sa.Column('heading', sa.String(512), nullable=True),
        sa.Column('heading_level', sa.Integer(), nullable=True),
        sa.Column('section_path', sa.JSON(), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('tokenized_content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
)

sa.Index('ix_document_chunks_document_id', document_chunks.c["document_id"])
sa.Index('ix_document_chunks_workspace_document', document_chunks.c["workspace_id"], document_chunks.c["document_id"])
sa.Index('ix_document_chunks_workspace_id', document_chunks.c["workspace_id"])

documents = Table(
    'documents',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('file_path', sa.String(1024), nullable=False),
        sa.Column('file_type', sa.String(50), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('outline', sa.Text(), nullable=True),
        sa.Column('learning_status', sa.String(20), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('chapter_summaries', sa.JSON(), nullable=False),
        sa.Column('core_concepts', sa.JSON(), nullable=False),
        sa.Column('important_terms', sa.JSON(), nullable=False),
        sa.Column('common_mistakes', sa.JSON(), nullable=False),
        sa.Column('prerequisites', sa.JSON(), nullable=False),
        sa.Column('learning_order', sa.JSON(), nullable=False),
        sa.Column('review_points', sa.JSON(), nullable=False),
        sa.Column('learning_error_message', sa.Text(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('learning_generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
)

sa.Index('ix_documents_status', documents.c["status"])
sa.Index('ix_documents_workspace_id', documents.c["workspace_id"])

flashcards = Table(
    'flashcards',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('origin_message_id', sa.String(36), nullable=True),
        sa.Column('knowledge_point_id', sa.String(36), nullable=True),
        sa.Column('front', sa.Text(), nullable=False),
        sa.Column('back', sa.Text(), nullable=False),
        sa.Column('source_label', sa.String(512), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('difficulty', sa.Integer(), nullable=False),
        sa.Column('mastery', sa.Float(), nullable=False),
        sa.Column('mastery_status', sa.String(20), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('source_snapshot', sa.JSON(), nullable=True),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('ease', sa.Float(), nullable=False),
        sa.Column('review_count', sa.Integer(), nullable=False),
        sa.Column('algorithm_version', sa.String(20), nullable=False),
        sa.Column('scheduler_data', sa.JSON(), nullable=False),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_review_seconds', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['origin_message_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='CASCADE'),
)

sa.Index('ix_flashcards_due_at', flashcards.c["due_at"])
sa.Index('ix_flashcards_knowledge_point_id', flashcards.c["knowledge_point_id"])
sa.Index('ix_flashcards_mastery_status', flashcards.c["mastery_status"])
sa.Index('ix_flashcards_origin_message_id', flashcards.c["origin_message_id"], unique=True)
sa.Index('ix_flashcards_source_type', flashcards.c["source_type"])
sa.Index('ix_flashcards_workspace_id', flashcards.c["workspace_id"])

knowledge_points = Table(
    'knowledge_points',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('source_page', sa.Integer(), nullable=True),
        sa.Column('source_heading', sa.String(255), nullable=True),
        sa.Column('importance', sa.Integer(), nullable=False),
        sa.Column('difficulty', sa.Integer(), nullable=False),
        sa.Column('mastery', sa.Float(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False),
        sa.Column('is_key', sa.Boolean(), nullable=False),
        sa.Column('mastery_status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
)

sa.Index('ix_knowledge_points_document_id', knowledge_points.c["document_id"])
sa.Index('ix_knowledge_points_mastery_status', knowledge_points.c["mastery_status"])
sa.Index('ix_knowledge_points_workspace_id', knowledge_points.c["workspace_id"])

learning_goals = Table(
    'learning_goals',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('scope_type', sa.String(20), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('metric', sa.String(30), nullable=False),
        sa.Column('target_value', sa.Float(), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
)

sa.Index('ix_learning_goals_is_active', learning_goals.c["is_active"])
sa.Index('ix_learning_goals_metric', learning_goals.c["metric"])
sa.Index('ix_learning_goals_scope_type', learning_goals.c["scope_type"])
sa.Index('ix_learning_goals_workspace_id', learning_goals.c["workspace_id"])
sa.Index('uq_learning_goals_global_metric', learning_goals.c["metric"], unique=True, sqlite_where=text("scope_type = 'global'"), postgresql_where=text("scope_type = 'global'"))
sa.Index('uq_learning_goals_workspace_metric', learning_goals.c["workspace_id"], learning_goals.c["metric"], unique=True, sqlite_where=text("scope_type = 'workspace'"), postgresql_where=text("scope_type = 'workspace'"))

learning_notes = Table(
    'learning_notes',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('message_id', sa.String(36), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id', name='uq_learning_notes_message'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['conversations.id'], ondelete='SET NULL'),
)

sa.Index('ix_learning_notes_message_id', learning_notes.c["message_id"])
sa.Index('ix_learning_notes_session_id', learning_notes.c["session_id"])
sa.Index('ix_learning_notes_workspace_id', learning_notes.c["workspace_id"])

learning_tasks = Table(
    'learning_tasks',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('knowledge_point_id', sa.String(36), nullable=True),
        sa.Column('task_type', sa.String(30), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('path', sa.String(512), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='SET NULL'),
)

sa.Index('ix_learning_tasks_due_at', learning_tasks.c["due_at"])
sa.Index('ix_learning_tasks_knowledge_point_id', learning_tasks.c["knowledge_point_id"])
sa.Index('ix_learning_tasks_status', learning_tasks.c["status"])
sa.Index('ix_learning_tasks_workspace_id', learning_tasks.c["workspace_id"])
sa.Index('uq_learning_tasks_pending_point_type', learning_tasks.c["knowledge_point_id"], learning_tasks.c["task_type"], unique=True, sqlite_where=text("status = 'pending'"), postgresql_where=text("status = 'pending'"))

mistake_records = Table(
    'mistake_records',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('question_id', sa.String(36), nullable=False),
        sa.Column('knowledge_point_id', sa.String(36), nullable=True),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('latest_attempt_id', sa.String(36), nullable=True),
        sa.Column('user_answer_snapshot', sa.JSON(), nullable=True),
        sa.Column('correct_answer_snapshot', sa.JSON(), nullable=True),
        sa.Column('error_reason', sa.Text(), nullable=True),
        sa.Column('source_snapshot', sa.JSON(), nullable=False),
        sa.Column('wrong_count', sa.Integer(), nullable=False),
        sa.Column('redo_count', sa.Integer(), nullable=False),
        sa.Column('consecutive_correct', sa.Integer(), nullable=False),
        sa.Column('mastery_status', sa.String(20), nullable=False),
        sa.Column('first_wrong_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_wrong_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_redone_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', name='uq_mistake_records_question'),
        sa.ForeignKeyConstraint(['question_id'], ['quiz_questions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['latest_attempt_id'], ['quiz_attempts.id'], ondelete='SET NULL'),
)

sa.Index('ix_mistake_records_knowledge_point_id', mistake_records.c["knowledge_point_id"])
sa.Index('ix_mistake_records_mastery_status', mistake_records.c["mastery_status"])
sa.Index('ix_mistake_records_workspace_id', mistake_records.c["workspace_id"])

quiz_attempts = Table(
    'quiz_attempts',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('quiz_set_id', sa.String(36), nullable=False),
        sa.Column('quiz_run_id', sa.String(36), nullable=False),
        sa.Column('question_id', sa.String(36), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('user_answer', sa.JSON(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=True),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('max_score', sa.Float(), nullable=False),
        sa.Column('evaluation_status', sa.String(20), nullable=False),
        sa.Column('feedback', sa.JSON(), nullable=True),
        sa.Column('error_reason', sa.Text(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quiz_run_id', 'question_id', 'attempt_number', name='uq_quiz_attempts_run_question_number'),
        sa.ForeignKeyConstraint(['quiz_set_id'], ['quiz_sets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quiz_run_id'], ['quiz_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['question_id'], ['quiz_questions.id'], ondelete='CASCADE'),
)

sa.Index('ix_quiz_attempts_question_id', quiz_attempts.c["question_id"])
sa.Index('ix_quiz_attempts_quiz_run_id', quiz_attempts.c["quiz_run_id"])
sa.Index('ix_quiz_attempts_quiz_set_id', quiz_attempts.c["quiz_set_id"])

quiz_questions = Table(
    'quiz_questions',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('quiz_set_id', sa.String(36), nullable=True),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('origin_message_id', sa.String(36), nullable=True),
        sa.Column('knowledge_point_id', sa.String(36), nullable=True),
        sa.Column('question_type', sa.String(20), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('difficulty_level', sa.String(20), nullable=False),
        sa.Column('answer_payload', sa.JSON(), nullable=True),
        sa.Column('grading_rubric', sa.JSON(), nullable=True),
        sa.Column('source_snapshot', sa.JSON(), nullable=False),
        sa.Column('strict_sources', sa.Boolean(), nullable=False),
        sa.Column('generation_model', sa.String(255), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('source_label', sa.String(512), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('correct_attempts', sa.Integer(), nullable=False),
        sa.Column('last_answer', sa.Text(), nullable=True),
        sa.Column('last_correct', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quiz_set_id'], ['quiz_sets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['origin_message_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='SET NULL'),
)

sa.Index('ix_quiz_questions_document_id', quiz_questions.c["document_id"])
sa.Index('ix_quiz_questions_origin_message_id', quiz_questions.c["origin_message_id"], unique=True)
sa.Index('ix_quiz_questions_quiz_set_id', quiz_questions.c["quiz_set_id"])
sa.Index('ix_quiz_questions_workspace_id', quiz_questions.c["workspace_id"])

quiz_runs = Table(
    'quiz_runs',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('quiz_set_id', sa.String(36), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=False),
        sa.Column('answer_mode', sa.String(20), nullable=False),
        sa.Column('question_ids', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('elapsed_seconds', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('max_score', sa.Float(), nullable=False),
        sa.Column('correct_count', sa.Integer(), nullable=False),
        sa.Column('graded_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quiz_set_id', 'round_number', name='uq_quiz_runs_set_round'),
        sa.ForeignKeyConstraint(['quiz_set_id'], ['quiz_sets.id'], ondelete='CASCADE'),
)

sa.Index('ix_quiz_runs_quiz_set_id', quiz_runs.c["quiz_set_id"])

quiz_sets = Table(
    'quiz_sets',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('document_ids', sa.JSON(), nullable=False),
        sa.Column('knowledge_point_ids', sa.JSON(), nullable=False),
        sa.Column('section_filters', sa.JSON(), nullable=False),
        sa.Column('question_count', sa.Integer(), nullable=False),
        sa.Column('difficulty', sa.String(20), nullable=False),
        sa.Column('question_types', sa.JSON(), nullable=False),
        sa.Column('strict_sources', sa.Boolean(), nullable=False),
        sa.Column('answer_mode', sa.String(20), nullable=False),
        sa.Column('duration_limit_seconds', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('generation_model', sa.String(255), nullable=True),
        sa.Column('generation_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
)

sa.Index('ix_quiz_sets_workspace_id', quiz_sets.c["workspace_id"])

report_suggestions = Table(
    'report_suggestions',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('period_type', sa.String(10), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('timezone_name', sa.String(100), nullable=False),
        sa.Column('stats_hash', sa.String(64), nullable=False),
        sa.Column('stats_snapshot', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('suggestion', sa.Text(), nullable=True),
        sa.Column('model', sa.String(255), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('period_type', 'period_start', 'timezone_name', 'stats_hash', name='uq_report_suggestions_snapshot'),
)

sa.Index('ix_report_suggestions_period_start', report_suggestions.c["period_start"])
sa.Index('ix_report_suggestions_period_type', report_suggestions.c["period_type"])
sa.Index('ix_report_suggestions_status', report_suggestions.c["status"])

retrieval_hits = Table(
    'retrieval_hits',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('retrieval_run_id', sa.String(36), nullable=False),
        sa.Column('chunk_id', sa.String(255), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('source_file', sa.String(512), nullable=False),
        sa.Column('page_num', sa.Integer(), nullable=True),
        sa.Column('heading', sa.String(512), nullable=True),
        sa.Column('content_snapshot', sa.Text(), nullable=False),
        sa.Column('vector_rank', sa.Integer(), nullable=True),
        sa.Column('keyword_rank', sa.Integer(), nullable=True),
        sa.Column('vector_score', sa.Float(), nullable=False),
        sa.Column('keyword_score', sa.Float(), nullable=False),
        sa.Column('fusion_score', sa.Float(), nullable=False),
        sa.Column('rerank_score', sa.Float(), nullable=False),
        sa.Column('final_rank', sa.Integer(), nullable=True),
        sa.Column('selected_as_evidence', sa.Boolean(), nullable=False),
        sa.Column('cited_in_answer', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('retrieval_run_id', 'chunk_id', name='uq_retrieval_hit_run_chunk'),
        sa.ForeignKeyConstraint(['retrieval_run_id'], ['retrieval_runs.id'], ondelete='CASCADE'),
)

sa.Index('ix_retrieval_hits_chunk_id', retrieval_hits.c["chunk_id"])
sa.Index('ix_retrieval_hits_document_id', retrieval_hits.c["document_id"])
sa.Index('ix_retrieval_hits_retrieval_run_id', retrieval_hits.c["retrieval_run_id"])

retrieval_runs = Table(
    'retrieval_runs',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('session_id', sa.String(36), nullable=True),
        sa.Column('user_message_id', sa.String(36), nullable=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('document_ids', sa.JSON(), nullable=False),
        sa.Column('vector_succeeded', sa.Boolean(), nullable=False),
        sa.Column('keyword_succeeded', sa.Boolean(), nullable=False),
        sa.Column('degradation_reason', sa.Text(), nullable=True),
        sa.Column('vector_top_k', sa.Integer(), nullable=False),
        sa.Column('keyword_top_k', sa.Integer(), nullable=False),
        sa.Column('selected_top_k', sa.Integer(), nullable=False),
        sa.Column('config_snapshot', sa.JSON(), nullable=False),
        sa.Column('evidence_status', sa.String(20), nullable=False),
        sa.Column('top_score', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_message_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
)

sa.Index('ix_retrieval_runs_created_at', retrieval_runs.c["created_at"])
sa.Index('ix_retrieval_runs_session_id', retrieval_runs.c["session_id"])
sa.Index('ix_retrieval_runs_user_message_id', retrieval_runs.c["user_message_id"])
sa.Index('ix_retrieval_runs_workspace_id', retrieval_runs.c["workspace_id"])

review_logs = Table(
    'review_logs',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('card_id', sa.String(36), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('previous_interval', sa.Integer(), nullable=False),
        sa.Column('next_interval', sa.Integer(), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('previous_mastery', sa.Float(), nullable=False),
        sa.Column('next_mastery', sa.Float(), nullable=False),
        sa.Column('previous_status', sa.String(20), nullable=False),
        sa.Column('next_status', sa.String(20), nullable=False),
        sa.Column('algorithm_version', sa.String(20), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['card_id'], ['flashcards.id'], ondelete='CASCADE'),
)

sa.Index('ix_review_logs_card_id', review_logs.c["card_id"])
sa.Index('ix_review_logs_reviewed_at', review_logs.c["reviewed_at"])

study_activities = Table(
    'study_activities',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('activity_type', sa.String(30), nullable=False),
        sa.Column('event_key', sa.String(255), nullable=True),
        sa.Column('source_type', sa.String(40), nullable=True),
        sa.Column('source_id', sa.String(64), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('duration_seconds', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
)

sa.Index('ix_study_activities_activity_type', study_activities.c["activity_type"])
sa.Index('ix_study_activities_created_at', study_activities.c["created_at"])
sa.Index('ix_study_activities_event_key', study_activities.c["event_key"], unique=True)
sa.Index('ix_study_activities_occurred_at', study_activities.c["occurred_at"])
sa.Index('ix_study_activities_source_id', study_activities.c["source_id"])
sa.Index('ix_study_activities_source_type', study_activities.c["source_type"])
sa.Index('ix_study_activities_workspace_id', study_activities.c["workspace_id"])

study_sessions = Table(
    'study_sessions',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('context_type', sa.String(20), nullable=False),
        sa.Column('context_id', sa.String(36), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('active_seconds', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('last_sequence', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='SET NULL'),
)

sa.Index('ix_study_sessions_context_id', study_sessions.c["context_id"])
sa.Index('ix_study_sessions_status', study_sessions.c["status"])
sa.Index('ix_study_sessions_workspace_id', study_sessions.c["workspace_id"])
sa.Index('uq_study_sessions_active_context', study_sessions.c["context_type"], study_sessions.c["context_id"], unique=True, sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'"))

user_profiles = Table(
    'user_profiles',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('display_name', sa.String(80), nullable=False),
        sa.Column('daily_goal_minutes', sa.Integer(), nullable=False),
        sa.Column('daily_review_target', sa.Integer(), nullable=False),
        sa.Column('weekly_goal_days', sa.Integer(), nullable=False),
        sa.Column('timezone_name', sa.String(100), nullable=False),
        sa.Column('preferred_mode', sa.String(30), nullable=False),
        sa.Column('reminder_time', sa.String(5), nullable=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
)


weak_knowledge_states = Table(
    'weak_knowledge_states',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('knowledge_point_id', sa.String(36), nullable=False),
        sa.Column('workspace_id', sa.String(36), nullable=False),
        sa.Column('weakness_score', sa.Float(), nullable=False),
        sa.Column('accuracy_component', sa.Float(), nullable=False),
        sa.Column('repeat_error_component', sa.Float(), nullable=False),
        sa.Column('review_feedback_component', sa.Float(), nullable=False),
        sa.Column('response_time_component', sa.Float(), nullable=False),
        sa.Column('recency_component', sa.Float(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('recommended_actions', sa.JSON(), nullable=False),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('knowledge_point_id', name='uq_weak_knowledge_states_point'),
        sa.ForeignKeyConstraint(['knowledge_point_id'], ['knowledge_points.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
)

sa.Index('ix_weak_knowledge_states_weakness_score', weak_knowledge_states.c["weakness_score"])
sa.Index('ix_weak_knowledge_states_workspace_id', weak_knowledge_states.c["workspace_id"])

workspaces = Table(
    'workspaces',
    legacy_metadata,
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('learning_goal', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(100), nullable=True),
        sa.Column('accent_color', sa.String(20), nullable=False),
        sa.Column('archived', sa.Boolean(), nullable=False),
        sa.Column('slug', sa.String(255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
)

sa.Index('ix_workspaces_slug', workspaces.c["slug"], unique=True)

