"""ChunkRouter：按 document_type 选择策略，未知类型与异常一律兜底。"""

from __future__ import annotations

from loguru import logger

from app.rag.chunking.base import Chunk, ChunkingContext, ChunkStrategy
from app.rag.chunking.semantic import SemanticChunkStrategy
from app.rag.chunking.strategies import (
    CodeChunkStrategy,
    ExamChunkStrategy,
    FallbackChunkStrategy,
    QaChunkStrategy,
    StructureChunkStrategy,
)
from app.rag.chunking.validator import ChunkValidator


class ChunkRouter:
    def __init__(self, *, validator: ChunkValidator | None = None) -> None:
        validator = validator or ChunkValidator()
        self._mapping: dict[str, ChunkStrategy] = {
            "textbook": StructureChunkStrategy(validator),
            "notes": StructureChunkStrategy(validator),
            "tutorial": StructureChunkStrategy(validator),
            "documentation": StructureChunkStrategy(validator),
            "slides": StructureChunkStrategy(validator),
            "paper": StructureChunkStrategy(validator),
            "exam": ExamChunkStrategy(validator),
            "qa": QaChunkStrategy(),
            "code_document": CodeChunkStrategy(validator),
            "unstructured": SemanticChunkStrategy(validator=validator),
        }
        self._fallback = FallbackChunkStrategy(validator)

    def get_strategy(self, document_type: str) -> ChunkStrategy:
        return self._mapping.get((document_type or "").strip(), self._fallback)

    async def chunk(
        self, context: ChunkingContext, *, embed=None, document_type: str | None = None
    ) -> list[Chunk]:
        """切分；任何策略异常都降级到兜底策略并记录原因。"""
        document_type = document_type or context.document_type
        strategy = self.get_strategy(document_type)
        try:
            chunks = await strategy.chunk(context, embed=embed)
        except Exception as exc:
            logger.warning(
                "Chunk strategy '{}' failed for document {}: {}; falling back.",
                strategy.name, context.document_id, exc,
            )
            chunks = await self._fallback.chunk(context, embed=None)
            for chunk in chunks:
                chunk.metadata["strategy_fallback_from"] = strategy.name
        if not chunks:
            chunks = await self._fallback.chunk(context, embed=None)
        for order, chunk in enumerate(chunks):
            chunk.metadata.setdefault("strategy", strategy.name)
            if chunk.chunk_level == "child":
                chunk.order = order
        return chunks
