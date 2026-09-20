"""阶段 2 分析结果的幂等落库：重新索引时整篇重建，避免残留旧结构。"""

from __future__ import annotations

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.rag import KnowledgeUnit, StructureNode
from app.rag.analyzers.document_classifier import ClassificationResult
from app.rag.analyzers.knowledge_extractor import KnowledgeUnitData
from app.rag.analyzers.structure_analyzer import StructureNodeData


async def persist_document_analysis(
    db: AsyncSession,
    *,
    document_id: str,
    workspace_id: str,
    classification: ClassificationResult,
    nodes: list[StructureNodeData],
    units: list[KnowledgeUnitData],
) -> None:
    """写入结构树与知识单元，并更新文档分类列。"""
    await db.execute(delete(StructureNode).where(StructureNode.document_id == document_id))
    await db.execute(delete(KnowledgeUnit).where(KnowledgeUnit.document_id == document_id))

    for node in nodes:
        db.add(StructureNode(
            id=node.node_id,
            document_id=document_id,
            workspace_id=workspace_id,
            parent_node_id=node.parent_node_id,
            node_type=node.node_type,
            title=node.title,
            level=node.level,
            order_index=node.order,
            block_start=node.block_start,
            block_end=node.block_end,
            page_start=node.page_start,
            page_end=node.page_end,
            meta=dict(node.metadata or {}),
        ))
    for unit in units:
        db.add(KnowledgeUnit(
            id=unit.unit_id,
            document_id=document_id,
            workspace_id=workspace_id,
            parent_id=unit.parent_id,
            unit_type=unit.unit_type,
            title=unit.title,
            content=unit.content,
            subject=unit.subject,
            chapter=unit.chapter,
            section=unit.section,
            difficulty=unit.difficulty,
            source_node_id=unit.source_node_id,
            meta=dict(unit.metadata or {}),
        ))

    await db.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(
            document_type=classification.document_type,
            classification_confidence=classification.confidence,
            classification_meta=classification.meta,
        )
    )
    await db.flush()
