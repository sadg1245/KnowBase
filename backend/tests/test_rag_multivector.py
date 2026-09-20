"""阶段 3(d)：多向量展开、按 chunk_id 归并与索引指纹。"""

import unittest
from unittest.mock import patch

from app.rag.indexing import (
    expand_child_vectors,
    fingerprint_gap,
    index_fingerprint,
    parse_vector_kinds,
    read_fingerprint,
    write_fingerprint,
)
from app.rag.indexing.multivector import logical_chunk_id


def row(chunk_id: str, content: str, *, content_type: str = "concept",
        summary: str = "", questions: list[str] | None = None) -> dict:
    return {
        "content": content,
        "metadata": {
            "chunk_id": chunk_id,
            "content_type": content_type,
            "summary": summary,
            "questions": questions or [],
        },
    }


class MultivectorExpansionTests(unittest.TestCase):
    def test_parse_vector_kinds_is_ordered_and_safe(self):
        self.assertEqual(parse_vector_kinds(None), ["content"])
        self.assertEqual(parse_vector_kinds("summary,question"), ["content", "summary", "question"])
        self.assertEqual(parse_vector_kinds("question,nonsense"), ["content", "question"])
        self.assertEqual(parse_vector_kinds(["SUMMARY", "content"]), ["content", "summary"])

    def test_expansion_adds_summary_and_question_records_for_whitelisted_types(self):
        rows = [row("c1", "条件概率的原文", content_type="definition",
                    summary="条件概率摘要", questions=["什么是条件概率？", "如何推导？"])]
        ids, texts, metadatas = expand_child_vectors(rows, kinds=["content", "summary", "question"])

        self.assertEqual(ids, ["c1", "c1#summary", "c1#question0", "c1#question1"])
        self.assertEqual(texts[0], "条件概率的原文")
        self.assertEqual(texts[1], "条件概率摘要")
        self.assertEqual(
            [meta["vector_kind"] for meta in metadatas],
            ["content", "summary", "question", "question"],
        )
        self.assertTrue(all(meta["chunk_id"] == "c1" for meta in metadatas))

    def test_non_whitelisted_type_and_disabled_kinds_stay_content_only(self):
        rows = [row("c2", "照片说明", content_type="note", summary="摘要", questions=["问题"])]
        ids, _texts, metadatas = expand_child_vectors(rows, kinds=["content", "summary", "question"])
        self.assertEqual(ids, ["c2"])

        whitelisted = [row("c3", "定义", content_type="definition", summary="摘要", questions=["问题"])]
        ids, _texts, metadatas = expand_child_vectors(whitelisted, kinds=["content"])
        self.assertEqual(ids, ["c3"])
        self.assertEqual(metadatas[0]["vector_kind"], "content")

    def test_logical_chunk_id_prefers_metadata_and_strips_suffix(self):
        self.assertEqual(logical_chunk_id("c1#summary", {"chunk_id": "c1"}), "c1")
        self.assertEqual(logical_chunk_id("c9#question1", {}), "c9")
        self.assertEqual(logical_chunk_id("c9", {}), "c9")


class IndexFingerprintTests(unittest.TestCase):
    class _Collection:
        def __init__(self, metadata=None):
            self.metadata = dict(metadata or {})
            self.modified: dict | None = None

        def modify(self, metadata=None):
            self.modified = metadata
            self.metadata = dict(metadata or {})

    def test_fingerprint_round_trip_and_gap_detection(self):
        collection = self._Collection({"hnsw:space": "cosine"})
        self.assertEqual(read_fingerprint(collection), {})

        fingerprint = index_fingerprint(embedding_model="BAAI/bge-m3", embedding_dimension=1024)
        write_fingerprint(collection, fingerprint)

        # 写入指纹不能丢掉既有 collection 元数据
        self.assertEqual(collection.modified["hnsw:space"], "cosine")
        self.assertEqual(read_fingerprint(collection)["embedding_model"], "BAAI/bge-m3")
        self.assertEqual(fingerprint_gap(read_fingerprint(collection), fingerprint), [])

        changed_model = index_fingerprint(embedding_model="BAAI/bge-small-zh-v1.5", embedding_dimension=1024)
        gaps = fingerprint_gap(read_fingerprint(collection), changed_model)
        self.assertTrue(any("embedding_model" in gap for gap in gaps))

        changed_dimension = index_fingerprint(embedding_model="BAAI/bge-m3", embedding_dimension=512)
        self.assertIn("index_stale:embedding_dimension", fingerprint_gap(read_fingerprint(collection), changed_dimension))

        self.assertEqual(
            fingerprint_gap({}, changed_dimension), ["index_stale:missing_fingerprint"]
        )


class VectorRecallMergeTests(unittest.IsolatedAsyncioTestCase):
    class _Collection:
        def __init__(self, payload):
            self.payload = payload

        def query(self, **_kwargs):
            return self.payload

    class _Client:
        def __init__(self, collection):
            self.collection = collection

        def get_collection(self, name=None):
            return self.collection

    class _Embeddings:
        async def embed_query(self, query):
            return [0.1, 0.2]

    async def test_multiple_kinds_merge_into_one_candidate_keeping_content_text(self):
        from app.api.routes import search as search_routes

        payload = {
            "ids": [["c1#summary", "c1", "c1#question0", "c2"]],
            "documents": [["摘要文本", "原文文本", "问题文本", "另一块原文"]],
            "metadatas": [[
                {"chunk_id": "c1", "vector_kind": "summary", "doc_id": "doc-1"},
                {"chunk_id": "c1", "vector_kind": "content", "doc_id": "doc-1"},
                {"chunk_id": "c1", "vector_kind": "question", "doc_id": "doc-1"},
                {"chunk_id": "c2", "vector_kind": "content", "doc_id": "doc-1"},
            ]],
            "distances": [[0.05, 0.30, 0.12, 0.40]],
        }
        client = self._Client(self._Collection(payload))

        with patch.object(search_routes, "_get_chroma_client", return_value=client), \
                patch.object(search_routes, "get_embedding_service", return_value=self._Embeddings()):
            results = await search_routes._vector_recall(
                query="条件概率", workspace_ids=["ws-1"], document_ids=[], top_k=5
            )

        self.assertEqual(len(results), 2)
        top = results[0]
        self.assertEqual(top["chunk_id"], "c1")
        self.assertEqual(top["vector_kinds"], ["content", "question", "summary"])
        self.assertAlmostEqual(top["score"], 0.95, places=4)          # 取最高名次
        self.assertEqual(top["content"], "原文文本")                    # 证据正文来自 content 向量
        self.assertNotIn("_content_kind", top)


if __name__ == "__main__":
    unittest.main()
