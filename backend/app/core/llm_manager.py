"""
LLMManager — 基于 litellm 的统一多模型大语言语言模型管理器

支持 OpenAI、DeepSeek、通义千问（Qwen）、智谱（GLM）、Ollama 等多家提供商，
提供统一的异步调用接口，包括普通生成和流式生成。
"""

import os
import time
from typing import AsyncGenerator, Optional

from loguru import logger


# 各提供商的默认配置
PROVIDER_CONFIGS = {
    "openai": {
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
        "env_key": "OPENAI_API_KEY",
        "base_url": None,  # 使用 litellm 默认
    },
    "deepseek": {
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
    },
    "qwen": {
        "models": ["qwen-turbo", "qwen-plus", "qwen-max"],
        "env_key": "QWEN_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "glm": {
        "models": ["glm-4-flash", "glm-4-plus"],
        "env_key": "GLM_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    "ollama": {
        "models": [],  # 由环境变量 OLLAMA_MODELS 配置，逗号分隔
        "env_key": None,  # Ollama 不需要 API key
        "base_url": None,  # 从 OLLAMA_BASE_URL 读取
    },
}


class LLMManager:
    """统一多提供商 LLM 调用管理器"""

    def __init__(self):
        """
        初始化 LLMManager。
        尝试从 app.config.Settings 加载配置，失败时从环境变量加载。
        """
        self._default_provider: Optional[str] = None
        self._default_model: Optional[str] = None

        # 尝试从 Settings 加载
        try:
            from app.config import Settings
            settings = Settings()
            self._default_provider = getattr(settings, "DEFAULT_LLM_PROVIDER", None)
            self._default_model = getattr(settings, "DEFAULT_LLM_MODEL", None)
            logger.info(
                f"从 Settings 加载 LLM 配置: provider={self._default_provider}, "
                f"model={self._default_model}"
            )
        except Exception:
            logger.debug("未找到 app.config.Settings，使用环境变量配置")

        # 环境变量兜底
        if not self._default_provider:
            self._default_provider = os.getenv("DEFAULT_LLM_PROVIDER", "openai")
        if not self._default_model:
            self._default_model = os.getenv("DEFAULT_LLM_MODEL", "gpt-4o-mini")

        logger.info(
            f"LLMManager 初始化完成: default_provider={self._default_provider}, "
            f"default_model={self._default_model}"
        )

    def _resolve_model_name(
        self, provider: Optional[str], model: Optional[str]
    ) -> tuple[str, str, dict]:
        """
        解析最终的模型调用参数。

        Returns:
            (litellm_model_name, provider, extra_kwargs)
            litellm_model_name: litellm 识别的模型标识
            provider: 提供商名称
            extra_kwargs: 传递给 litellm 的额外参数
        """
        provider = provider or self._default_provider
        model = model or self._default_model

        extra_kwargs = {}

        if provider == "openai":
            litellm_model = model
        elif provider == "deepseek":
            litellm_model = f"deepseek/{model}"
        elif provider == "qwen":
            litellm_model = f"openai/{model}"
        elif provider == "glm":
            litellm_model = f"openai/{model}"
        elif provider == "ollama":
            litellm_model = f"ollama/{model}"
        else:
            litellm_model = f"openai/{model}"

        # 设置 base_url
        config = PROVIDER_CONFIGS.get(provider, {})
        base_url = config.get("base_url")

        if provider == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        if base_url:
            extra_kwargs["api_base"] = base_url

        # 设置 API key
        env_key = config.get("env_key")
        if env_key:
            api_key = os.getenv(env_key)
            if api_key:
                extra_kwargs["api_key"] = api_key

        # Ollama 需要虚拟 api_key
        if provider == "ollama":
            extra_kwargs["api_key"] = "ollama"

        return litellm_model, provider, extra_kwargs

    async def generate(
        self,
        messages: list[dict],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """
        异步生成文本响应。

        Args:
            messages: 对话消息列表 [{"role": "system"|"user"|"assistant", "content": "..."}]
            provider: 提供商名称（可选，默认使用配置的默认提供商）
            model: 模型名称（可选，默认使用配置的默认模型）
            temperature: 生成温度
            max_tokens: 最大生成 token 数

        Returns:
            生成的文本

        Raises:
            RuntimeError: 生成过程出错
        """
        try:
            import litellm
        except ImportError:
            raise ImportError(
                "使用 LLMManager 需要安装 litellm: pip install litellm"
            )

        litellm_model, resolved_provider, extra_kwargs = self._resolve_model_name(
            provider, model
        )

        logger.debug(
            f"LLM 生成请求: model={litellm_model}, provider={resolved_provider}, "
            f"temperature={temperature}, max_tokens={max_tokens}, "
            f"messages_count={len(messages)}"
        )

        try:
            response = await litellm.acompletion(
                model=litellm_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **extra_kwargs,
            )
            content = response.choices[0].message.content or ""
            logger.debug(f"LLM 生成完成: 响应长度={len(content)}")
            return content

        except litellm.exceptions.RateLimitError:
            logger.warning(f"LLM 请求频率超限: {litellm_model}")
            raise RuntimeError("请求频率超限，请稍后重试")
        except litellm.exceptions.Timeout:
            logger.warning(f"LLM 请求超时: {litellm_model}")
            raise RuntimeError("请求超时，请稍后重试")
        except litellm.exceptions.AuthenticationError:
            logger.error(f"LLM API Key 无效: provider={resolved_provider}")
            raise RuntimeError(
                f"API Key 无效或未配置，请检查 {resolved_provider} 的 API Key 设置"
            )
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            raise RuntimeError(f"LLM 生成失败: {e}") from e

    async def generate_stream(
        self,
        messages: list[dict],
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> AsyncGenerator[str, None]:
        """
        异步流式生成文本响应。

        Args:
            messages: 对话消息列表
            provider: 提供商名称
            model: 模型名称
            temperature: 生成温度
            max_tokens: 最大生成 token 数

        Yields:
            逐步生成的文本片段
        """
        try:
            import litellm
        except ImportError:
            raise ImportError(
                "使用 LLMManager 需要安装 litellm: pip install litellm"
            )

        litellm_model, resolved_provider, extra_kwargs = self._resolve_model_name(
            provider, model
        )

        logger.debug(
            f"LLM 流式生成请求: model={litellm_model}, provider={resolved_provider}"
        )

        try:
            response = await litellm.acompletion(
                model=litellm_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **extra_kwargs,
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"LLM 流式生成失败: {e}")
            raise RuntimeError(f"LLM 流式生成失败: {e}") from e

    async def test_connection(
        self, provider: str, model: str
    ) -> dict:
        """
        测试与指定提供商和模型的连接。

        Args:
            provider: 提供商名称
            model: 模型名称

        Returns:
            {success: bool, latency_ms: float, error: str|None}
        """
        start_time = time.time()

        try:
            import litellm
        except ImportError:
            return {
                "success": False,
                "latency_ms": 0,
                "error": "litellm 未安装",
            }

        litellm_model, resolved_provider, extra_kwargs = self._resolve_model_name(
            provider, model
        )

        try:
            response = await litellm.acompletion(
                model=litellm_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
                temperature=0,
                **extra_kwargs,
            )
            latency_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }

        except litellm.exceptions.AuthenticationError:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "success": False,
                "latency_ms": round(latency_ms, 2),
                "error": "API Key 无效或未配置",
            }
        except litellm.exceptions.RateLimitError:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "success": False,
                "latency_ms": round(latency_ms, 2),
                "error": "请求频率超限",
            }
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return {
                "success": False,
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
            }

    def get_available_providers(self) -> list[dict]:
        """
        获取所有已配置的提供商及其状态。

        Returns:
            提供商信息列表，每项包含 {name, models, configured: bool}
        """
        providers = []

        for name, config in PROVIDER_CONFIGS.items():
            env_key = config.get("env_key")
            models = list(config.get("models", []))

            # Ollama 特殊处理：模型列表从环境变量获取
            if name == "ollama":
                ollama_models = os.getenv("OLLAMA_MODELS", "")
                models = [m.strip() for m in ollama_models.split(",") if m.strip()]

            # 判断是否已配置（有 API Key 或不需要 Key）
            if name == "ollama":
                configured = bool(os.getenv("OLLAMA_BASE_URL"))
            elif env_key:
                configured = bool(os.getenv(env_key))
            else:
                configured = False

            providers.append({
                "name": name,
                "models": models,
                "configured": configured,
            })

        return providers
