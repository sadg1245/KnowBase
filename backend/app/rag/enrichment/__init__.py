"""阶段 3 富化层：chunk 级 summary / keywords / difficulty / content_type / questions。"""

from app.rag.enrichment.metadata_enricher import (
    EnrichmentPayload,
    MetadataEnricher,
    build_completion,
)

__all__ = ["EnrichmentPayload", "MetadataEnricher", "build_completion"]
