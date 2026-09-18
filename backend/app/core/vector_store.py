"""
VectorStore — 基于 ChromaDB 的向量存储与检索服务

每个 workspace 拥有独立的 collection，支持文档的增删查及语义搜索。
"""

import os
import time
from typing import Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

_vector_store_instance: Optional["VectorStore"] = None


def get_vector_store() -> "VectorStore":
    """返回全局 VectorStore 单例，供 Celery 任务和 API 路由使用。"""
    global _vector_store_instance
    if _vector_store_instance is not None:
        return _vector_store_instance

    from app.config import settings

    _vector_store_instance = VectorStore(
        host=settings.CHROMA_HOST,
        port=settings.CHROMA_PORT,
    )
    return _vector_store_instance


class VectorStore:
    """基于 ChromaDB 的向量存储"""

    def __init__(self, host: str = "local", port: int = 8000):
        """
        初始化 VectorStore。

        Args:
            host: ChromaDB 服务器地址，"local" 表示使用本地持久化模式
            port: ChromaDB 服务器端口（仅远程模式有效）
        """
        self.host = host
        self.port = port
        self._client = None
        self._connect()

    def _connect(self):
        """建立与 ChromaDB 的连接"""
        try:
            import chromadb

            if self.host == "local":
                from app.config import settings

                os.makedirs(settings.CHROMA_DIR, exist_ok=True)
                self._client = chromadb.PersistentClient(path=settings.CHROMA_DIR)
                logger.info("ChromaDB 本地持久化模式连接成功")
            else:
                self._client = chromadb.HttpClient(
                    host=self.host,
                    port=self.port,
                    settings=chromadb.Settings(
                        anonymized_telemetry=False,
                    ),
                )
                # 验证连接
                self._client.heartbeat()
                logger.info(f"ChromaDB 远程连接成功: {self.host}:{self.port}")
        except ImportError:
            raise ImportError(
                "使用 VectorStore 需要安装 chromadb: pip install chromadb"
            )
        except Exception as e:
            logger.error(f"ChromaDB 连接失败: {e}")
            raise ConnectionError(f"无法连接 ChromaDB: {e}") from e

    def _get_collection_name(self, workspace_id: str) -> str:
        """生成 workspace 对应的 collection 名称（ChromaDB 不允许特殊字符）"""
        # ChromaDB collection 名只能包含字母、数字、下划线、短横线
        safe_name = f"ws_{workspace_id}".replace("-", "_")
        return safe_name

    def get_or_create_collection(self, workspace_id: str):
        """
        获取或创建 workspace 对应的 collection。

        Args:
            workspace_id: 工作空间 ID

        Returns:
            ChromaDB Collection 对象
        """
        collection_name = self._get_collection_name(workspace_id)
        try:
            collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"workspace_id": workspace_id, "created_at": time.time()},
            )
            logger.debug(f"获取/创建 collection: {collection_name}")
            return collection
        except Exception as e:
            logger.error(f"创建 collection 失败 [{collection_name}]: {e}")
            raise

    async def add_documents(
        self,
        workspace_id: str,
        doc_ids: list[str],
        texts: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ):
        """
        向 collection 中添加文档。

        Args:
            workspace_id: 工作空间 ID
            doc_ids: 文档 ID 列表
            texts: 文档文本列表
            metadatas: 文档元数据列表（可选）
            embeddings: 预计算的向量列表（可选，不提供则由 ChromaDB 自动计算）
        """
        if not doc_ids:
            logger.warning("add_documents: 没有文档需要添加")
            return

        collection = self.get_or_create_collection(workspace_id)

        # 构建添加参数
        kwargs = {
            "ids": doc_ids,
            "documents": texts,
        }

        if metadatas:
            # ChromaDB 要求 metadata value 不能为 None，过滤掉
            cleaned_metadatas = []
            for meta in metadatas:
                cleaned = {
                    k: v for k, v in (meta or {}).items()
                    if v is not None
                }
                cleaned_metadatas.append(cleaned if cleaned else {"empty": True})
            kwargs["metadatas"] = cleaned_metadatas

        if embeddings:
            kwargs["embeddings"] = embeddings

        try:
            # upsert 使失败任务可以安全重试，也支持重新索引已有文档。
            collection.upsert(**kwargs)
            logger.info(
                f"成功添加 {len(doc_ids)} 个文档到 workspace={workspace_id}"
            )
        except Exception as e:
            logger.error(f"添加文档失败 [workspace={workspace_id}]: {e}")
            raise

    async def replace_document(
        self,
        workspace_id: str,
        document_id: str,
        doc_ids: list[str],
        texts: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        """Replace every current and legacy vector chunk for one document."""
        collection = self.get_or_create_collection(workspace_id)
        collection.delete(where={"doc_id": document_id})
        collection.delete(where={"document_id": document_id})
        if doc_ids:
            await self.add_documents(
                workspace_id=workspace_id,
                doc_ids=doc_ids,
                texts=texts,
                metadatas=metadatas,
                embeddings=embeddings,
            )
        logger.info(
            "已替换文档向量 [workspace={}, document={}, chunks={}]",
            workspace_id,
            document_id,
            len(doc_ids),
        )

    async def search(
        self,
        workspace_id: str,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """
        在 workspace 的 collection 中进行向量相似度搜索。

        Args:
            workspace_id: 工作空间 ID
            query_embedding: 查询向量
            top_k: 返回的最大结果数

        Returns:
            搜索结果列表，每项包含 {id, content, metadata, distance}
        """
        collection_name = self._get_collection_name(workspace_id)

        try:
            collection = self._client.get_collection(name=collection_name)
        except Exception:
            logger.warning(f"Collection 不存在: {collection_name}")
            return []

        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, collection.count() or top_k),
                include=["documents", "metadatas", "distances"],
            )

            # 解析结果
            output = []
            if results and results["ids"] and results["ids"][0]:
                ids = results["ids"][0]
                documents = results["documents"][0] if results["documents"] else [""] * len(ids)
                metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(ids)
                distances = results["distances"][0] if results["distances"] else [0.0] * len(ids)

                for i, doc_id in enumerate(ids):
                    output.append({
                        "id": doc_id,
                        "content": documents[i],
                        "metadata": metadatas[i] or {},
                        "distance": distances[i],
                    })

            logger.debug(
                f"搜索完成 [workspace={workspace_id}]: 返回 {len(output)} 条结果"
            )
            return output

        except Exception as e:
            logger.error(f"向量搜索失败 [workspace={workspace_id}]: {e}")
            raise

    async def delete_documents(self, workspace_id: str, doc_ids: list[str]):
        """
        从 collection 中删除指定文档。

        Args:
            workspace_id: 工作空间 ID
            doc_ids: 待删除的文档 ID 列表
        """
        if not doc_ids:
            return

        collection_name = self._get_collection_name(workspace_id)

        try:
            collection = self._client.get_collection(name=collection_name)
        except Exception:
            logger.warning(f"Collection 不存在，跳过删除: {collection_name}")
            return

        try:
            collection.delete(ids=doc_ids)
            logger.info(
                f"成功删除 {len(doc_ids)} 个文档 [workspace={workspace_id}]"
            )
        except Exception as e:
            logger.error(f"删除文档失败 [workspace={workspace_id}]: {e}")
            raise

    async def delete_collection(self, workspace_id: str):
        """
        删除整个 workspace 的 collection。

        Args:
            workspace_id: 工作空间 ID
        """
        collection_name = self._get_collection_name(workspace_id)

        try:
            self._client.delete_collection(name=collection_name)
            logger.info(f"成功删除 collection: {collection_name}")
        except ValueError:
            logger.warning(f"Collection 不存在，跳过删除: {collection_name}")
        except Exception as e:
            logger.error(f"删除 collection 失败 [{collection_name}]: {e}")
            raise

    async def get_collection_stats(self, workspace_id: str) -> dict:
        """
        获取 collection 的统计信息。

        Args:
            workspace_id: 工作空间 ID

        Returns:
            包含 {count, last_updated} 的字典
        """
        collection_name = self._get_collection_name(workspace_id)

        try:
            collection = self._client.get_collection(name=collection_name)
            count = collection.count()

            # 获取最近更新的文档作为参考
            last_updated = None
            if count > 0:
                try:
                    # 获取 collection 的 metadata
                    meta = collection.metadata or {}
                    last_updated = meta.get("created_at")
                except Exception:
                    pass

            return {
                "count": count,
                "last_updated": last_updated,
            }

        except Exception:
            logger.debug(f"Collection 不存在: {collection_name}")
            return {
                "count": 0,
                "last_updated": None,
            }
