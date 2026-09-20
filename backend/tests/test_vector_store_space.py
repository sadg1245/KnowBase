"""The vector collection must use cosine distance, matching the score math."""

import unittest

from app.core.vector_store import COSINE_SPACE, VectorStore, describe_collection_space


class _FakeCollection:
    def __init__(self, metadata=None) -> None:
        self.metadata = metadata or {}


class _FakeClient:
    def __init__(self) -> None:
        self.created: dict = {}
        self.collections: dict[str, _FakeCollection] = {}

    def get_or_create_collection(self, *, name, metadata=None):
        self.created[name] = metadata or {}
        collection = _FakeCollection(metadata or {})
        self.collections[name] = collection
        return collection

    def get_collection(self, *, name):
        return self.collections[name]


class VectorStoreSpaceTests(unittest.TestCase):
    def test_new_collections_declare_cosine_space(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        store.get_or_create_collection("ws-123")

        metadata = client.created["ws_ws_123"]
        self.assertEqual(metadata["hnsw:space"], COSINE_SPACE)
        self.assertEqual(metadata["workspace_id"], "ws-123")

    def test_describe_collection_space_reports_missing_configuration(self):
        self.assertIsNone(describe_collection_space(_FakeCollection()))
        self.assertEqual(
            describe_collection_space(_FakeCollection({"hnsw:space": "cosine"})),
            "cosine",
        )
        # 写入索引指纹后 hnsw:space 不再回写，诊断改用指纹里的 distance
        self.assertEqual(
            describe_collection_space(_FakeCollection({"knowbase_index_distance": "cosine"})),
            "cosine",
        )

    def test_describe_space_reads_the_live_collection(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        store.get_or_create_collection("ws-123")

        self.assertEqual(store.describe_space("ws-123"), "cosine")

    def test_injected_client_skips_chromadb_connection(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        self.assertIs(store._client, client)
