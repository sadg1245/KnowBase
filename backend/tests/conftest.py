"""测试与开发者本地 `.env` 解耦：行为开关一律在用例内显式开启。

`app.config.settings` 会读取仓库根目录的 `.env`（自托管部署用的真实配置）。
如果不在这里收敛，本地把 `RAG_ENRICH_ENABLED=true` 打开后，所有跑流水线的用例
都会真的去调 LLM，既变慢又依赖外部网络。需要开启的用例自己在 `patch.object` 里打开。
"""

from app.config import settings

# 富化默认关闭：用例需要时用 patch.object(settings, "RAG_ENRICH_ENABLED", True)
settings.RAG_ENRICH_ENABLED = False
# 调试端点默认关闭：用例需要时自行打开
settings.RAG_DEBUG_ENDPOINT_ENABLED = False
