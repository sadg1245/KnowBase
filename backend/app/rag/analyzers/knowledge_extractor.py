"""KnowledgeUnit 抽取：确定性规则，不再额外引入 LLM 调用（设计文档 §9.2）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.analyzers.structure_analyzer import StructureNodeData
from app.rag.contracts import Block

_DEFINITION_RE = re.compile(r"是指|称为|定义为|指的是|\bis defined as\b|\brefers to\b", re.I)
_EXAMPLE_RE = re.compile(r"^\s*(?:例\s*\d+|例题|example\s*\d*)", re.I)
_QUESTION_RE = re.compile(r"^\s*(?:第?\s*\d+[.、)）]|例\s*\d+|question\s*\d+)", re.I)

UNIT_TYPE_BY_NODE = {
    "document": "note",
    "chapter": "chapter",
    "section": "section",
    "formula": "formula",
    "code": "code",
    "table": "table",
    "image": "image",
    "question": "question",
    "solution": "solution",
    "answer": "answer",
    "example": "example",
}


@dataclass
class KnowledgeUnitData:
    unit_id: str
    document_id: str
    workspace_id: str
    parent_id: str | None
    unit_type: str
    title: str | None
    content: str
    subject: str | None = None
    chapter: str | None = None
    section: str | None = None
    difficulty: int | None = None
    source_node_id: str | None = None
    metadata: dict = field(default_factory=dict)


def _node_text(blocks: list[Block], node: StructureNodeData) -> str:
    return "\n\n".join(
        blocks[index].text()
        for index in range(node.block_start, min(node.block_end, len(blocks) - 1) + 1)
        if blocks[index].text()
    ).strip()


def extract_units(
    blocks: list[Block],
    nodes: list[StructureNodeData],
    *,
    document_id: str,
    workspace_id: str,
) -> list[KnowledgeUnitData]:
    """结构节点 → 知识单元；没有结构树时按块本身抽取。"""
    units: list[KnowledgeUnitData] = []
    by_id: dict[str, StructureNodeData] = {node.node_id: node for node in nodes}
    unit_by_node: dict[str, str] = {}
    chapter_title: str | None = None
    section_title: str | None = None

    def emit(
        *,
        unit_type: str,
        content: str,
        title: str | None = None,
        node: StructureNodeData | None = None,
        parent_id: str | None = None,
    ) -> None:
        if not content.strip():
            return
        unit_id = f"{document_id}:u{len(units)}"
        units.append(KnowledgeUnitData(
            unit_id=unit_id,
            document_id=document_id,
            workspace_id=workspace_id,
            parent_id=parent_id,
            unit_type=unit_type,
            title=title,
            content=content.strip(),
            chapter=chapter_title,
            section=section_title,
            source_node_id=node.node_id if node else None,
            metadata={
                "block_start": node.block_start if node else None,
                "block_end": node.block_end if node else None,
            },
        ))
        if node is not None:
            unit_by_node[node.node_id] = unit_id

    if not nodes:
        for index, block in enumerate(blocks):
            _emit_from_block(emit, block, index=index)
        return units

    for node in sorted(nodes, key=lambda item: item.order):
        if node.node_type == "document":
            continue
        parent_unit = unit_by_node.get(node.parent_node_id or "")
        content = _node_text(blocks, node)
        if node.node_type == "chapter":
            chapter_title = node.title
            section_title = None
            emit(unit_type="chapter", content=content or (node.title or ""), title=node.title,
                 node=node, parent_id=parent_unit)
            continue
        if node.node_type == "section":
            section_title = node.title
            emit(unit_type="section", content=content or (node.title or ""), title=node.title,
                 node=node, parent_id=parent_unit)
            continue
        unit_type = UNIT_TYPE_BY_NODE.get(node.node_type, "concept")
        if unit_type == "concept" and _DEFINITION_RE.search(content):
            unit_type = "definition"
        emit(unit_type=unit_type, content=content, title=node.title, node=node, parent_id=parent_unit)

    # 结构树遗漏的块（例如题目树里的散块）按块补抽，保证覆盖完整
    covered = {
        index
        for node in nodes
        for index in range(node.block_start, min(node.block_end, len(blocks) - 1) + 1)
    }
    for index, block in enumerate(blocks):
        if index in covered:
            continue
        _emit_from_block(emit, block, index=index)
    return units


def _emit_from_block(emit, block: Block, *, index: int) -> None:
    """块级兜底规则：定义句、例题、题干、答案、代码、公式。"""
    text = block.text()
    if not text:
        return
    if block.type == "formula":
        emit(unit_type="formula", content=text)
    elif block.type == "code":
        emit(unit_type="code", content=text)
    elif block.type == "table":
        emit(unit_type="table", content=text)
    elif block.type == "answer":
        emit(unit_type="answer", content=text)
    elif _EXAMPLE_RE.match(text):
        emit(unit_type="example", content=text, title=text[:120])
    elif block.type == "question" or _QUESTION_RE.match(text):
        emit(unit_type="question", content=text, title=text[:120])
    elif _DEFINITION_RE.search(text):
        emit(unit_type="definition", content=text, title=text[:120])
    else:
        emit(unit_type="concept", content=text)
