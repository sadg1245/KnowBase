"""RAG 统一数据契约：Document / Block / ParseQuality。

入库流水线的所有解析器都必须输出 `Document`（含 `Block[]`），这样分类、结构分析、
切分、富化与多向量索引才能共享同一份结构，而不是各自猜文本格式。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

BlockType = Literal[
    "heading", "paragraph", "list", "code", "formula",
    "table", "image", "question", "answer", "quote", "caption",
]

# 公式、表格、代码块不可被切分（ChunkValidator 的原子块约束）。
ATOMIC_BLOCK_TYPES: frozenset[str] = frozenset({"formula", "table", "code"})


class Block(BaseModel):
    """文档的最小结构单元。"""

    block_id: str
    type: BlockType
    content: str
    order: int
    page: int | None = None
    heading_level: int | None = None
    section_path: list[str] = Field(default_factory=list)
    latex: str | None = None
    language: str | None = None
    table: list[list[str]] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_atomic(self) -> bool:
        """原子块在切分时不可被打断。"""
        return self.type in ATOMIC_BLOCK_TYPES

    def text(self) -> str:
        """用于向量化与展示的文本；公式优先使用 latex。"""
        return (self.latex or self.content or "").strip()


class ParseQuality(BaseModel):
    """解析质量：扫描件、公式密集与降级路径都必须显式记录，不能静默通过。"""

    scanned: bool = False
    formula_heavy: bool = False
    degraded: str | None = None
    page_count: int = 0
    empty_page_count: int = 0
    extractable_chars: int = 0
    text_ratio: float | None = None
    signature: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def is_scanned_document(self) -> bool:
        return self.degraded == "scanned_pdf"


class Document(BaseModel):
    """一份已解析文档：结构（Block[]）+ 质量（ParseQuality）+ 来源元数据。"""

    document_id: str
    workspace_id: str
    filename: str
    file_type: str
    title: str | None = None
    document_type: str | None = None
    classification_confidence: float | None = None
    blocks: list[Block] = Field(default_factory=list)
    quality: ParseQuality = Field(default_factory=ParseQuality)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def text_length(self) -> int:
        return sum(len(block.text()) for block in self.blocks)

    def section_path_at(self, order: int) -> list[str]:
        """返回第 *order* 个块所处的小节路径（不含块自身标题）。"""
        for block in self.blocks:
            if block.order == order:
                return list(block.section_path)
        return []

    def page_count(self) -> int:
        return len({block.page for block in self.blocks if block.page})

