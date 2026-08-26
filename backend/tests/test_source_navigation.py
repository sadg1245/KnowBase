"""Stable source identifiers are exposed by every serializer."""

import unittest

from app.api.routes.search import serialize_source
from app.core.rag_engine import RAGEngine
from app.schemas.schemas import SearchResult, SourceItem
from app.services.hybrid_retrieval import RetrievalCandidate


class SourceNavigationTests(unittest.TestCase):
    def test_candidate_serializer_and_schemas_keep_chunk_id(self):
        candidate = RetrievalCandidate(
            chunk_id="doc_chunk_3",
            document_id="doc",
            source_file="book.pdf",
            page_num=8,
            heading="第三章",
            content="evidence",
        )
        source = serialize_source(candidate)
        self.assertEqual(source["chunk_id"], "doc_chunk_3")
        self.assertEqual(source["document_id"], "doc")
        self.assertEqual(SourceItem(**source).chunk_id, "doc_chunk_3")
        self.assertEqual(SearchResult(**source).chunk_id, "doc_chunk_3")

    def test_legacy_rag_metadata_prefers_chunk_id_then_id(self):
        engine = object.__new__(RAGEngine)
        _context, sources, _confidence = engine._build_context([{
            "content": "evidence",
            "metadata": {
                "source_file": "book.pdf",
                "document_id": "doc",
                "id": "legacy-id",
                "chunk_id": "doc_chunk_3",
            },
            "distance": 0.1,
        }])
        self.assertEqual(sources[0]["chunk_id"], "doc_chunk_3")
        self.assertEqual(sources[0]["document_id"], "doc")

