"""
EmbeddingService — 多提供商文本向量化服务

支持两种 embedding 提供商：
- local: 使用 sentence-transformers 本地模型（默认 BAAI/bge-small-zh-v1.5）
- openai: 通过 litellm 调用 OpenAI embedding API
"""

import asyncio
from typing import Optional

from loguru import logger


class EmbeddingService:
    """多提供商文本向量化服务"""

    # 默认模型配置
    DEFAULT_MODELS = {
        "local": "BAAI/bge-small-zh-v1.5",
        "openai": "text-embedding-3-small",
    }

    # 各模型对应的向量维度
    MODEL_DIMENSIONS = {
        "BAAI/bge-small-zh-v1.5": 512,
        "text-embedding-3-small": 1536,
    }

    # 各模型的输入窗口（token）。模型已加载时以 tokenizer 的真实窗口为准，
    # 这张表只用于「未加载模型」时判断切分上限是否安全。
    MODEL_MAX_TOKENS = {
        "BAAI/bge-small-zh-v1.5": 512,
        "BAAI/bge-m3": 8192,
        "text-embedding-3-small": 8191,
    }

    def __init__(self, provider: str = "local", model_name: Optional[str] = None):
        """
        初始化 EmbeddingService。

        Args:
            provider: 提供商名称，支持 "local" 和 "openai"
            model_name: 模型名称，为 None 时使用提供商默认模型
        """
        self.provider = provider
        self.model_name = model_name or self.DEFAULT_MODELS.get(provider)
        self._model = None  # 延迟加载本地模型
        self._dimension: Optional[int] = None
        # 最近一批 embedding 的窗口截断情况，供调用方与排障读取。
        self.last_truncation: dict[str, int] = {"over_window": 0, "batch": 0, "worst_tokens": 0}

        if not self.model_name:
            raise ValueError(f"未知的 embedding 提供商: {provider}，且未指定模型名称")

        logger.info(f"EmbeddingService 初始化完成: provider={provider}, model={self.model_name}")

    @property
    def max_input_tokens(self) -> Optional[int]:
        """模型输入窗口：优先取已加载模型的真实值，否则查已知模型表。"""
        if self._model is not None:
            window = int(getattr(self._model, "max_seq_length", 0) or 0)
            if window:
                return window
        return self.MODEL_MAX_TOKENS.get(self.model_name)

    def _count_over_window(self, texts: list[str]) -> tuple[int, int]:
        """统计本批有多少条输入超出模型窗口（超出的部分不会进入向量）。

        sentence-transformers 默认静默截断，这里显式统计，避免「切分上限比模型窗口大」
        这类配置问题变成无声的质量损失。原子块（公式/代码/表格）按设计不细分，
        因此这条检查在收紧切分上限之后仍然必要。
        """
        window = self.max_input_tokens
        tokenizer = getattr(self._model, "tokenizer", None)
        if not window or tokenizer is None:
            return 0, 0
        over = 0
        worst = 0
        for text in texts:
            try:
                length = len(tokenizer.encode(text, add_special_tokens=True, truncation=False))
            except TypeError:  # 某些 tokenizer 不接受 truncation 参数
                length = len(tokenizer.encode(text))
            if length > window:
                over += 1
                worst = max(worst, length)
        return over, worst

    def _load_local_model(self):
        """延迟加载 sentence-transformers 本地模型"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info(f"正在加载本地 embedding 模型: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                logger.info(f"本地 embedding 模型加载完成: {self.model_name}")
            except ImportError:
                raise ImportError(
                    "使用本地 embedding 需要安装 sentence-transformers: "
                    "pip install sentence-transformers"
                )
            except Exception as e:
                logger.error(f"加载本地 embedding 模型失败: {e}")
                raise

    def get_dimension(self) -> int:
        """
        获取当前模型的向量维度。

        Returns:
            向量维度整数
        """
        if self._dimension is not None:
            return self._dimension

        # 先尝试从已知配置中获取
        if self.model_name in self.MODEL_DIMENSIONS:
            self._dimension = self.MODEL_DIMENSIONS[self.model_name]
            return self._dimension

        # 本地模型：加载后获取维度
        if self.provider == "local":
            self._load_local_model()
            self._dimension = self._model.get_sentence_embedding_dimension()
            return self._dimension

        # 远程模型：发送一次请求获取维度
        if self.provider == "openai":
            self._dimension = self.MODEL_DIMENSIONS.get(self.model_name, 1536)
            return self._dimension

        # 兜底
        logger.warning(f"无法确定模型 {self.model_name} 的维度，默认返回 512")
        self._dimension = 512
        return self._dimension

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        批量向量化文本。

        Args:
            texts: 待向量化的文本列表

        Returns:
            与输入顺序对应的向量列表

        Raises:
            ValueError: 输入为空
            RuntimeError: 向量化过程出错
        """
        if not texts:
            return []

        try:
            if self.provider == "local":
                return await self._embed_local(texts)
            elif self.provider == "openai":
                return await self._embed_openai(texts)
            else:
                raise ValueError(f"不支持的 embedding 提供商: {self.provider}")
        except Exception as e:
            logger.error(f"批量向量化失败: {e}")
            raise RuntimeError(f"批量向量化失败: {e}") from e

    async def embed_query(self, query: str) -> list[float]:
        """
        向量化单条查询文本。

        Args:
            query: 查询文本

        Returns:
            向量列表

        Raises:
            RuntimeError: 向量化过程出错
        """
        results = await self.embed_texts([query])
        return results[0]

    async def _embed_local(self, texts: list[str]) -> list[list[float]]:
        """使用 sentence-transformers 本地推理"""
        self._load_local_model()
        over, worst = self._count_over_window(texts)
        self.last_truncation = {"over_window": over, "batch": len(texts), "worst_tokens": worst}
        if over:
            logger.warning(
                "embedding 输入超出模型窗口：{}/{} 条被截断（模型 {}，窗口 {} token，最长 {} token）。"
                "被截断的尾部不会进入向量，请核对切分上限与原子块长度。",
                over,
                len(texts),
                self.model_name,
                self.max_input_tokens,
                worst,
            )

        def _run():
            # sentence-transformers 的 encode 是同步的，放到线程池执行
            embeddings = self._model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=64,
            )
            return embeddings.tolist()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _run)

    async def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        """通过 litellm 调用 OpenAI embedding API"""
        try:
            import litellm
        except ImportError:
            raise ImportError(
                "使用 OpenAI embedding 需要安装 litellm: pip install litellm"
            )

        try:
            response = await litellm.aembedding(
                model=self.model_name,
                input=texts,
            )
            # 按 index 排序以确保顺序正确
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
        except Exception as e:
            logger.error(f"OpenAI embedding 调用失败: {e}")
            raise


# ---------------------------------------------------------------------------
# 工厂函数：供 Celery 任务和 API 路由统一调用
# ---------------------------------------------------------------------------

_embedding_service_instance: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """根据应用配置返回全局单例 EmbeddingService。

    读取 ``DEFAULT_EMBEDDING_PROVIDER`` 和 ``DEFAULT_EMBEDDING_MODEL``
    环境变量（由 .env / config.py 提供），自动选择 local 或 openai 后端。
    """
    global _embedding_service_instance
    if _embedding_service_instance is not None:
        return _embedding_service_instance

    from app.config import settings

    provider = settings.DEFAULT_EMBEDDING_PROVIDER  # "local" | "openai"
    # DEFAULT_EMBEDDING 是用户在设置页选择的模型（本地或远程），优先使用它；
    # 未选择时再回退到提供商默认模型。
    model_name = settings.DEFAULT_EMBEDDING or settings.DEFAULT_EMBEDDING_MODEL

    _embedding_service_instance = EmbeddingService(
        provider=provider,
        model_name=model_name,
    )
    return _embedding_service_instance


def reset_embedding_service() -> None:
    """Drop the cached service so tests and settings changes can rebuild it."""
    global _embedding_service_instance
    _embedding_service_instance = None
