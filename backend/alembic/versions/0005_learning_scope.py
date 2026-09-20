"""学习范围（RetrievalScope）契约列与历史数据回填。

Revision ID: 0005_learning_scope
Revises: 0004_rag_pipeline_events
Create Date: 2026-09-18

迁移内容：
1. `chat_sessions` 增加 `scope_mode` / `scope_config`。
2. `retrieval_runs` 增加范围审计字段。
3. `retrieval_hits` 增加 `profile_bonus`。

回填策略（关键）：
迁移前的行为 = 单知识库 + 可选文件过滤 + 从不扩展，等价于 `strict`。
因此默认值必须是 `strict`，否则迁移瞬间会改变所有历史会话的检索行为。

降级删除本 revision 新增的结构；不触碰既有数据。
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0005_learning_scope"
down_revision = "0004_rag_pipeline_events"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add_column(
        "chat_sessions",
        sa.Column("scope_mode", sa.String(32), nullable=False, server_default="strict"),
    )
    _add_column(
        "chat_sessions",
        sa.Column("scope_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    _add_column("retrieval_runs", sa.Column("scope_mode", sa.String(32), nullable=True))
    _add_column(
        "retrieval_runs",
        sa.Column("scope_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _add_column(
        "retrieval_runs",
        sa.Column("scope_resolution", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _add_column(
        "retrieval_runs",
        sa.Column("expansion_rounds", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column(
        "retrieval_runs",
        sa.Column("expanded_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    _add_column(
        "retrieval_hits",
        sa.Column("profile_bonus", sa.Float(), nullable=False, server_default=sa.text("0")),
    )

    _backfill_legacy_sessions()


def _backfill_legacy_sessions() -> None:
    """把迁移前的 selected_document_ids / workspace_id 映射进 scope_config。"""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, workspace_id, selected_document_ids, scope_mode, scope_config "
            "FROM chat_sessions"
        )
    ).mappings().all()
    for row in rows:
        existing = row["scope_config"]
        if isinstance(existing, str):
            try:
                existing = json.loads(existing)
            except (TypeError, ValueError):
                existing = {}
        if isinstance(existing, dict) and existing:
            continue
        documents = row["selected_document_ids"]
        if isinstance(documents, str):
            try:
                documents = json.loads(documents)
            except (TypeError, ValueError):
                documents = []
        if documents:
            payload = {"document_ids": list(documents)}
            mode = "strict"
        elif row["workspace_id"]:
            payload = {"workspace_ids": [row["workspace_id"]]}
            mode = "strict"
        else:
            payload = {}
            mode = "smart"
        bind.execute(
            sa.text(
                "UPDATE chat_sessions SET scope_mode = :mode, scope_config = :config "
                "WHERE id = :id"
            ),
            {"mode": mode, "config": json.dumps(payload, ensure_ascii=False), "id": row["id"]},
        )


def downgrade() -> None:
    for table, column in (
        ("retrieval_hits", "profile_bonus"),
        ("retrieval_runs", "expanded_scope"),
        ("retrieval_runs", "expansion_rounds"),
        ("retrieval_runs", "scope_resolution"),
        ("retrieval_runs", "scope_snapshot"),
        ("retrieval_runs", "scope_mode"),
        ("chat_sessions", "scope_config"),
        ("chat_sessions", "scope_mode"),
    ):
        if column in _columns(table):
            op.drop_column(table, column)
