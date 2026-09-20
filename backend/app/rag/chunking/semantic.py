"""Semantic Chunking：句子级相似度漂移检测（设计文档 §10.3）。

失败（embedding 不可用）时直接降级到递归兜底策略，绝不阻断入库。
"""

from __future__ import annotations

import math
import re
from typing import Awaitable, Callable, Sequence

from loguru import logger

from app.config import settings
from app.rag.chunking.base import Chunk, ChunkingContext, ChunkStrategy
from app.rag.chunking.strategies import FallbackChunkStrategy
from app.rag.chunking.validator import ChunkValidator, normalize_text

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in _SENTENCE_RE.findall(text or "") if sentence.strip()]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


class SemanticChunkStrategy(ChunkStrategy):
    name = "semantic"

    def __init__(
        self,
        *,
        threshold: float | None = None,
        max_sentences: int | None = None,
        validator: ChunkValidator | None = None,
    ) -> None:
        self.threshold = settings.SEMANTIC_SPLIT_THRESHOLD if threshold is None else threshold
        self.max_sentences = (
            settings.SEMANTIC_SPLIT_MAX_SENTENCES if max_sentences is None else max_sentences
        )
        self.validator = validator or ChunkValidator()

    async def chunk(self, context: ChunkingContext, *, embed=None) -> list[Chunk]:
        text = normalize_text("\n\n".join(block.text() for block in context.blocks if block.text()))
        if not text:
            return []
        sentences = split_sentences(text)
        if len(sentences) < 2 or embed is None:
            return await FallbackChunkStrategy(self.validator).chunk(context, embed=None)
        # 超长文本先按段落预切，避免二次方开销（§10.3）
        groups: list[list[str]] = [sentences]
        if len(sentences) > self.max_sentences:
            groups = [
                sentences[index: index + self.max_sentences]
                for index in range(0, len(sentences), self.max_sentences)
            ]
        try:
            chunks: list[Chunk] = []
            for group in groups:
                vectors = await embed(group)
                chunks.extend(self._assemble(context, group, vectors, len(chunks)))
            return self.validator.validate(chunks)
        except Exception as exc:  # embedding 不可用 → 兜底
            logger.warning("Semantic chunking degraded to fallback: {}", exc)
            return await FallbackChunkStrategy(self.validator).chunk(context, embed=None)

    def _assemble(
        self,
        context: ChunkingContext,
        sentences: list[str],
        vectors: Sequence[Sequence[float]],
        offset: int,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        buffer = [sentences[0]]
        for index in range(1, len(sentences)):
            similarity = cosine_similarity(vectors[index - 1], vectors[index])
            if similarity < self.threshold:
                chunks.append(self._build(context, buffer, offset + len(chunks)))
                buffer = []
            buffer.append(sentences[index])
        if buffer:
            chunks.append(self._build(context, buffer, offset + len(chunks)))
        return chunks

    def _build(self, context: ChunkingContext, sentences: list[str], order: int) -> Chunk:
        return Chunk(
            chunk_id=self.child_id(context.document_id, order),
            document_id=context.document_id,
            workspace_id=context.workspace_id,
            content="".join(sentences),
            chunk_level="child",
            content_type="concept",
            order=order,
            metadata={"strategy": "semantic", "sentence_count": len(sentences)},
        )

