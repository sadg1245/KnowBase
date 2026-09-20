"""阶段 2 产物：结构树与知识单元（与 learning 层的 knowledge_points 分工不同）。"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, func

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StructureNode(Base):
    """`Document → Chapter → Section → (Concept | Formula | …)` 结构树节点。"""

    __tablename__ = "structure_nodes"

    id = Column(String(96), primary_key=True)
    document_id = Column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_node_id = Column(String(96), nullable=True, index=True)
    node_type = Column(String(20), nullable=False, index=True)
    title = Column(String(512), nullable=True)
    level = Column(Integer, nullable=False, default=0)
    order_index = Column(Integer, nullable=False, default=0)
    block_start = Column(Integer, nullable=False, default=0)
    block_end = Column(Integer, nullable=False, default=0)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())

    __table_args__ = (
        Index("ix_structure_nodes_document_order", "document_id", "order_index"),
    )


class KnowledgeUnit(Base):
    """检索与上下文构建使用的文档结构层单元。"""

    __tablename__ = "knowledge_units"

    id = Column(String(96), primary_key=True)
    document_id = Column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id = Column(String(96), nullable=True, index=True)
    unit_type = Column(String(20), nullable=False, index=True)
    title = Column(String(512), nullable=True)
    content = Column(Text, nullable=False, default="")
    subject = Column(String(128), nullable=True)
    chapter = Column(String(512), nullable=True)
    section = Column(String(512), nullable=True)
    difficulty = Column(Integer, nullable=True)
    source_node_id = Column(String(96), nullable=True, index=True)
    meta = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now, server_default=func.now())

    __table_args__ = (
        Index("ix_knowledge_units_document_type", "document_id", "unit_type"),
    )

