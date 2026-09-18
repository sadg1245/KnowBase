"""入库阶段事件与文档阶段列。

Revision ID: 0004_rag_pipeline_events
Revises: 0003_ai_tutor_memory
Create Date: 2026-09-18

迁移内容：
1. `documents` 增加可空 `pipeline_stage`。
2. 新建 `document_pipeline_events` 表与索引。

降级删除本 revision 新增的结构；不触碰既有数据。
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_rag_pipeline_events"
down_revision = "0003_ai_tutor_memory"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    document_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")
    }
    if "pipeline_stage" not in document_columns:
        op.add_column("documents", sa.Column("pipeline_stage", sa.String(20), nullable=True))

    if "document_pipeline_events" not in _table_names():
        op.create_table(
            "document_pipeline_events",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("document_id", sa.String(36), nullable=False),
            sa.Column("node", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_document_pipeline_events_document_id",
            "document_pipeline_events",
            ["document_id"],
        )
        op.create_index(
            "ix_document_pipeline_events_document_node",
            "document_pipeline_events",
            ["document_id", "node"],
        )


def downgrade() -> None:
    if "document_pipeline_events" in _table_names():
        op.drop_table("document_pipeline_events")
    document_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")
    }
    if "pipeline_stage" in document_columns:
        op.drop_column("documents", "pipeline_stage")
