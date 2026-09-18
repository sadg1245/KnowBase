"""AI 导师的长期记忆表与消息诊断列。

Revision ID: 0003_ai_tutor_memory
Revises: 0002_account_foundation
Create Date: 2026-09-18

迁移内容：
1. 新增 `learning_memories` 表与索引。
2. `conversations` 增加 `answer_policy`、`used_memory_ids`、`profile_summary`。
3. `chat_sessions.strict_sources` 保留，仅由应用层停止使用。

降级删除本 revision 新增的结构；不触碰既有数据。
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_ai_tutor_memory"
down_revision = "0002_account_foundation"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "learning_memories" not in _table_names():
        op.create_table(
            "learning_memories",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tokenized_content", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_refs", sa.JSON(), nullable=False),
            sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("embedding_state", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_learning_memories_user_id", "learning_memories", ["user_id"])
        op.create_index("ix_learning_memories_workspace_id", "learning_memories", ["workspace_id"])
        op.create_index("ix_learning_memories_kind", "learning_memories", ["kind"])
        op.create_index("ix_learning_memories_is_active", "learning_memories", ["is_active"])
        op.create_index("ix_learning_memories_last_used_at", "learning_memories", ["last_used_at"])
        op.create_index(
            "ix_learning_memories_user_workspace", "learning_memories", ["user_id", "workspace_id"]
        )
        op.create_index(
            "ix_learning_memories_user_kind", "learning_memories", ["user_id", "kind", "is_active"]
        )

    conversation_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("conversations")
    }
    if "answer_policy" not in conversation_columns:
        op.add_column("conversations", sa.Column("answer_policy", sa.String(20), nullable=True))
    if "used_memory_ids" not in conversation_columns:
        op.add_column("conversations", sa.Column("used_memory_ids", sa.JSON(), nullable=True))
    if "profile_summary" not in conversation_columns:
        op.add_column("conversations", sa.Column("profile_summary", sa.String(500), nullable=True))


def downgrade() -> None:
    conversation_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("conversations")
    }
    for name in ("profile_summary", "used_memory_ids", "answer_policy"):
        if name in conversation_columns:
            op.drop_column("conversations", name)
    if "learning_memories" in _table_names():
        op.drop_table("learning_memories")
