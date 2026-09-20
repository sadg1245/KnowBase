"""切分层契约：Chunk、切分上下文与策略接口。

Token 口径（设计文档 §10.4）：以 embedding 模型自带 tokenizer 为准；模型未加载时
使用中英混合估算器——CJK 字符计 1 token，拉丁词计 1.3 token。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.rag.analyzers.knowledge_extractor import KnowledgeUnitData
from app.rag.analyzers.structure_analyzer import StructureNodeData
from app.rag.contracts import Block, Document

MIN_CHUNK_TOKENS = 150
TARGET_CHUNK_TOKENS = 600
MAX_CHUNK_TOKENS = 1200

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_'\-]*")


def estimate_tokens(text: str) -> int:
    """中英混合估算：CJK 字符 1 token，拉丁词 1.3 token，其余标点按 0.3 计。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    words = len(_LATIN_WORD_RE.findall(text))
    rest = max(0, len(text) - cjk - sum(len(word) for word in _LATIN_WORD_RE.findall(text)))
    return max(1, int(round(cjk + words * 1.3 + rest * 0.3)))


@dataclass
class Chunk:
    """候选块；`chunk_level=parent` 的行是上下文来源，`child` 行才进入索引。"""

    chunk_id: str
    document_id: str
    workspace_id: str
    content: str
    chunk_level: str = "child"
    parent_id: str | None = None
    unit_id: str | None = None
    content_type: str = "concept"
    heading: str | None = None
    heading_level: int | None = None
    section_path: list[str] = field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    order: int = 0
    tokens: int = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = estimate_tokens(self.content)

    @property
    def is_atomic(self) -> bool:
        return self.content_type in {"formula", "code", "table"}


@dataclass
class ChunkingContext:
    """一次切分所需的全部输入（解析结果 + 结构 + 知识单元）。"""

    document_id: str
    workspace_id: str
    document_type: str
    blocks: list[Block]
    nodes: list[StructureNodeData] = field(default_factory=list)
    units: list[KnowledgeUnitData] = field(default_factory=list)
    filename: str | None = None

    def document(self) -> Document:
        """仅用于策略内部读取标题等元信息。"""
        return Document(
            document_id=self.document_id,
            workspace_id=self.workspace_id,
            filename=self.filename or "",
            file_type="",
            document_type=self.document_type,
            blocks=list(self.blocks),
        )


class ChunkStrategy(ABC):
    """按 document_type 选择的切分策略。"""

    name = "base"

    @abstractmethod
    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        """产出候选块（含 parent 与 child）。"""

    # ---- 共用工具 ---------------------------------------------------- #

    @staticmethod
    def child_id(document_id: str, order: int) -> str:
        return f"{document_id}_chunk_{order}"

    @staticmethod
    def parent_id(document_id: str, order: int) -> str:
        return f"{document_id}_parent_{order}"

    @staticmethod
    def block_text(blocks: list[Block], start: int, end: int) -> str:
        return "\n\n".join(
            blocks[index].text()
            for index in range(start, min(end, len(blocks) - 1) + 1)
            if blocks[index].text()
        ).strip()
