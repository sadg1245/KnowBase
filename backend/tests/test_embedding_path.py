"""The query path must use the same embedding service as ingestion."""

import unittest
from unittest.mock import patch

from app.core.embedding import get_embedding_service, reset_embedding_service


class EmbeddingSingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_embedding_service()

    def test_get_embedding_service_returns_one_shared_instance(self):
        reset_embedding_service()
        self.assertIs(get_embedding_service(), get_embedding_service())

    def test_reset_embedding_service_forces_a_fresh_instance(self):
        reset_embedding_service()
        first = get_embedding_service()
        reset_embedding_service()
        self.assertIsNot(first, get_embedding_service())


class QueryEmbeddingPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_recall_uses_the_shared_embedding_service(self):
        from app.api.routes import search as search_module

        self.assertFalse(
            hasattr(search_module, "_get_embedding_function"),
            "查询侧不应再自带一套 embedding 加载路径",
        )

        seen: list[str] = []

        class _Recorder:
            async def embed_query(self, text: str) -> list[float]:
                seen.append(text)
                return [0.1, 0.2, 0.3]

        class _Collection:
            def __init__(self) -> None:
                self.kwargs: dict = {}

            def query(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "ids": [["doc-1_chunk_0"]],
                    "documents": [["条件概率的定义"]],
                    "metadatas": [[{"doc_id": "doc-1", "source_file": "概率论.pdf"}]],
                    "distances": [[0.2]],
                }

        class _Client:
            def __init__(self) -> None:
                self.collection = _Collection()

            def get_collection(self, name: str):
                return self.collection

        client = _Client()
        with patch.object(search_module, "get_embedding_service", lambda: _Recorder()), patch.object(
            search_module, "_get_chroma_client", lambda: client
        ):
            rows = await search_module._vector_recall(
                query="条件概率", workspace_ids=["ws-1"], document_ids=[], top_k=5
            )

        self.assertEqual(seen, ["条件概率"])
        self.assertEqual(client.collection.kwargs["query_embeddings"], [[0.1, 0.2, 0.3]])
        self.assertEqual(rows[0]["chunk_id"], "doc-1_chunk_0")
        self.assertEqual(rows[0]["score"], 0.8)
        self.assertEqual(rows[0]["document_id"], "doc-1")
        self.assertEqual(rows[0]["workspace_id"], "ws-1")


class _FakeTokenizer:
    """1 个字符 = 1 个 token，便于构造超出窗口的输入。"""

    def encode(self, text: str, add_special_tokens: bool = True, truncation: bool = True):
        return list(range(len(text)))


class _FakeLocalModel:
    def __init__(self, max_seq_length: int) -> None:
        self.max_seq_length = max_seq_length
        self.tokenizer = _FakeTokenizer()

    def encode(self, texts, **kwargs):
        import numpy as np

        return np.array([[0.1, 0.2] for _ in texts])


class EmbeddingWindowGuardTests(unittest.IsolatedAsyncioTestCase):
    """模型窗口静默截断必须变成可读的显式信号（模型保持现状的前提）。"""

    def test_window_falls_back_to_the_known_model_table(self):
        from app.core.embedding import EmbeddingService

        service = EmbeddingService(provider="local", model_name="BAAI/bge-small-zh-v1.5")

        self.assertEqual(service.max_input_tokens, 512)
        self.assertIsNone(
            EmbeddingService(provider="local", model_name="unknown/model").max_input_tokens
        )

    async def test_over_window_inputs_are_counted_and_reported(self):
        from app.core.embedding import EmbeddingService

        service = EmbeddingService(provider="local", model_name="BAAI/bge-small-zh-v1.5")
        service._model = _FakeLocalModel(max_seq_length=4)

        embeddings = await service._embed_local(["abc", "abcdefgh"])

        self.assertEqual(len(embeddings), 2)
        self.assertEqual(service.last_truncation, {
            "over_window": 1, "batch": 2, "worst_tokens": 8,
        })

    async def test_inputs_within_the_window_report_nothing(self):
        from app.core.embedding import EmbeddingService

        service = EmbeddingService(provider="local", model_name="BAAI/bge-small-zh-v1.5")
        service._model = _FakeLocalModel(max_seq_length=4)

        await service._embed_local(["abc", "abcd"])

        self.assertEqual(service.last_truncation, {
            "over_window": 0, "batch": 2, "worst_tokens": 0,
        })
