"""文档解析质量列（阶段 1：统一文档模型与解析层）。

Revision ID: 0006_document_parse_quality
Revises: 0005_learning_scope
Create Date: 2026-09-19

迁移内容：`documents` 增加 `parse_degraded` 与 `parse_quality`。
回填策略：历史文档保持 `NULL` / `{}`，表示「迁移前未记录解析质量」，
不伪装成「已检查且正常」。降级删除本 revision 新增的列。
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_document_parse_quality"
down_revision = "0005_learning_scope"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _columns("documents")
    if "parse_degraded" not in existing:
        op.add_column("documents", sa.Column("parse_degraded", sa.String(30), nullable=True))
    if "parse_quality" not in existing:
        op.add_column(
            "documents",
            sa.Column("parse_quality", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )


def downgrade() -> None:
    existing = _columns("documents")
    if "parse_quality" in existing:
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("parse_quality")
    if "parse_degraded" in existing:
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("parse_degraded")
