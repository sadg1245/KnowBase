"""文档结构层（阶段 2：分类、结构与知识单元）。

Revision ID: 0007_document_analysis
Revises: 0006_document_parse_quality
Create Date: 2026-09-19

迁移内容：
1. `documents` 增加 `document_type` / `classification_confidence` / `classification_meta`；
2. 新增 `structure_nodes`（结构树）与 `knowledge_units`（知识单元）；
3. `knowledge_points` 增加可空 `unit_id`（指向 `knowledge_units.id`，删除时置空）。

回填策略：历史文档 `document_type` 保持 NULL、`classification_meta` 为 `{}`，
表示「迁移前未分析」，不伪装成 unstructured；结构树与知识单元由重新索引重建。
降级删除新增表与列，不改动既有知识点数据。
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_document_analysis"
down_revision = "0006_document_parse_quality"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _columns("documents")
    if "document_type" not in existing:
        op.add_column("documents", sa.Column("document_type", sa.String(30), nullable=True))
    if "classification_confidence" not in existing:
        op.add_column("documents", sa.Column("classification_confidence", sa.Float(), nullable=True))
    if "classification_meta" not in existing:
        op.add_column(
            "documents",
            sa.Column("classification_meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )

    tables = _tables()
    if "structure_nodes" not in tables:
        op.create_table(
            "structure_nodes",
            sa.Column("id", sa.String(96), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_node_id", sa.String(96), nullable=True),
            sa.Column("node_type", sa.String(20), nullable=False),
            sa.Column("title", sa.String(512), nullable=True),
            sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("block_start", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("block_end", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("page_start", sa.Integer(), nullable=True),
            sa.Column("page_end", sa.Integer(), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_structure_nodes_document_id", "structure_nodes", ["document_id"])
        op.create_index("ix_structure_nodes_workspace_id", "structure_nodes", ["workspace_id"])
        op.create_index("ix_structure_nodes_parent_node_id", "structure_nodes", ["parent_node_id"])
        op.create_index("ix_structure_nodes_node_type", "structure_nodes", ["node_type"])
        op.create_index("ix_structure_nodes_document_order", "structure_nodes", ["document_id", "order_index"])

    if "knowledge_units" not in tables:
        op.create_table(
            "knowledge_units",
            sa.Column("id", sa.String(96), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_id", sa.String(96), nullable=True),
            sa.Column("unit_type", sa.String(20), nullable=False),
            sa.Column("title", sa.String(512), nullable=True),
            sa.Column("content", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("subject", sa.String(128), nullable=True),
            sa.Column("chapter", sa.String(512), nullable=True),
            sa.Column("section", sa.String(512), nullable=True),
            sa.Column("difficulty", sa.Integer(), nullable=True),
            sa.Column("source_node_id", sa.String(96), nullable=True),
            sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_knowledge_units_document_id", "knowledge_units", ["document_id"])
        op.create_index("ix_knowledge_units_workspace_id", "knowledge_units", ["workspace_id"])
        op.create_index("ix_knowledge_units_parent_id", "knowledge_units", ["parent_id"])
        op.create_index("ix_knowledge_units_unit_type", "knowledge_units", ["unit_type"])
        op.create_index("ix_knowledge_units_source_node_id", "knowledge_units", ["source_node_id"])
        op.create_index("ix_knowledge_units_document_type", "knowledge_units", ["document_id", "unit_type"])

    if "unit_id" not in _columns("knowledge_points"):
        with op.batch_alter_table("knowledge_points") as batch:
            batch.add_column(sa.Column("unit_id", sa.String(96), nullable=True))
            batch.create_index("ix_knowledge_points_unit_id", ["unit_id"])


def downgrade() -> None:
    if "unit_id" in _columns("knowledge_points"):
        with op.batch_alter_table("knowledge_points") as batch:
            batch.drop_index("ix_knowledge_points_unit_id")
            batch.drop_column("unit_id")

    tables = _tables()
    if "knowledge_units" in tables:
        for index in (
            "ix_knowledge_units_document_type", "ix_knowledge_units_source_node_id",
            "ix_knowledge_units_unit_type", "ix_knowledge_units_parent_id",
            "ix_knowledge_units_workspace_id", "ix_knowledge_units_document_id",
        ):
            op.drop_index(index, table_name="knowledge_units")
        op.drop_table("knowledge_units")
    if "structure_nodes" in tables:
        for index in (
            "ix_structure_nodes_document_order", "ix_structure_nodes_node_type",
            "ix_structure_nodes_parent_node_id", "ix_structure_nodes_workspace_id",
            "ix_structure_nodes_document_id",
        ):
            op.drop_index(index, table_name="structure_nodes")
        op.drop_table("structure_nodes")

    existing = _columns("documents")
    for column in ("classification_meta", "classification_confidence", "document_type"):
        if column in existing:
            with op.batch_alter_table("documents") as batch:
                batch.drop_column(column)
