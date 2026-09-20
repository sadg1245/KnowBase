"""大小校验与归一化（设计文档 §10.4）。

顺序不可颠倒：先按结构/语义产出候选块 → 超上限的在同一语义单元内递归细分 →
低于下限的与同父相邻块合并 → 原子块既不细分也不合并。
"""

from __future__ import annotations

import re

from app.rag.chunking.base import (
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    Chunk,
    estimate_tokens,
)

_BLANK_LINES_RE = re.compile(r"\n{3,}")
_TRAILING_SPACES_RE = re.compile(r"[ \t]+\n")


def normalize_text(text: str) -> str:
    """统一换行、去掉行尾空白、压缩连续空行。"""
    unified = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    unified = _TRAILING_SPACES_RE.sub("\n", unified)
    return _BLANK_LINES_RE.sub("\n\n", unified).strip()


class ChunkValidator:
    def __init__(
        self,
        *,
        min_tokens: int = MIN_CHUNK_TOKENS,
        max_tokens: int = MAX_CHUNK_TOKENS,
        splitter=None,
    ) -> None:
        self.min_tokens = min_tokens
        self.max_tokens = max_tokens
        self.splitter = splitter

    # ---- 细分 -------------------------------------------------------- #

    def split_oversized(self, chunk: Chunk) -> list[Chunk]:
        """超过上限时在同一语义单元内递归细分；原子块整块保留并标记。"""
        if chunk.tokens <= self.max_tokens:
            return [chunk]
        if chunk.is_atomic:
            chunk.metadata["oversized_ok"] = True
            chunk.metadata["oversized_reason"] = "atomic_block_kept_intact"
            return [chunk]
        pieces = self._split_text(chunk.content)
        if len(pieces) <= 1:
            chunk.metadata["oversized_ok"] = True
            chunk.metadata["oversized_reason"] = "no_safe_split_point"
            return [chunk]
        results: list[Chunk] = []
        for index, piece in enumerate(pieces):
            clone = Chunk(
                chunk_id=f"{chunk.chunk_id}#{index}",
                document_id=chunk.document_id,
                workspace_id=chunk.workspace_id,
                content=piece,
                chunk_level=chunk.chunk_level,
                parent_id=chunk.parent_id,
                unit_id=chunk.unit_id,
                content_type=chunk.content_type,
                heading=chunk.heading,
                heading_level=chunk.heading_level,
                section_path=list(chunk.section_path),
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                order=chunk.order,
                metadata={**chunk.metadata, "split_from": chunk.chunk_id, "split_index": index},
            )
            results.append(clone)
        return results

    def _split_text(self, text: str) -> list[str]:
        if self.splitter is None:
            return self._paragraph_split(text)
        try:
            pieces = self.splitter.split_text(text)
        except Exception:
            return self._paragraph_split(text)
        return [piece for piece in pieces if piece.strip()] or self._paragraph_split(text)

    def _paragraph_split(self, text: str) -> list[str]:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if len(paragraphs) <= 1:
            sentences = re.split(r"(?<=[。！？；.!?;])\s*", text)
            paragraphs = [part.strip() for part in sentences if part.strip()]
        pieces: list[str] = []
        buffer = ""
        for part in paragraphs:
            candidate = f"{buffer}\n\n{part}".strip() if buffer else part
            if buffer and estimate_tokens(candidate) > self.max_tokens:
                pieces.append(buffer)
                buffer = part
            else:
                buffer = candidate
        if buffer:
            pieces.append(buffer)
        return pieces

    # ---- 合并与归一化 ------------------------------------------------ #

    def merge_undersized(self, chunks: list[Chunk]) -> list[Chunk]:
        """低于下限时与同父相邻块合并；跨父不合并，并记录原因。"""
        merged: list[Chunk] = []
        for chunk in chunks:
            previous = merged[-1] if merged else None
            same_parent = (
                previous is not None
                and previous.parent_id == chunk.parent_id
                and previous.chunk_level == chunk.chunk_level
            )
            if (
                previous is not None
                and same_parent
                # 只有同类型才合并：把「定义」并进「标题」会丢掉语义类型
                and previous.content_type == chunk.content_type
                and not previous.is_atomic
                and not chunk.is_atomic
                and min(previous.tokens, chunk.tokens) < self.min_tokens
                and estimate_tokens(f"{previous.content}\n\n{chunk.content}") <= self.max_tokens
            ):
                previous.content = normalize_text(f"{previous.content}\n\n{chunk.content}")
                previous.tokens = estimate_tokens(previous.content)
                previous.page_end = chunk.page_end or previous.page_end
                previous.metadata["merge_reason"] = "below_min_tokens"
                previous.metadata.setdefault("merged_chunk_ids", []).append(chunk.chunk_id)
                continue
            if chunk.tokens < self.min_tokens:
                chunk.metadata["merge_reason"] = "below_min_tokens_no_sibling"
            merged.append(chunk)
        return merged

    def dedupe_overlap(self, chunks: list[Chunk]) -> list[Chunk]:
        """去掉与相邻块完全重复的尾部重叠。"""
        for previous, current in zip(chunks, chunks[1:]):
            if not previous.content or not current.content:
                continue
            tail = previous.content[-200:]
            overlap = 0
            for size in range(min(len(tail), len(current.content)), 20, -1):
                if current.content.startswith(tail[-size:]):
                    overlap = size
                    break
            if overlap:
                current.content = current.content[overlap:].lstrip()
                current.tokens = estimate_tokens(current.content)
        return [chunk for chunk in chunks if chunk.content.strip()]

    def validate(self, chunks: list[Chunk]) -> list[Chunk]:
        """完整流程：细分 → 合并 → 归一化 → 去重。"""
        for chunk in chunks:
            chunk.content = normalize_text(chunk.content)
            chunk.tokens = estimate_tokens(chunk.content)
        split: list[Chunk] = []
        for chunk in chunks:
            split.extend(self.split_oversized(chunk))
        merged = self.merge_undersized(split)
        return self.dedupe_overlap(merged)
