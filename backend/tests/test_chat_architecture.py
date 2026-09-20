"""Architecture contracts for persistent learning conversations and retrieval audit."""

import unittest

import app.models  # noqa: F401 - register all model metadata
from app.models.base import Base


class ChatArchitectureTests(unittest.TestCase):
    def test_learning_conversation_tables_are_registered(self):
        expected = {
            "chat_sessions",
            "learning_notes",
            "chat_feedback",
            "document_chunks",
            "retrieval_runs",
            "retrieval_hits",
        }

        self.assertTrue(expected.issubset(Base.metadata.tables))

    def test_chat_sessions_keep_scope_and_lifecycle_state(self):
        table = Base.metadata.tables.get("chat_sessions")
        if table is None:
            self.fail("chat_sessions is not registered")
        columns = table.columns

        for name in (
            "workspace_id",
            "title",
            "preferred_mode",
            "strict_sources",
            "selected_document_ids",
            "scope_mode",
            "scope_config",
            "is_favorite",
            "created_at",
            "updated_at",
        ):
            with self.subTest(column=name):
                self.assertIn(name, columns)

    def test_retrieval_runs_keep_scope_audit_columns(self):
        columns = Base.metadata.tables["retrieval_runs"].columns

        for name in (
            "scope_mode",
            "scope_snapshot",
            "scope_resolution",
            "expansion_rounds",
            "expanded_scope",
        ):
            with self.subTest(column=name):
                self.assertIn(name, columns)

    def test_messages_keep_session_and_evidence_metadata(self):
        columns = Base.metadata.tables["conversations"].columns

        for name in (
            "session_id",
            "mode",
            "evidence_status",
            "retrieval_run_id",
            "answer_policy",
            "used_memory_ids",
            "profile_summary",
        ):
            with self.subTest(column=name):
                self.assertIn(name, columns)

    def test_retrieval_hits_keep_rank_and_component_scores(self):
        table = Base.metadata.tables.get("retrieval_hits")
        if table is None:
            self.fail("retrieval_hits is not registered")
        columns = table.columns

        for name in (
            "retrieval_run_id",
            "chunk_id",
            "vector_rank",
            "keyword_rank",
            "vector_score",
            "keyword_score",
            "rerank_score",
            "profile_bonus",
            "selected_as_evidence",
        ):
            with self.subTest(column=name):
                self.assertIn(name, columns)


if __name__ == "__main__":
    unittest.main()
