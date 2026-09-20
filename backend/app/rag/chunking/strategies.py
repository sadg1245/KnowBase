"""策略族：结构感知切分、题目切分、代码切分与递归兜底。"""

from __future__ import annotations

import re

from app.rag.chunking.base import (
    Chunk,
    ChunkingContext,
    ChunkStrategy,
)
from app.rag.chunking.validator import ChunkValidator, normalize_text
from app.rag.contracts import Block

_DEFINITION_RE = re.compile(r"是指|称为|定义为|指的是|\bis defined as\b", re.I)
_QUESTION_RE = re.compile(r"^\s*(?:第?\s*\d+[.、)）]|例\s*\d+|question\s*\d+)", re.I)
_CODE_BOUNDARY_RE = re.compile(r"^(?:def|class|async def)\s+\w+", re.M)

BLOCK_TYPE_TO_CONTENT_TYPE = {
    "heading": "note",
    "paragraph": "concept",
    "list": "concept",
    "quote": "note",
    "caption": "note",
    "code": "code",
    "formula": "formula",
    "table": "table",
    "image": "note",
    "question": "question",
    "answer": "answer",
}


def content_type_of(block: Block) -> str:
    base = BLOCK_TYPE_TO_CONTENT_TYPE.get(block.type, "concept")
    if base == "concept" and _DEFINITION_RE.search(block.text()):
        return "definition"
    if base == "concept" and _QUESTION_RE.match(block.text() or ""):
        return "question"
    return base


class StructureChunkStrategy(ChunkStrategy):
    """textbook / notes / tutorial / documentation / markdown / slides / paper。

    parent = 一个小节（完整上下文），child = 小节内的语义单元。
    """

    name = "structure"

    def __init__(self, validator: ChunkValidator | None = None) -> None:
        self.validator = validator or ChunkValidator()

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        parents: list[Chunk] = []
        children: list[Chunk] = []
        for group in self._groups(context.blocks):
            parent_id = self.parent_id(context.document_id, len(parents))
            parents.append(Chunk(
                chunk_id=parent_id,
                document_id=context.document_id,
                workspace_id=context.workspace_id,
                content=ChunkStrategy.block_text(context.blocks, group["start"], group["end"]),
                chunk_level="parent",
                content_type="note",
                heading=group["heading"],
                heading_level=group["heading_level"],
                section_path=list(group["section_path"]),
                page_start=group["page_start"],
                page_end=group["page_end"],
                order=len(parents),
            ))
            for index, span in enumerate(group["spans"]):
                children.append(Chunk(
                    chunk_id=self.child_id(context.document_id, len(children)),
                    document_id=context.document_id,
                    workspace_id=context.workspace_id,
                    content=ChunkStrategy.block_text(context.blocks, span["start"], span["end"]),
                    chunk_level="child",
                    parent_id=parent_id,
                    unit_id=span.get("unit_id"),
                    content_type=span["content_type"],
                    heading=group["heading"],
                    heading_level=group["heading_level"],
                    section_path=list(group["section_path"]),
                    page_start=span["page_start"],
                    page_end=span["page_end"],
                    order=index,
                ))
        return parents + self._finalize(children)

    def _finalize(self, children: list[Chunk]) -> list[Chunk]:
        validated = self.validator.validate(children)
        for order, chunk in enumerate(validated):
            chunk.order = order
        return validated

    def _groups(self, blocks: list[Block]) -> list[dict]:
        groups: list[dict] = []
        current: dict | None = None
        for index, block in enumerate(blocks):
            if block.type == "heading":
                # 标题只用于确定小节边界与 section_path，不作为独立 child 入库。
                if current is not None:
                    current["end"] = index
                continue
            path = list(block.section_path) or ([block.content] if block.type == "heading" else [])
            if current is None or path != current["section_path"]:
                # parent 覆盖该小节（含小节标题），child 仍从正文块开始
                start = index
                while (
                    start > 0
                    and blocks[start - 1].type == "heading"
                    and blocks[start - 1].content in path
                ):
                    start -= 1
                current = {
                    "section_path": path,
                    "heading": path[-1] if path else None,
                    "heading_level": block.heading_level,
                    "start": start,
                    "end": index,
                    "page_start": block.page,
                    "page_end": block.page,
                    "spans": [],
                }
                groups.append(current)
            current["end"] = index
            current["page_end"] = block.page or current["page_end"]
            mapped = content_type_of(block)
            last = current["spans"][-1] if current["spans"] else None
            if last is not None and last["content_type"] == mapped:
                last["end"] = index
                last["page_end"] = block.page or last["page_end"]
            else:
                current["spans"].append({
                    "start": index,
                    "end": index,
                    "content_type": mapped,
                    "page_start": block.page,
                    "page_end": block.page,
                })
        return groups


class ExamChunkStrategy(ChunkStrategy):
    """题目：parent = 题干 + 解答，child = 题干 / 解答（练习模式只召回题干）。"""

    name = "exam"

    def __init__(self, validator: ChunkValidator | None = None) -> None:
        self.validator = validator or ChunkValidator()

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        groups: list[list[int]] = []
        current: list[int] = []
        for index, block in enumerate(context.blocks):
            if block.type in {"question", "answer"} or (
                block.type == "heading" and block.heading_level == 1
            ):
                is_new_question = block.type == "question" or (
                    block.type == "heading" and current and context.blocks[current[0]].type != "question"
                )
                if current and is_new_question:
                    groups.append(current)
                    current = []
            current.append(index)
        if current:
            groups.append(current)
        if not groups:
            return await StructureChunkStrategy(self.validator).chunk(context, embed=embed)

        parents: list[Chunk] = []
        children: list[Chunk] = []
        for span in groups:
            first, last = span[0], span[-1]
            parent_id = self.parent_id(context.document_id, len(parents))
            stem = context.blocks[first].text()[:200]
            parents.append(Chunk(
                chunk_id=parent_id,
                document_id=context.document_id,
                workspace_id=context.workspace_id,
                content=ChunkStrategy.block_text(context.blocks, first, last),
                chunk_level="parent",
                content_type="question",
                heading=stem,
                section_path=list(context.blocks[first].section_path),
                page_start=context.blocks[first].page,
                page_end=context.blocks[last].page,
                order=len(parents),
            ))
            for index in span:
                block = context.blocks[index]
                children.append(Chunk(
                    chunk_id=self.child_id(context.document_id, len(children)),
                    document_id=context.document_id,
                    workspace_id=context.workspace_id,
                    content=block.text(),
                    chunk_level="child",
                    parent_id=parent_id,
                    content_type=content_type_of(block),
                    heading=stem,
                    section_path=list(block.section_path),
                    page_start=block.page,
                    page_end=block.page,
                    order=index,
                ))
        for order, chunk in enumerate(children):
            chunk.order = order
        return parents + children


class QaChunkStrategy(ChunkStrategy):
    """问答资料：Q + A 成对，题目与答案分块。"""

    name = "qa"

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        return await ExamChunkStrategy().chunk(context, embed=embed)


class CodeChunkStrategy(ChunkStrategy):
    """代码文档：按函数/类边界切分，代码块与前后说明配对。"""

    name = "code"

    def __init__(self, validator: ChunkValidator | None = None) -> None:
        self.validator = validator or ChunkValidator()

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        parents: list[Chunk] = []
        children: list[Chunk] = []
        explanation: list[int] = []
        for index, block in enumerate(context.blocks):
            if block.type != "code":
                explanation.append(index)
                continue
            span = [*explanation, index]
            leading = list(explanation)
            explanation = []
            segments = self._split_code(block.content)
            parent_id = self.parent_id(context.document_id, len(parents))
            parents.append(Chunk(
                chunk_id=parent_id,
                document_id=context.document_id,
                workspace_id=context.workspace_id,
                content=ChunkStrategy.block_text(context.blocks, span[0], span[-1]),
                chunk_level="parent",
                content_type="code",
                heading=block.section_path[-1] if block.section_path else None,
                section_path=list(block.section_path),
                page_start=context.blocks[span[0]].page,
                page_end=block.page,
                order=len(parents),
            ))
            for offset, block_index in enumerate(leading):
                children.append(Chunk(
                    chunk_id=self.child_id(context.document_id, len(children)),
                    document_id=context.document_id,
                    workspace_id=context.workspace_id,
                    content=context.blocks[block_index].text(),
                    chunk_level="child",
                    parent_id=parent_id,
                    content_type=content_type_of(context.blocks[block_index]),
                    section_path=list(context.blocks[block_index].section_path),
                    page_start=context.blocks[block_index].page,
                    page_end=context.blocks[block_index].page,
                    order=offset,
                ))
            for offset, segment in enumerate(segments):
                children.append(Chunk(
                    chunk_id=self.child_id(context.document_id, len(children)),
                    document_id=context.document_id,
                    workspace_id=context.workspace_id,
                    content=segment,
                    chunk_level="child",
                    parent_id=parent_id,
                    content_type="code",
                    heading=block.section_path[-1] if block.section_path else None,
                    section_path=list(block.section_path),
                    page_start=block.page,
                    page_end=block.page,
                    order=offset,
                    metadata={"code_segment": offset},
                ))
        if explanation:
            tail = self.block_text(context.blocks, explanation[0], explanation[-1])
            if tail:
                children.append(Chunk(
                    chunk_id=self.child_id(context.document_id, len(children)),
                    document_id=context.document_id,
                    workspace_id=context.workspace_id,
                    content=tail,
                    chunk_level="child",
                    content_type="concept",
                    section_path=list(context.blocks[explanation[0]].section_path),
                    page_start=context.blocks[explanation[0]].page,
                    page_end=context.blocks[explanation[-1]].page,
                    order=len(children),
                ))
        for order, chunk in enumerate(children):
            chunk.order = order
        return parents + children

    def _split_code(self, code: str) -> list[str]:
        boundaries = [match.start() for match in _CODE_BOUNDARY_RE.finditer(code)]
        if len(boundaries) <= 1:
            return [code.strip()] if code.strip() else []
        segments: list[str] = []
        for index, start in enumerate(boundaries):
            end = boundaries[index + 1] if index + 1 < len(boundaries) else len(code)
            piece = code[start:end].strip()
            if piece:
                segments.append(piece)
        return segments


class FallbackChunkStrategy(ChunkStrategy):
    """未知类型或策略异常时的递归字符切分（复用既有 TextSplitter）。"""

    name = "fallback"

    def __init__(self, validator: ChunkValidator | None = None) -> None:
        self.validator = validator or ChunkValidator()

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        text = normalize_text("\n\n".join(block.text() for block in context.blocks if block.text()))
        if not text:
            return []
        pieces = self._split_text(text)
        offsets: list[tuple[int, Block]] = []
        cursor = 0
        for block in context.blocks:
            segment = block.text()
            if not segment:
                continue
            offsets.append((cursor, block))
            cursor += len(segment) + 2

        children: list[Chunk] = []
        search_from = 0
        for index, piece in enumerate(pieces):
            position = text.find(piece[:40], search_from)
            if position < 0:
                position = search_from
            search_from = position + max(1, len(piece) - 40)
            owner = next(
                (block for offset, block in reversed(offsets) if offset <= position),
                context.blocks[0] if context.blocks else None,
            )
            children.append(Chunk(
                chunk_id=self.child_id(context.document_id, index),
                document_id=context.document_id,
                workspace_id=context.workspace_id,
                content=piece,
                chunk_level="child",
                content_type="note",
                heading=(owner.section_path[-1] if owner and owner.section_path else None),
                section_path=list(owner.section_path) if owner else [],
                page_start=owner.page if owner else None,
                page_end=owner.page if owner else None,
                order=index,
                metadata={"strategy": "fallback"},
            ))
        return self.validator.validate(children)

    def _split_text(self, text: str) -> list[str]:
        from app.core.text_splitter import get_text_splitter

        try:
            splitter = get_text_splitter()
            pieces = [piece for piece in splitter.split_text(text) if piece.strip()]
        except Exception:
            pieces = []
        if pieces:
            return pieces
        # 极端兜底：按段落切，保证不丢内容
        return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
