"""Structure Analyzer：把 Block[] 组装成结构树。

两类模板（设计文档 §8）：

```text
textbook / notes / tutorial：Document → Chapter → Section → (Concept | Formula | Example | Code | Table)
exam：                      Document → Question → (Solution | Answer)
```

没有任何标题且不是题目集时返回空列表：文档整体走 Semantic 切分，属于允许的降级，
但不会写入半截结构树。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.contracts import Block

HEADING_TYPES = frozenset({"textbook", "notes", "tutorial", "documentation", "slides"})
LEAF_NODE_TYPES = {
    "formula": "formula",
    "example": "example",
    "code": "code",
    "table": "table",
    "image": "image",
    "question": "question",
    "answer": "answer",
}


@dataclass
class StructureNodeData:
    node_id: str
    parent_node_id: str | None
    node_type: str
    title: str | None
    level: int
    order: int
    block_start: int
    block_end: int
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict = field(default_factory=dict)


def _leaf_type(block: Block) -> str:
    if block.type == "list":
        return "concept"
    return LEAF_NODE_TYPES.get(block.type, "concept")


def build_structure(
    blocks: list[Block], *, document_type: str, document_id: str
) -> list[StructureNodeData]:
    """返回按 order 排序的结构节点；根节点始终是 document。"""
    if not blocks:
        return []
    if document_type == "exam":
        return _build_exam_tree(blocks, document_id=document_id)
    has_question = any(block.type in {"question", "answer"} for block in blocks)
    if has_question:
        return _build_exam_tree(blocks, document_id=document_id)
    if document_type not in HEADING_TYPES or not any(block.type == "heading" for block in blocks):
        return []
    return _build_heading_tree(blocks, document_id=document_id)


def _spans(blocks: list[Block], start: int, end: int) -> tuple[int | None, int | None]:
    pages = [blocks[index].page for index in range(start, end + 1) if blocks[index].page]
    return (min(pages), max(pages)) if pages else (None, None)


def _build_heading_tree(blocks: list[Block], *, document_id: str) -> list[StructureNodeData]:
    nodes: list[StructureNodeData] = []

    def add(node_type: str, parent: str | None, title: str | None, level: int,
            start: int, end: int) -> str:
        node_id = f"{document_id}:n{len(nodes)}"
        page_start, page_end = _spans(blocks, start, end)
        nodes.append(StructureNodeData(
            node_id=node_id,
            parent_node_id=parent,
            node_type=node_type,
            title=title,
            level=level,
            order=len(nodes),
            block_start=start,
            block_end=end,
            page_start=page_start,
            page_end=page_end,
        ))
        return node_id

    root = add("document", None, None, 0, 0, len(blocks) - 1)
    stack: list[tuple[int, str]] = [(0, root)]  # (level, node_id)
    leaf_start: int | None = None
    leaf_type: str | None = None
    leaf_parent: str | None = None

    def flush_leaf(end: int) -> None:
        nonlocal leaf_start, leaf_type, leaf_parent
        if leaf_start is not None:
            parent_level = next(
                (node.level for node in nodes if node.node_id == leaf_parent), 0
            )
            add(leaf_type or "concept", leaf_parent, None, parent_level + 1, leaf_start, end)
        leaf_start, leaf_type, leaf_parent = None, None, None

    for index, block in enumerate(blocks):
        if block.type == "heading":
            flush_leaf(index - 1)
            level = max(1, block.heading_level or 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else root
            node_type = "chapter" if level == 1 else "section"
            node_id = add(node_type, parent, block.content, level, index, index)
            stack.append((level, node_id))
            continue
        mapped = _leaf_type(block)
        parent = stack[-1][1] if stack else root
        if leaf_start is None:
            leaf_start, leaf_type, leaf_parent = index, mapped, parent
        elif mapped != leaf_type or parent != leaf_parent:
            flush_leaf(index - 1)
            leaf_start, leaf_type, leaf_parent = index, mapped, parent
    flush_leaf(len(blocks) - 1)

    # 父节点跨到最后一个子节点的末尾，便于 Parent Expansion 取整节原文
    # 自底向上聚合，父节点才能拿到所有子节点的最终跨度
    for node in reversed(nodes):
        children = [child for child in nodes if child.parent_node_id == node.node_id]
        if children:
            node.block_end = max(child.block_end for child in children)
            page_start, page_end = _spans(blocks, node.block_start, node.block_end)
            node.page_start, node.page_end = page_start, page_end
    return nodes


def _build_exam_tree(blocks: list[Block], *, document_id: str) -> list[StructureNodeData]:
    nodes: list[StructureNodeData] = []

    def add(node_type: str, parent: str | None, title: str | None, level: int,
            start: int, end: int) -> str:
        node_id = f"{document_id}:n{len(nodes)}"
        page_start, page_end = _spans(blocks, start, end)
        nodes.append(StructureNodeData(
            node_id=node_id,
            parent_node_id=parent,
            node_type=node_type,
            title=title,
            level=level,
            order=len(nodes),
            block_start=start,
            block_end=end,
            page_start=page_start,
            page_end=page_end,
        ))
        return node_id

    root = add("document", None, None, 0, 0, len(blocks) - 1)
    current_question: str | None = None
    for index, block in enumerate(blocks):
        if block.type == "heading" and block.heading_level == 1:
            current_question = add("question", root, block.content, 1, index, index)
            continue
        if block.type == "question":
            current_question = add("question", root, block.content[:120], 1, index, index)
            continue
        if block.type in {"answer", "solution"}:
            parent = current_question or root
            add("solution" if block.type == "solution" else "answer", parent,
                block.content[:120], 2, index, index)
            if current_question:
                question_node = next(node for node in nodes if node.node_id == current_question)
                question_node.block_end = max(question_node.block_end, index)
            continue
        parent = current_question or root
        add("concept", parent, None, 2 if current_question else 1, index, index)
    return nodes
