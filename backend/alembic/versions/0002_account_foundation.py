"""账号、所有权、学习领域与封面字段。

Revision ID: 0002_account_foundation
Revises: 0001_legacy_baseline
Create Date: 2026-09-17

迁移内容：
1. 新增 `users`、`learning_preferences`、`learning_domains`。
2. `user_profiles` 拆分：第一条资料复用其 id 作为用户 id，昵称/密码/时间字段进入
   `users`，学习偏好进入 `learning_preferences`。旧库没有资料时创建待首次设置的
   占位所有者。由于旧资料没有用户名，迁移后的账号使用用户名 `owner`。
3. `workspaces.owner_id` 非空并回填全部旧知识库；slug 唯一约束改为 (owner_id, slug)。
4. 旧 `workspaces.domain` 字符串按用户去重生成领域记录并回填 `domain_id`。
5. `study_activities`、`study_sessions`、`learning_goals`、`report_suggestions`
   增加 `user_id`；`conversations`、`chat_sessions`、`chat_feedback` 的历史
   `user_id` 改写为真实用户外键。
6. `knowledge_points.tags_locked` 记录人工标签，供重新生成时保留。
7. 删除已被取代的 `user_profiles` 表。

降级以保留数据为优先：本 revision 的 downgrade 只回滚纯新增结构，涉及所有者回填
与唯一约束变化的步骤不可逆，详见 `downgrade()`。
"""

import uuid

import sqlalchemy as sa
from alembic import op
from loguru import logger

revision = "0002_account_foundation"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None


PLACEHOLDER_USERNAME = "__pending_setup__"
MIGRATED_USERNAME = "owner"
USER_TABLES = ("study_activities", "study_sessions", "learning_goals", "report_suggestions")
OWNED_STRING_TABLES = ("conversations", "chat_sessions", "chat_feedback")


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _bind():
    return op.get_bind()


def _table_names() -> set[str]:
    return set(sa.inspect(_bind()).get_table_names())


def _create_account_tables() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("avatar_kind", sa.String(10), nullable=False, server_default="none"),
        sa.Column("avatar_value", sa.String(1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "learning_preferences",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("daily_goal_minutes", sa.Integer(), nullable=False, server_default="25"),
        sa.Column("daily_review_target", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("weekly_goal_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("timezone_name", sa.String(100), nullable=False, server_default="Asia/Shanghai"),
        sa.Column("preferred_mode", sa.String(30), nullable=False, server_default="explain"),
        sa.Column("reminder_time", sa.String(5), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "learning_domains",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(20), nullable=False, server_default="#1f7a8c"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "name", name="uq_learning_domains_user_name"),
    )
    op.create_index("ix_learning_domains_user_id", "learning_domains", ["user_id"])


def _insert_user(user_id: str, username: str, display_name: str, password_hash, created_at=None, updated_at=None):
    _bind().execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, display_name, avatar_kind, "
            "is_active, created_at, updated_at) VALUES (:id, :username, :password_hash, "
            ":display_name, 'none', :is_active, "
            "COALESCE(:created_at, CURRENT_TIMESTAMP), COALESCE(:updated_at, CURRENT_TIMESTAMP))"
        ),
        {
            "id": user_id,
            "username": username,
            "password_hash": password_hash,
            "display_name": display_name,
            "is_active": True,
            "created_at": created_at,
            "updated_at": updated_at,
        },
    )


def _insert_preferences(user_id: str, row) -> None:
    values = {
        "user_id": user_id,
        "daily_goal_minutes": 25,
        "daily_review_target": 10,
        "weekly_goal_days": 5,
        "timezone_name": "Asia/Shanghai",
        "preferred_mode": "explain",
        "reminder_time": "20:00",
    }
    if row is not None:
        values.update({
            "daily_goal_minutes": row.daily_goal_minutes,
            "daily_review_target": row.daily_review_target,
            "weekly_goal_days": row.weekly_goal_days,
            "timezone_name": row.timezone_name,
            "preferred_mode": row.preferred_mode,
            "reminder_time": row.reminder_time,
        })
    _bind().execute(
        sa.text(
            "INSERT INTO learning_preferences (user_id, daily_goal_minutes, "
            "daily_review_target, weekly_goal_days, timezone_name, preferred_mode, "
            "reminder_time, created_at, updated_at) VALUES (:user_id, :daily_goal_minutes, "
            ":daily_review_target, :weekly_goal_days, :timezone_name, :preferred_mode, "
            ":reminder_time, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        values,
    )


def _resolve_owner() -> str:
    """把现有 UserProfile 拆分为用户与学习偏好；没有资料时创建占位所有者。"""
    row = None
    if "user_profiles" in _table_names():
        row = _bind().execute(sa.text(
            "SELECT id, display_name, daily_goal_minutes, daily_review_target, "
            "weekly_goal_days, timezone_name, preferred_mode, reminder_time, "
            "password_hash, created_at, updated_at FROM user_profiles "
            "ORDER BY created_at LIMIT 1"
        )).first()
    if row is None:
        user_id = str(uuid.uuid4())
        _insert_user(user_id, PLACEHOLDER_USERNAME, "学习者", None)
        _insert_preferences(user_id, None)
        logger.info("No legacy profile found; created a placeholder owner awaiting first setup.")
        return user_id

    user_id = row.id
    _insert_user(
        user_id,
        MIGRATED_USERNAME,
        row.display_name or "学习者",
        row.password_hash,
        row.created_at,
        row.updated_at,
    )
    _insert_preferences(user_id, row)
    logger.info("Migrated the legacy profile into user '{}'.", user_id)
    return user_id


def _add_workspace_columns(owner_id: str) -> None:
    op.add_column("workspaces", sa.Column("owner_id", sa.String(36), nullable=True))
    op.add_column("workspaces", sa.Column("domain_id", sa.String(36), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("learning_status", sa.String(20), nullable=False, server_default="not_started"),
    )
    op.add_column(
        "workspaces",
        sa.Column("cover_kind", sa.String(10), nullable=False, server_default="none"),
    )
    op.add_column("workspaces", sa.Column("cover_value", sa.String(1024), nullable=True))
    _bind().execute(
        sa.text("UPDATE workspaces SET owner_id = :owner_id WHERE owner_id IS NULL"),
        {"owner_id": owner_id},
    )


def _convert_domains(owner_id: str) -> None:
    """旧 domain 字符串按用户去重生成领域；空值与“未分类”保持空关联。"""
    names = [
        row[0]
        for row in _bind().execute(sa.text(
            "SELECT DISTINCT domain FROM workspaces WHERE domain IS NOT NULL"
        )).fetchall()
    ]
    for raw in names:
        name = (raw or "").strip()
        if not name or name == "未分类":
            continue
        domain_id = str(uuid.uuid4())
        _bind().execute(
            sa.text(
                "INSERT INTO learning_domains (id, user_id, name, description, color, "
                "created_at, updated_at) VALUES (:id, :user_id, :name, '', '#1f7a8c', "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": domain_id, "user_id": owner_id, "name": name},
        )
        _bind().execute(
            sa.text(
                "UPDATE workspaces SET domain_id = :domain_id "
                "WHERE domain IS NOT NULL AND TRIM(domain) = :name"
            ),
            {"domain_id": domain_id, "name": name},
        )
    _bind().execute(sa.text(
        "UPDATE workspaces SET domain = '未分类' "
        "WHERE domain IS NULL OR TRIM(domain) = ''"
    ))


def _finalize_workspace_constraints() -> None:
    """owner_id 非空、外键、领域外键，以及 (owner_id, slug) 唯一约束。"""
    bind = _bind()
    inspector = sa.inspect(bind)
    index_names = {index["name"] for index in inspector.get_indexes("workspaces")}
    if "ix_workspaces_slug" in index_names:
        op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    if _sqlite():
        with op.batch_alter_table("workspaces", recreate="always") as batch:
            batch.alter_column("owner_id", existing_type=sa.String(36), nullable=False)
            batch.create_foreign_key(
                "fk_workspaces_owner_id", "users", ["owner_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_foreign_key(
                "fk_workspaces_domain_id", "learning_domains", ["domain_id"], ["id"],
                ondelete="SET NULL",
            )
            batch.create_unique_constraint(
                "uq_workspaces_owner_slug", ["owner_id", "slug"]
            )
    else:
        op.alter_column("workspaces", "owner_id", existing_type=sa.String(36), nullable=False)
        op.create_foreign_key(
            "fk_workspaces_owner_id", "workspaces", "users", ["owner_id"], ["id"],
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "fk_workspaces_domain_id", "workspaces", "learning_domains", ["domain_id"], ["id"],
            ondelete="SET NULL",
        )
        op.create_unique_constraint("uq_workspaces_owner_slug", "workspaces", ["owner_id", "slug"])
    op.create_index("ix_workspaces_owner_id", "workspaces", ["owner_id"])
    op.create_index("ix_workspaces_domain_id", "workspaces", ["domain_id"])


def _add_user_columns(owner_id: str) -> None:
    """用户级记录直接保存 user_id，并沿外键关系覆盖既有记录。"""
    for table in USER_TABLES:
        op.add_column(table, sa.Column("user_id", sa.String(36), nullable=True))
        _bind().execute(
            sa.text(f"UPDATE {table} SET user_id = :owner_id WHERE user_id IS NULL"),
            {"owner_id": owner_id},
        )
        if _sqlite():
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.alter_column("user_id", existing_type=sa.String(36), nullable=False)
                batch.create_foreign_key(
                    f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
                )
        else:
            op.alter_column(table, "user_id", existing_type=sa.String(36), nullable=False)
            op.create_foreign_key(
                f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE"
            )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])


def _rewrite_conversation_owners(owner_id: str) -> None:
    """历史 user_id 是任意字符串，必须改写为真实用户外键。"""
    for table in OWNED_STRING_TABLES:
        _bind().execute(
            sa.text(f"UPDATE {table} SET user_id = :owner_id WHERE user_id IS NULL OR user_id <> :owner_id"),
            {"owner_id": owner_id},
        )
        if _sqlite():
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.alter_column("user_id", existing_type=sa.String(255), type_=sa.String(36), nullable=False)
                batch.create_foreign_key(
                    f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
                )
        else:
            op.alter_column(
                table, "user_id", existing_type=sa.String(255), type_=sa.String(36), nullable=False
            )
            op.create_foreign_key(
                f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE"
            )


def _reshape_goal_and_suggestion_keys() -> None:
    """用户级唯一约束必须包含 user_id，否则多用户会互相冲突。"""
    op.drop_index("uq_learning_goals_global_metric", table_name="learning_goals")
    op.create_index(
        "uq_learning_goals_global_metric",
        "learning_goals",
        ["user_id", "metric"],
        unique=True,
        sqlite_where=sa.text("scope_type = 'global'"),
        postgresql_where=sa.text("scope_type = 'global'"),
    )
    if _sqlite():
        with op.batch_alter_table("report_suggestions", recreate="always") as batch:
            batch.drop_constraint("uq_report_suggestions_snapshot", type_="unique")
            batch.create_unique_constraint(
                "uq_report_suggestions_snapshot",
                ["user_id", "period_type", "period_start", "timezone_name", "stats_hash"],
            )
    else:
        op.drop_constraint("uq_report_suggestions_snapshot", "report_suggestions", type_="unique")
        op.create_unique_constraint(
            "uq_report_suggestions_snapshot",
            "report_suggestions",
            ["user_id", "period_type", "period_start", "timezone_name", "stats_hash"],
        )


def upgrade() -> None:
    _create_account_tables()
    owner_id = _resolve_owner()
    _add_workspace_columns(owner_id)
    _convert_domains(owner_id)
    _finalize_workspace_constraints()
    _add_user_columns(owner_id)
    _rewrite_conversation_owners(owner_id)
    op.add_column(
        "knowledge_points",
        sa.Column("tags_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _reshape_goal_and_suggestion_keys()
    if "user_profiles" in _table_names():
        op.drop_table("user_profiles")


def downgrade() -> None:
    """以保留数据为优先：只回滚纯新增结构。

    不可逆部分（必须从备份恢复才能回到旧结构）：
    - `user_profiles` 已拆分为 `users` 与 `learning_preferences`；
    - 知识库、文档与学习记录的所有者回填；
    - `workspaces` slug 唯一约束与 `report_suggestions` 唯一约束的变化。
    """
    op.drop_column("knowledge_points", "tags_locked")
    for table in USER_TABLES:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        if _sqlite():
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
                batch.drop_column("user_id")
        else:
            op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
            op.drop_column(table, "user_id")
    op.drop_index("ix_workspaces_domain_id", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_id", table_name="workspaces")
    op.drop_column("workspaces", "cover_value")
    op.drop_column("workspaces", "cover_kind")
    op.drop_column("workspaces", "learning_status")
    op.drop_column("workspaces", "domain_id")
    op.drop_column("workspaces", "owner_id")
    op.drop_index("ix_learning_domains_user_id", table_name="learning_domains")
    op.drop_table("learning_domains")
    op.drop_table("learning_preferences")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
