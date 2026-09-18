"""阶段一之前的完整结构基线。

Revision ID: 0001_legacy_baseline
Revises:
Create Date: 2026-09-17

全新数据库从该基线创建全部既有表，随后执行账号基础 revision。
已有数据库如果存在核心表但没有 `alembic_version`，由受控引导命令校验结构后
登记该基线（见 `app/core/db_bootstrap.py`），不能仅凭“表存在”盲目 stamp。
"""

from alembic import op

from app.core.legacy_schema import legacy_metadata

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    legacy_metadata.create_all(bind, checkfirst=True)


def downgrade() -> None:
    """基线降级等同于清空本阶段之前的所有结构。"""
    bind = op.get_bind()
    legacy_metadata.drop_all(bind, checkfirst=True)
