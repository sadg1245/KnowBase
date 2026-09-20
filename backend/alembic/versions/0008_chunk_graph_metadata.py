"""Chunk 结构层与元数据（阶段 3：切分、Parent-Child、富化字段）。

Revision ID: 0008_chunk_graph_metadata
Revises: 0007_document_analysis
Create Date: 2026-09-19

迁移内容：`document_chunks` 增加 `unit_id / parent_id / chunk_level / content_type /
document_type / subject / summary / keywords / knowledge_points / difficulty /
page_end / enrichment_status / index_version / metadata`。

回填策略：历史 chunk 一律按 `chunk_level='child'`、`content_type='concept'`、
`enrichment_status='skipped'`、`index_version=1` 回填——它们确实来自旧切分与旧索引
版本，标记成新版本会掩盖「需要重建」。FTS5 虚拟表与触发器不变，因此不需要重建全文索引。
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_chunk_graph_metadata"
down_revision = "0007_document_analysis"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


_COLUMNS = (
    ("unit_id", sa.String(96), None),
    ("parent_id", sa.String(255), None),
    ("chunk_level", sa.String(10), "child"),
    ("content_type", sa.String(32), "concept"),
    ("document_type", sa.String(32), None),
    ("subject", sa.String(128), None),
    ("summary", sa.Text(), None),
    ("keywords", sa.JSON(), "'[]'"),
    ("knowledge_points", sa.JSON(), "'[]'"),
    ("difficulty", sa.Integer(), None),
    ("page_end", sa.Integer(), None),
    ("enrichment_status", sa.String(16), "skipped"),
    ("index_version", sa.Integer(), "1"),
    ("metadata", sa.JSON(), "'{}'"),
)


def upgrade() -> None:
    existing = _columns("document_chunks")
    for name, column_type, default in _COLUMNS:
        if name in existing:
            continue
        kwargs = {"nullable": default is None}
        if default is not None:
            kwargs["nullable"] = False
            kwargs["server_default"] = sa.text(default)
        op.add_column("document_chunks", sa.Column(name, column_type, **kwargs))
    for index_name, columns in (
        ("ix_document_chunks_unit_id", ["unit_id"]),
        ("ix_document_chunks_parent_id", ["parent_id"]),
        ("ix_document_chunks_chunk_level", ["chunk_level"]),
        ("ix_document_chunks_content_type", ["content_type"]),
        ("ix_document_chunks_document_type", ["document_type"]),
    ):
        try:
            op.create_index(index_name, "document_chunks", columns)
        except Exception:  # 索引可能已存在（重复升级场景）
            continue


def downgrade() -> None:
    existing = _columns("document_chunks")
    with op.batch_alter_table("document_chunks") as batch:
        for name, _type, _default in reversed(_COLUMNS):
            if name in existing:
                batch.drop_column(name)
