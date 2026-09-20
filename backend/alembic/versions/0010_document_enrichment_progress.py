"""文档富化进度列（阶段 3：富化从入库主链路拆出）。

Revision ID: 0010_document_enrichment_progress
Revises: 0009_retrieval_vector_kinds
Create Date: 2026-09-19

迁移内容：`documents` 增加 `enrichment_state` 与 `enrichment_progress`。
回填策略：历史文档保持 NULL / `{}`，表示「迁移前没有后台富化这一阶段」，
不伪装成已完成；需要补富化时走 `POST /api/documents/{id}/enrich`。
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_document_enrichment_progress"
down_revision = "0009_retrieval_vector_kinds"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _columns("documents")
    if "enrichment_state" not in existing:
        op.add_column("documents", sa.Column("enrichment_state", sa.String(20), nullable=True))
    if "enrichment_progress" not in existing:
        op.add_column(
            "documents",
            sa.Column("enrichment_progress", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    existing = _columns("documents")
    for column in ("enrichment_progress", "enrichment_state"):
        if column in existing:
            with op.batch_alter_table("documents") as batch:
                batch.drop_column(column)
