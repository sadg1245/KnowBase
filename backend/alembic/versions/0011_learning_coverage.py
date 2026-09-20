"""学习内容覆盖率（学习内容生成的两级降级）。

Revision ID: 0011_learning_coverage
Revises: 0010_document_enrichment_progress
Create Date: 2026-09-19

迁移内容：`documents` 增加 `learning_coverage`（JSON，默认 `{}`）。
回填策略：历史文档保持 `{}`，表示「迁移前没有覆盖率记录」；`learning_status`
可能取值为 `partial`（部分章节生成成功），旧值语义不变。
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_learning_coverage"
down_revision = "0010_document_enrichment_progress"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "learning_coverage" in _columns("documents"):
        return
    op.add_column(
        "documents",
        sa.Column("learning_coverage", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    if "learning_coverage" in _columns("documents"):
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("learning_coverage")
