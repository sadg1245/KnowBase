"""检索命中记录命中的向量种类（阶段 3：多向量归并审计）。

Revision ID: 0009_retrieval_vector_kinds
Revises: 0008_chunk_graph_metadata
Create Date: 2026-09-19

迁移内容：`retrieval_hits` 增加 `vector_kinds`（JSON，默认 `[]`）。
回填策略：历史命中没有多向量信息，保持空数组，表示「单 content 向量时代的记录」。
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_retrieval_vector_kinds"
down_revision = "0008_chunk_graph_metadata"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "vector_kinds" in _columns("retrieval_hits"):
        return
    op.add_column(
        "retrieval_hits",
        sa.Column("vector_kinds", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    if "vector_kinds" in _columns("retrieval_hits"):
        with op.batch_alter_table("retrieval_hits") as batch:
            batch.drop_column("vector_kinds")

