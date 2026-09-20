"""索引指纹提示只在真正有向量时出现（删除资料后不应误报需要重建）。"""

import unittest
from unittest.mock import patch

from app.api.routes import search as search_routes
from app.config import settings as app_settings


class _Collection:
    def __init__(self, count: int, metadata: dict | None = None):
        self._count = count
        self.metadata = metadata or {}

    def count(self) -> int:
        return self._count


class _Client:
    def __init__(self, collections: dict):
        self.collections = collections

    def get_collection(self, name=None):
        if name not in self.collections:
            raise ValueError("missing collection")
        return self.collections[name]


class _Embeddings:
    def get_dimension(self) -> int:
        return 512


class IndexStaleReportingTests(unittest.TestCase):
    def _reasons(self, collections: dict, workspace_ids: list[str]) -> list[str]:
        client = _Client(collections)
        with patch.object(search_routes, "_get_chroma_client", return_value=client), \
                patch.object(search_routes, "get_embedding_service", return_value=_Embeddings()):
            return search_routes._index_stale_reasons(workspace_ids)

    def test_empty_collection_is_not_reported_as_stale(self):
        # 资料已删除：collection 还在但没有向量，不应该提示重建
        reasons = self._reasons({"ws_empty": _Collection(0)}, ["empty"])
        self.assertEqual(reasons, [])

    def test_missing_fingerprint_on_populated_collection_is_stale(self):
        reasons = self._reasons({"ws_full": _Collection(12)}, ["full"])
        self.assertEqual(len(reasons), 1)
        self.assertIn("index_stale:missing_fingerprint", reasons[0])

    def test_matching_fingerprint_on_populated_collection_is_clean(self):
        from app.rag.indexing import index_fingerprint

        fingerprint = index_fingerprint(
            embedding_model=app_settings.DEFAULT_EMBEDDING or app_settings.DEFAULT_EMBEDDING_MODEL,
            embedding_dimension=512,
        )
        collection = _Collection(5, {"hnsw:space": "cosine", "knowbase_index": fingerprint})
        self.assertEqual(self._reasons({"ws_ok": collection}, ["ok"]), [])

    def test_unknown_workspace_collection_is_ignored(self):
        self.assertEqual(self._reasons({}, ["never-ingested"]), [])


if __name__ == "__main__":
    unittest.main()
