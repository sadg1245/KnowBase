"""
RAGEngine — 检索增强生成引擎

兼容层（legacy）：产品主链路已改为
`app/api/routes/search.py` → `app/services/hybrid_retrieval.py` →
`app/rag/retrieval/orchestrator.py`，本模块不再被任何生产代码引用。

保留原因：`_build_context` 的旧索引元数据兼容逻辑（`chunk_id` 优先、回退 `id`）仍由
`backend/tests/test_source_navigation.py` 守着，避免历史数据在迁移期丢来源标识。
新功能不要再依赖本模块；确认历史数据全部迁移后可整体删除。
"""

from typing import AsyncGenerator, Optional

from loguru import logger

from app.core.embedding import EmbeddingService
from app.core.llm_manager import LLMManager
from app.core.text_splitter import TextSplitter
from app.core.vector_store import VectorStore


# RAG 系统提示词
SYSTEM_PROMPT = """你是 KnowBase 私人知识库助手。请根据以下参考资料回答用户的问题。
规则：
1. 仅基于提供的参考资料回答，不要编造信息
2. 如果参考资料中没有相关内容，明确告知用户"知识库中暂未找到相关信息"
3. 回答时引用来源文件和页码，格式为 [文件名 第X页]
4. 保持回答简洁准确

参考资料：
{context}"""

# 无检索结果时的系统提示词
SYSTEM_PROMPT_NO_CONTEXT = """你是 KnowBase 私人知识库助手。
用户向你提问，但知识库中暂未检索到相关内容。请如实告知用户"知识库中暂未找到相关信息"，
并建议用户检查关键词或补充相关知识库文档。"""


class RAGEngine:
    """RAG 检索增强生成引擎"""

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        llm_manager: LLMManager,
        text_splitter: TextSplitter,
    ):
        """
        初始化 RAGEngine。

        Args:
            vector_store: 向量存储实例
            embedding_service: 向量化服务实例
            llm_manager: LLM 管理器实例
            text_splitter: 文本分块器实例
        """
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.llm_manager = llm_manager
        self.text_splitter = text_splitter

        logger.info("RAGEngine 初始化完成")

    async def query(
        self,
        question: str,
        workspace_id: Optional[str] = None,
        history: Optional[list] = None,
        top_k: int = 5,
    ) -> dict:
        """
        执行 RAG 查询：检索 -> 构建上下文 -> LLM 生成。

        Args:
            question: 用户提问
            workspace_id: 工作空间 ID（可选，指定时只搜索该工作空间）
            history: 对话历史（可选），格式 [{"role": "user"|"assistant", "content": "..."}]
            top_k: 检索返回的最大文档数

        Returns:
            {
                "answer": str,           # LLM 生成的回答
                "sources": list[dict],   # 引用的来源文档信息
                "confidence": float,     # 置信度 (0-1)
            }
        """
        logger.info(
            f"RAG 查询开始: question='{question[:50]}...', "
            f"workspace_id={workspace_id}, top_k={top_k}"
        )

        # 1. 向量化问题
        try:
            query_embedding = await self.embedding_service.embed_query(question)
        except Exception as e:
            logger.error(f"问题向量化失败: {e}")
            return {
                "answer": "抱歉，问题处理过程中出现错误，请稍后重试。",
                "sources": [],
                "confidence": 0.0,
            }

        # 2. 检索相关文档
        search_results = await self._search_documents(
            query_embedding, workspace_id, top_k
        )

        # 3. 构建上下文
        context, sources, confidence = self._build_context(search_results)

        # 4. 构建 prompt
        messages = self._build_prompt(question, context, history)

        # 5. 调用 LLM 生成回答
        try:
            answer = await self.llm_manager.generate(messages=messages)
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            return {
                "answer": "抱歉，生成回答时出现错误，请稍后重试。",
                "sources": sources,
                "confidence": 0.0,
            }

        logger.info(f"RAG 查询完成: 回答长度={len(answer)}, 来源数={len(sources)}")

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
        }

    async def query_stream(
        self,
        question: str,
        workspace_id: Optional[str] = None,
        history: Optional[list] = None,
        top_k: int = 5,
    ) -> AsyncGenerator[dict, None]:
        """
        流式 RAG 查询：检索 -> 构建上下文 -> LLM 流式生成。

        Args:
            question: 用户提问
            workspace_id: 工作空间 ID
            history: 对话历史
            top_k: 检索返回的最大文档数

        Yields:
            逐步生成的结果：
            - 首先 yield {"type": "sources", "sources": [...]}
            - 然后 yield {"type": "token", "content": "..."} 多个
            - 最后 yield {"type": "done", "confidence": float}
        """
        logger.info(
            f"RAG 流式查询开始: question='{question[:50]}...', "
            f"workspace_id={workspace_id}"
        )

        # 1. 向量化问题
        try:
            query_embedding = await self.embedding_service.embed_query(question)
        except Exception as e:
            logger.error(f"问题向量化失败: {e}")
            yield {"type": "error", "content": "问题处理失败，请稍后重试。"}
            return

        # 2. 检索相关文档
        search_results = await self._search_documents(
            query_embedding, workspace_id, top_k
        )

        # 3. 构建上下文
        context, sources, confidence = self._build_context(search_results)

        # 4. 先发送来源信息
        yield {"type": "sources", "sources": sources}

        # 5. 构建 prompt
        messages = self._build_prompt(question, context, history)

        # 6. 流式生成
        try:
            async for token in self.llm_manager.generate_stream(messages=messages):
                yield {"type": "token", "content": token}
        except Exception as e:
            logger.error(f"LLM 流式生成失败: {e}")
            yield {"type": "error", "content": "生成回答时出现错误，请稍后重试。"}
            return

        yield {"type": "done", "confidence": confidence}

    async def _search_documents(
        self,
        query_embedding: list[float],
        workspace_id: Optional[str],
        top_k: int,
    ) -> list[dict]:
        """
        执行文档检索。

        Args:
            query_embedding: 查询向量
            workspace_id: 工作空间 ID（为 None 时搜索所有工作空间）
            top_k: 返回结果数

        Returns:
            检索结果列表
        """
        try:
            if workspace_id:
                results = await self.vector_store.search(
                    workspace_id=workspace_id,
                    query_embedding=query_embedding,
                    top_k=top_k,
                )
                return results
            else:
                # 搜索所有工作空间：暂时只支持单 workspace 搜索
                # 如果需要搜索所有，可以传入特殊标识或遍历
                logger.warning(
                    "未指定 workspace_id，尝试在默认工作空间中搜索"
                )
                results = await self.vector_store.search(
                    workspace_id="default",
                    query_embedding=query_embedding,
                    top_k=top_k,
                )
                return results
        except Exception as e:
            logger.error(f"文档检索失败: {e}")
            return []

    def _build_context(
        self, search_results: list[dict]
    ) -> tuple[str, list[dict], float]:
        """
        从检索结果中构建上下文和来源引用。

        Args:
            search_results: 向量检索结果列表

        Returns:
            (context_str, sources, confidence)
            - context_str: 格式化的上下文文本
            - sources: 来源引用列表
            - confidence: 基于检索距离的置信度
        """
        if not search_results:
            return "", [], 0.0

        context_parts = []
        sources = []
        distances = []

        for idx, result in enumerate(search_results, 1):
            content = result.get("content", "")
            metadata = result.get("metadata", {})
            distance = result.get("distance", 1.0)
            distances.append(distance)

            # 提取来源信息
            source_file = metadata.get("source_file", "未知文件")
            page_num = metadata.get("page_num", None)
            heading = metadata.get("heading", None)

            # 构建上下文文本
            source_label = f"[来源{idx}]"
            file_info = f"文件: {source_file}"
            if page_num is not None:
                file_info += f" 第{page_num}页"
            if heading:
                file_info += f" 章节: {heading}"

            context_parts.append(f"{source_label} {file_info}\n{content}")

            # 构建来源引用
            sources.append({
                "index": idx,
                "file": source_file,
                "page": page_num,
                "heading": heading,
                "document_id": metadata.get("document_id") or metadata.get("doc_id"),
                "chunk_id": metadata.get("chunk_id") or metadata.get("id"),
                "content_preview": content[:200] + "..." if len(content) > 200 else content,
                "distance": distance,
            })

        context_str = "\n\n".join(context_parts)

        # 计算置信度：基于平均距离
        # ChromaDB 默认使用 L2 距离，越小越相似
        # 归一化到 0-1 区间（假设最大合理距离为 2.0）
        if distances:
            avg_distance = sum(distances) / len(distances)
            # 使用指数衰减函数归一化
            import math
            confidence = math.exp(-avg_distance)
            confidence = round(max(0.0, min(1.0, confidence)), 3)
        else:
            confidence = 0.0

        return context_str, sources, confidence

    def _build_prompt(
        self,
        question: str,
        context: str,
        history: Optional[list] = None,
    ) -> list[dict]:
        """
        构建发送给 LLM 的消息列表。

        Args:
            question: 用户提问
            context: 格式化的上下文文本
            history: 对话历史

        Returns:
            messages 列表，符合 OpenAI Chat 格式
        """
        messages = []

        # 系统提示
        if context:
            system_content = SYSTEM_PROMPT.format(context=context)
        else:
            system_content = SYSTEM_PROMPT_NO_CONTEXT

        messages.append({"role": "system", "content": system_content})

        # 对话历史（限制最近 10 轮）
        if history:
            recent_history = history[-20:]  # 取最近 20 条消息（10 轮对话）
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # 当前问题
        messages.append({"role": "user", "content": question})

        return messages
