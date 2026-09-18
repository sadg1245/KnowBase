# KnowBase 项目开发提示词

> 本提示词用于指导 AI 编程助手从零构建 KnowBase 私人知识数据库系统。

---

## 项目概述

构建一个名为 **KnowBase** 的自托管私人知识数据库系统。核心理念是"你的知识，随时可问"。

**系统由 4 个服务组成：**

1. **Backend（FastAPI 后端）** — 提供 REST API，负责文档上传/解析/向量化、RAG 检索与问答、工作区管理、系统配置
2. **Feishu Bot（飞书机器人）** — 通过 WebSocket 长连接接收飞书消息，调用后端 API 实现知识问答
3. **Frontend（React 前端）** — Web 管理界面，文件上传、文档管理、检索测试、系统设置
4. **Infra（基础设施）** — ChromaDB 向量数据库 + Redis 缓存/队列 + SQLite 关系数据库

**部署方式：** Docker Compose 一键启动全部 6 个容器（backend、worker、feishu-bot、frontend、chromadb、redis）。

---

## 技术栈约束

### 后端（Python 3.11+）

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
aiosqlite==0.20.0
python-multipart==0.0.12
pydantic==2.9.2
pydantic-settings==2.5.2
python-dotenv==1.0.1
litellm==1.48.0
chromadb==0.5.11
sentence-transformers==3.1.1
celery[redis]==5.4.0
redis==5.1.1
pymupdf==1.24.10
python-docx==1.1.2
python-pptx==0.6.23
markdown==3.7
beautifulsoup4==4.12.3
chardet==5.2.0
openpyxl==3.1.5
pandas==2.2.3
loguru==0.7.2
aiofiles==24.1.0
httpx==0.27.2
```

### 前端

React 18 + TypeScript + Vite + Ant Design 5.x + Zustand + react-dropzone + axios

### 飞书 Bot

lark-oapi==1.4.0 + httpx==0.27.2 + redis==5.1.1 + loguru==0.7.2 + pydantic-settings==2.5.2

### 基础设施

Docker Compose、ChromaDB（chromadb/chroma:latest）、Redis 7 Alpine、Nginx（前端静态文件+API代理）

---

## 项目目录结构

```
knowbase/
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── README.md
│
├── backend/
│   ├── Dockerfile                      # Python 3.11-slim, pip install, uvicorn :8000
│   ├── requirements.txt
│   └── app/
│       ├── __init__.py
│       ├── main.py                     # FastAPI 入口
│       ├── config.py                   # Settings(BaseSettings) 配置管理
│       ├── api/
│       │   ├── __init__.py
│       │   ├── deps.py                 # get_db / get_settings 依赖注入
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── workspaces.py       # 工作区 CRUD
│       │       ├── documents.py        # 文档上传与管理
│       │       ├── search.py           # RAG 检索与对话（SSE 流式）
│       │       └── settings.py         # 系统设置
│       ├── core/
│       │   ├── __init__.py
│       │   ├── rag_engine.py           # RAG 引擎
│       │   ├── llm_manager.py          # 多模型 LLM 管理
│       │   ├── embedding.py            # Embedding 服务
│       │   ├── vector_store.py         # ChromaDB 向量存储
│       │   └── text_splitter.py        # 中文感知文本切片
│       ├── collector/
│       │   ├── __init__.py
│       │   ├── pipeline.py             # 文档处理流水线
│       │   ├── tasks.py                # Celery 异步任务
│       │   └── parsers/
│       │       ├── __init__.py
│       │       ├── base.py             # BaseParser 抽象基类
│       │       ├── pdf_parser.py       # PDF（PyMuPDF）
│       │       ├── docx_parser.py      # Word（python-docx）
│       │       ├── pptx_parser.py      # PPT（python-pptx）
│       │       └── markdown_parser.py  # Markdown
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py                 # 异步引擎 + Session
│       │   ├── workspace.py
│       │   ├── document.py
│       │   └── conversation.py
│       └── schemas/
│           ├── __init__.py
│           └── schemas.py              # Pydantic 请求/响应模型
│
├── feishu-bot/
│   ├── Dockerfile                      # Python 3.11-slim, python -m bot.main
│   ├── requirements.txt
│   └── bot/
│       ├── __init__.py
│       ├── main.py                     # WebSocket 长连接入口
│       ├── handler.py                  # 消息处理分发
│       ├── commands.py                 # 指令解析路由
│       ├── cards.py                    # 飞书消息卡片
│       ├── auth.py                     # Token 管理
│       └── config.py                   # Bot 配置
│
├── frontend/
│   ├── Dockerfile                      # Node 20 build + nginx:alpine serve
│   ├── nginx.conf                      # SPA 路由 + /api 反向代理
│   ├── package.json
│   ├── vite.config.ts                  # /api → http://localhost:8000
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                     # Ant Design Layout + Sider + Router
│       ├── pages/
│       │   ├── Dashboard.tsx           # 仪表盘
│       │   ├── Workspaces.tsx          # 工作区管理
│       │   ├── Documents.tsx           # 文档列表
│       │   ├── Upload.tsx              # 文件上传
│       │   ├── SearchTest.tsx          # 检索测试
│       │   └── Settings.tsx            # 系统设置
│       ├── components/
│       │   ├── FileUploader.tsx
│       │   └── SourceCard.tsx
│       ├── services/
│       │   └── api.ts                  # Axios API 调用层
│       └── stores/
│           └── appStore.ts             # Zustand 状态管理
│
└── data/
    ├── uploads/
    ├── vectordb/
    └── sqlite/
```

---

## 一、后端核心设计

### 1.1 配置管理（app/config.py）

使用 `pydantic-settings` 的 `BaseSettings`，从 `.env` 文件加载，字段如下：

| 字段 | 类型 | 默认值 |
|------|------|--------|
| DATABASE_URL | str | `sqlite+aiosqlite:///./data/sqlite/knowbase.db` |
| REDIS_URL | str | `redis://localhost:6379/0` |
| CHROMA_HOST | str | `localhost` |
| CHROMA_PORT | int | `8000` |
| UPLOAD_DIR | str | `./data/uploads` |
| UPLOAD_MAX_SIZE_MB | int | `50` |
| CHUNK_SIZE | int | `1000` |
| CHUNK_OVERLAP | int | `200` |
| RAG_TOP_K | int | `5` |
| DEFAULT_LLM_PROVIDER | str | `deepseek` |
| DEFAULT_LLM_MODEL | str | `deepseek-chat` |
| DEFAULT_EMBEDDING | str | `BAAI/bge-small-zh-v1.5` |
| CONVERSATION_HISTORY_LIMIT | int | `10` |
| OPENAI_API_KEY | Optional[str] | None |
| DEEPSEEK_API_KEY | Optional[str] | None |
| DASHSCOPE_API_KEY | Optional[str] | None |
| ZHIPU_API_KEY | Optional[str] | None |
| OLLAMA_BASE_URL | Optional[str] | None |
| FEISHU_APP_ID | Optional[str] | None |
| FEISHU_APP_SECRET | Optional[str] | None |
| JWT_SECRET | str | `knowbase-secret-key-change-in-production` |

导出模块级单例 `settings = Settings()`。

### 1.2 FastAPI 入口（app/main.py）

```python
# 关键设计点：
# 1. Lifespan 上下文管理器：启动时创建 DB 表、检查 ChromaDB 连接（非致命）
# 2. CORS 中间件：开发阶段 allow_origins=["*"]
# 3. 4 组路由挂载在 /api 前缀下
# 4. 静态文件服务：/uploads 挂载 UPLOAD_DIR
# 5. 健康检查：GET / 返回 {"status": "ok"}
```

### 1.3 数据模型（app/models/）

**Workspace：**
- `id` String(36) PK (UUID)
- `name` String(255) NOT NULL
- `description` Text (默认空)
- `slug` String(255) UNIQUE INDEX
- `created_at` / `updated_at` DateTime(tz)
- 关系：`documents = relationship("Document", cascade="all, delete-orphan", lazy="selectin")`

**Document：**
- `id` String(36) PK (UUID)
- `workspace_id` String(36) FK → workspaces.id (CASCADE)
- `filename` String(512)
- `file_path` String(1024)
- `file_type` String(50) — 文件扩展名
- `file_size` Integer (默认 0)
- `chunk_count` Integer (默认 0)
- `status` String(20) — `pending / processing / ready / failed`，带索引
- `error_message` Text (nullable)
- `created_at` / `updated_at` DateTime(tz)

**Conversation：**
- `id` String(36) PK (UUID)
- `user_id` String(255) INDEX
- `workspace_id` String(36) FK → workspaces.id (SET NULL)
- `role` String(20) — `"user"` 或 `"assistant"`
- `content` Text
- `sources` JSON (nullable)
- `created_at` DateTime(tz)

**数据库引擎：** `create_async_engine(DATABASE_URL)` + `async_sessionmaker(AsyncSession)`。`get_db` 依赖使用 `async with` 自动管理会话，自动 commit/rollback。

### 1.4 API 路由

**所有路由挂载在 `/api` 前缀下。**

#### 工作区管理（/api/workspaces）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /workspaces | 列出所有工作区 |
| POST | /workspaces | 创建工作区（自动从 name 生成 slug） |
| GET | /workspaces/{id} | 工作区详情（含文档计数） |
| PUT | /workspaces/{id} | 更新工作区 |
| DELETE | /workspaces/{id} | 删除工作区（级联删除文档） |

#### 文档管理（/api/workspaces/{id}/documents 和 /api/documents/{id}）

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /workspaces/{id}/documents | 上传文件（multipart，支持多文件） |
| GET | /workspaces/{id}/documents | 列出文档（可选 status/file_type 过滤） |
| GET | /documents/{id} | 文档详情 |
| GET | /documents/{id}/status | 处理状态 |
| DELETE | /documents/{id} | 删除文档（文件+DB+向量） |

**上传流程：**
1. 验证文件扩展名白名单（pdf/docx/doc/pptx/ppt/xlsx/xls/csv/txt/md/rst/html/htm/json/xml/yaml/yml）
2. 验证文件大小（≤ UPLOAD_MAX_SIZE_MB）
3. 生成 UUID 文件名，保存到 `{UPLOAD_DIR}/{workspace_id}/{uuid}{ext}`
4. 创建 Document 记录（status=pending）
5. 内联处理：提取文本 → 切片 → ChromaDB 存储 → status=ready
6. 返回 UploadResponse

**文件解析器（内联在 documents.py 中）：**
- PDF: PyMuPDF (fitz) 逐页提取
- DOCX/DOC: python-docx 段落文本
- PPTX/PPT: python-pptx 逐 slide 文本
- XLSX/XLS: pandas.read_excel → to_string
- TXT/MD/CSV/JSON/XML/YAML: chardet 编码检测 + 直读
- HTML/HTM: BeautifulSoup("html.parser") 提取可见文本

#### 检索与对话（/api/search 和 /api/chat）

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /search | RAG 检索，返回 top-K 文档片段 |
| POST | /chat | 完整 RAG 问答，SSE 流式回答 |

**POST /search 流程：**
1. 用 SentenceTransformer（BGE-small-zh-v1.5）对 query 做 embedding
2. 连接 ChromaDB，搜索对应 workspace 的 collection（collection 命名：`ws_{workspace_id}`，短横线替换为下划线）
3. 如果未指定 workspace，搜索所有 `ws_*` 前缀的 collection
4. 距离转相似度：`score = max(0, 1 - distance)`（cosine space）
5. 按 score 降序排序，取 top_k 返回

**POST /chat SSE 流式流程：**
1. 保存用户消息到 Conversation 表
2. 调用 /search 获取上下文
3. 获取最近 10 轮对话历史
4. 构建中文 RAG Prompt
5. 调用 litellm.acompletion(stream=True) 流式生成
6. SSE 事件序列：`{"token":"..."}` → `{"sources":[...]}` → `{"done":true,"conversation_id":"...","confidence":0.xx}`
7. 保存 assistant 消息到 Conversation 表

**RAG Prompt 模板（中文）：**
```
你是 KnowBase 私人知识库助手。请根据以下参考资料回答用户的问题。

规则：
1. 仅基于提供的参考资料回答，不要编造信息
2. 如果参考资料中没有相关内容，明确告知用户「知识库中暂未找到相关信息」
3. 回答时引用来源文件和页码，格式为 [文件名 第X页]
4. 保持回答简洁准确

参考资料：
{context}

用户问题：{question}
```

**LLM 流式调用 provider 映射：**

| provider | litellm_model | api_base |
|----------|---------------|----------|
| openai | `{model}` | 默认 |
| deepseek | `deepseek/{model}` | `https://api.deepseek.com/v1` |
| qwen/dashscope | `openai/{model}` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| glm/zhipu | `openai/{model}` | `https://open.bigmodel.cn/api/paas/v4` |
| ollama | `ollama/{model}` | 从 OLLAMA_BASE_URL 读取 |

#### 系统设置（/api/settings）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | /settings/llm | 获取 LLM 配置（API Key 脱敏显示） |
| PUT | /settings/llm | 更新 LLM provider/model/key |
| POST | /settings/llm/test | 测试模型连通性 |
| GET | /settings/embedding | 获取 Embedding 配置 |
| PUT | /settings/embedding | 更新 Embedding 模型 |
| GET | /settings/system | 系统信息（文档数/工作区数/存储用量） |

---

## 二、核心模块设计

### 2.1 Embedding 服务（app/core/embedding.py）

**类：EmbeddingService**

```python
# 支持两种 provider：
# - "local": sentence-transformers, 模型 BAAI/bge-small-zh-v1.5 (512维)
# - "openai": litellm.aembedding, 模型 text-embedding-3-small (1536维)

# 关键方法：
# async embed_texts(texts: list[str]) -> list[list[float]]  — 批量 embedding
# async embed_query(query: str) -> list[float]              — 单条 query
# get_dimension() -> int                                    — 向量维度

# 本地模型使用 SentenceTransformer.encode(normalize_embeddings=True, batch_size=64)
# 通过 run_in_executor 在线程池中运行避免阻塞事件循环
# 模型延迟加载（首次调用时才加载）
```

### 2.2 向量存储（app/core/vector_store.py）

**类：VectorStore**

```python
# 封装 ChromaDB 操作，每个 workspace 一个 collection
# collection 命名：f"ws_{workspace_id}".replace("-", "_")

# 构造：
# - host="local" → chromadb.PersistentClient(path="./data/chromadb")
# - host=其他 → chromadb.HttpClient(host, port) + heartbeat 验证

# 关键方法（全部 async）：
# get_or_create_collection(workspace_id) → Collection
# add_documents(workspace_id, doc_ids, texts, metadatas, embeddings)
# search(workspace_id, query_embedding, top_k=5) → [{id, content, metadata, distance}]
# delete_documents(workspace_id, doc_ids)
# delete_collection(workspace_id)
# get_collection_stats(workspace_id) → {count, last_updated}

# 注意：metadata 中的 None 值必须过滤掉（ChromaDB 不允许 None value）
# 空 metadata 替换为 {"empty": True}
```

### 2.3 LLM 管理器（app/core/llm_manager.py）

**类：LLMManager**

```python
# 通过 litellm 统一调用多家 LLM

# PROVIDER_CONFIGS 常量定义每家：
# {
#   "openai": {"models": ["gpt-4o","gpt-4o-mini","gpt-3.5-turbo"], "env_key": "OPENAI_API_KEY"},
#   "deepseek": {"models": ["deepseek-chat","deepseek-reasoner"], "env_key": "DEEPSEEK_API_KEY", "base_url": "https://api.deepseek.com/v1"},
#   "qwen": {"models": ["qwen-turbo","qwen-plus","qwen-max"], "env_key": "QWEN_API_KEY", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
#   "glm": {"models": ["glm-4-flash","glm-4-plus"], "env_key": "GLM_API_KEY", "base_url": "https://open.bigmodel.cn/api/paas/v4"},
#   "ollama": {"models": [], "base_url": "from env OLLAMA_BASE_URL"}
# }

# 关键方法：
# async generate(messages, provider, model, temperature=0.3, max_tokens=2000) → str
# async generate_stream(...) → AsyncGenerator[str]
# async test_connection(provider, model) → {success, latency_ms, error}
# get_available_providers() → [{name, models, configured}]

# 错误处理：RateLimitError → "请求频率超限"
#          Timeout → "请求超时"
#          AuthenticationError → "API Key 无效"
# Ollama 使用虚拟 api_key="ollama"
```

### 2.4 文本切片器（app/core/text_splitter.py）

**类：TextSplitter**

```python
# 中文感知的递归字符切片器

# 默认分隔符优先级：
# ["\n\n", "\n", "。", ".", "！", "!", "？", "?", "；", ";", " ", ""]

# 构造：TextSplitter(chunk_size=1000, chunk_overlap=200)

# 关键方法：
# split_text(text, metadata) → [{content, metadata}]
#   metadata 包含 chunk_index 和 total_chunks
# split_documents(documents: list[dict]) → list[dict]
#   批量处理，每个 document 有 content 和 metadata 字段

# 核心算法 _recursive_split：
# 1. 按当前优先级分隔符切分
# 2. 合并过短的片段（不超过 chunk_size）
# 3. 超长片段递归使用下一优先级分隔符
# 4. 最终兜底：硬字符截断 _force_split

# 重叠处理 _add_overlap：
# 将前一个 chunk 的最后 chunk_overlap 个字符拼到当前 chunk 开头
```

### 2.5 RAG 引擎（app/core/rag_engine.py）

**类：RAGEngine**

```python
# 构造依赖注入：VectorStore + EmbeddingService + LLMManager + TextSplitter

# 核心方法：
# async query(question, workspace_id, history, top_k=5) → {answer, sources, confidence}
#   1. embed_query → 2. vector_store.search → 3. 构建 context → 4. 构建 prompt → 5. LLM 生成
#
# async query_stream(...) → AsyncGenerator[dict]
#   yield {"type":"sources",...} → 多个 {"type":"token","content":...} → {"type":"done","confidence":...}

# 置信度计算：math.exp(-avg_distance)，归一化到 [0, 1]

# 对话历史截断：最近 20 条消息（10 轮）

# System Prompt（无上下文时 fallback）：
# "你是 KnowBase 私人知识库助手。抱歉，知识库中暂未找到与该问题相关的信息。
#  建议您上传相关文档到知识库后再试。"
```

### 2.6 文档处理流水线（app/collector/pipeline.py）

**类：DocumentPipeline**

```python
# 构造依赖：embedding_service + vector_store + text_splitter（鸭子类型）

# 解析器工厂 _get_parser(file_type) → BaseParser
# 支持 12 种扩展名映射：
# pdf→PDFParser, docx/doc→DocxParser, pptx/ppt→PptxParser,
# md/markdown→MarkdownParser, txt→_TxtParser, xlsx→_XlsxParser,
# csv→_CsvParser, html/htm→_HtmlParser
# 解析器延迟实例化并缓存（_PARSER_CACHE 类级字典）

# 主入口：
# async process_document(document_id, file_path, file_type, workspace_id, db_session) → dict
# 六步流水线：
# 1. status="processing"
# 2. parser.parse(file_path) → [{content, metadata}]
# 3. text_splitter.split_documents(raw_chunks)
# 4. embedding_service.embed_texts(texts)
# 5. vector_store.add_documents(workspace_id, doc_ids, texts, embeddings, metadatas)
#    doc_ids 格式：{document_id}_chunk_{idx}
# 6. status="ready", chunk_count=N
# 异常：status="failed", error_message=str(e)

# 内联解析器设计：
# _TxtParser: chardet 编码检测，decode 后整体返回一个 chunk
# _XlsxParser: openpyxl read_only 模式，每个 sheet 一个 chunk，行转 "header: value | ..." 格式
# _CsvParser: chardet + csv.reader，类似 xlsx 的键值对格式
# _HtmlParser: BeautifulSoup("html.parser")，去除 script/style/noscript，提取 title 作 heading

# 所有解析器返回统一格式：[{content: str, metadata: {page_num, heading, source_file}}]
```

**BaseParser 抽象基类：**
```python
class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> list[dict]: ...
    # 返回 [{content: str, metadata: {page_num: int, heading: str, source_file: str}}]
```

**外部解析器（独立文件）：**
- `pdf_parser.py`: PyMuPDF, 逐页提取, 读 TOC/bookmarks 作 heading, 检测扫描件
- `docx_parser.py`: python-docx, 按 element.body 顺序交错段落和表格, 追踪标题层级, 表格转 pipe 分隔文本
- `pptx_parser.py`: python-pptx, 每 slide 一个 chunk, 提取所有 shape 文本+表格+备注, slide title 作 heading
- `markdown_parser.py`: 按 ATX 标题切分, 保留代码块, 去除 HTML 标签, 无标题时整体一个 chunk

---

## 三、飞书 Bot 设计

### 3.1 连接方式

使用 `lark_oapi` SDK 的 **WebSocket 长连接**（`lark.ws.Client`），无需公网 IP 和域名。

```python
# main.py 启动流程：
# 1. 加载 BotConfig
# 2. 创建 asyncio event loop
# 3. 初始化：Redis → TokenManager → CommandRouter → MessageHandler
# 4. 构建 event dispatcher，注册 im.message.receive_v1 回调
# 5. lark.ws.Client(app_id, app_secret, event_handler=dispatcher).start()
# 6. SDK 回调是同步的，用 asyncio.run_coroutine_threadsafe 桥接到 async handler
# 7. SIGINT/SIGTERM 优雅关闭所有组件
```

### 3.2 配置（bot/config.py）

```python
class BotConfig(BaseSettings):
    FEISHU_APP_ID: str
    FEISHU_APP_SECRET: str
    BACKEND_URL: str = "http://localhost:8000"
    REDIS_URL: str = "redis://localhost:6379/1"  # 注意用 DB 1，与后端 DB 0 隔离
    BOT_NAME: str = "KnowBase"
    LOG_LEVEL: str = "INFO"
```

### 3.3 Token 管理（bot/auth.py）

```python
class TokenManager:
    # 管理 tenant_access_token 生命周期
    # POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
    # Body: {"app_id": ..., "app_secret": ...}
    # 内存缓存 token，在到期前 5 分钟自动刷新
    # async get_token() → str
```

### 3.4 指令系统（bot/commands.py）

```python
class CommandRouter:
    COMMANDS = {"search", "status", "ws", "help", "feedback"}

    # parse_command(text) → (command, args)
    # 以 / 开头为指令，否则默认 ("ask", text)

    # route_command(command, args, user_id, context) → card dict
    # ask    → POST backend /api/chat → build_answer_card
    # search → POST backend /api/search → 搜索结果卡片
    # status → GET backend /api/settings/system → build_status_card
    # ws     → Redis 读写 knowbase:ws:{user_id}（TTL 7天）切换工作区
    # help   → build_help_card
    # feedback → 占位，返回确认卡片
```

### 3.5 消息处理（bot/handler.py）

```python
class MessageHandler:
    # async handle_message(event_data):
    #   1. 解析 v2.0 event 信封：sender_id, message_id, chat_type, message_type
    #   2. 仅处理 msg_type=="text"
    #   3. 解析 JSON content {"text":"..."}，去除 @_user_N @提及
    #   4. command_router.parse_command → route_command
    #   5. reply_message(message_id, card)
    #   6. 异常时 send error card

    # reply_message(message_id, card):
    #   POST /im/v1/messages/{message_id}/reply
    #   msg_type="interactive", content=card JSON
```

### 3.6 消息卡片（bot/cards.py）

全部使用飞书卡片 Schema 2.0，中文，`lark_md` 文本标签：

| 函数 | 标题颜色 | 内容 |
|------|---------|------|
| build_answer_card(answer, sources, confidence) | 蓝色 | 回答 + 来源引用 + 置信度 + 反馈按钮 |
| build_help_card() | 绿色 | 指令列表说明 |
| build_status_card(stats) | 紫色 | 工作区数/文档数/切片数/最近更新 |
| build_not_found_card(query) | 灰色 | 未找到提示 + 建议 |
| build_error_card(error_msg) | 红色 | 错误信息 + 排查建议 |

置信度颜色：≥0.8 绿色, ≥0.5 橙色, <0.5 红色。

---

## 四、前端设计

### 4.1 布局与路由

Ant Design ConfigProvider (zh_CN) → Layout → 可折叠暗色 Sider + Header("私人知识数据库") + Content

| 路由 | 页面 | 菜单名 |
|------|------|--------|
| / | Dashboard | 仪表盘 |
| /workspaces | Workspaces | 工作区 |
| /workspaces/:id/documents | Documents | — |
| /upload | Upload | 文件上传 |
| /search | SearchTest | 检索测试 |
| /settings | Settings | 系统设置 |

主题：`colorPrimary: '#1677ff'`, `borderRadius: 6`

### 4.2 各页面功能

**Dashboard:** Statistic 卡片展示工作区总数/文档总数/知识片段总数，快速操作按钮（上传文件/测试搜索），最近活动列表

**Workspaces:** Table 列出工作区（名称/描述/文档数/创建时间），创建 Modal（name + description），删除确认，点击行跳转文档列表

**Documents:** 从 URL params 获取 workspace_id，Table 展示文档（文件名/类型/大小/切片数/状态/时间），状态标签：pending=orange, processing=blue(带 Spin), ready=green, failed=red，processing 状态自动轮询刷新

**Upload:** react-dropzone 拖拽区域，accept 限制文件类型，Workspace 下拉选择器，文件列表带 Progress 进度条，顺序上传，每文件显示状态

**SearchTest:** 双模式切换（知识检索/对话问答），Workspace 筛选（可选），输入问题，展示 RAG 结果：回答文本 + 来源卡片列表（文件名/页码/内容预览/相关度评分）+ 耗时统计

**Settings:** Tabs 分三个标签页：LLM 设置（provider/model/api_key/test连接），Embedding 设置（provider/model），系统信息

### 4.3 API 层（services/api.ts）

Axios 实例：`baseURL: '/api'`, `timeout: 60000`

关键 TypeScript 接口：
```typescript
interface Workspace { id, name, description, document_count, created_at }
interface Document { id, workspace_id, filename, file_type, file_size, chunk_count, status, created_at }
interface SearchResult { answer, sources: SourceItem[], timing }
interface SourceItem { filename, page_number, content, score }
interface LLMSettings { provider, model, api_key, base_url? }
interface SystemInfo { version, total_workspaces, total_documents, total_chunks, backend_uptime }
```

SSE 聊天：`chatQuery` 返回 URL 字符串，消费端用 `EventSource` 处理流式事件。

### 4.4 状态管理（stores/appStore.ts）

Zustand store：
```typescript
{
  currentWorkspace: Workspace | null,
  workspaces: Workspace[],
  documents: Document[],
  settings: LLMSettings,
  actions: { fetchWorkspaces, setCurrentWorkspace, fetchDocuments }
}
```

---

## 五、Docker 部署

### 5.1 docker-compose.yml

```yaml
# 6 个服务：
# backend   - build ./backend, port 8000:8000, depends: redis+chromadb
# worker    - build ./backend, command: celery -A app.collector.tasks worker
# feishu-bot - build ./feishu-bot, BACKEND_URL=http://backend:8000, Redis DB 1
# frontend  - build ./frontend, port 3000:80, nginx
# chromadb  - image chromadb/chroma:latest, port 8001:8000
# redis     - image redis:7-alpine, port 6379, AOF 持久化

# 共享网络: knowbase-net (bridge)
# 数据卷: backend_data, backend_uploads, chroma_data, redis_data
# 所有服务使用 env_file: .env
```

### 5.2 各服务 Dockerfile

**backend:** `FROM python:3.11-slim` → WORKDIR /app → COPY requirements.txt → pip install → COPY app → EXPOSE 8000 → CMD uvicorn

**feishu-bot:** `FROM python:3.11-slim` → WORKDIR /app → COPY requirements.txt → pip install → COPY bot → CMD python -m bot.main

**frontend:** 多阶段构建。Stage 1: `FROM node:20-alpine` → npm install → npm run build。Stage 2: `FROM nginx:alpine` → COPY dist → COPY nginx.conf → EXPOSE 80

### 5.3 前端 nginx.conf

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;  # SPA 路由
    }

    location /api/ {
        proxy_pass http://backend:8000;    # API 反向代理
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;               # SSE 需要关闭缓冲
        proxy_cache off;
    }
}
```

---

## 六、关键设计决策与注意事项

1. **ChromaDB collection 命名统一为 `ws_{workspace_id}`**（短横线替换为下划线），所有模块必须一致
2. **metadata 必须包含 `source_file` 键**（RAG 引擎用它引用来源文件名）
3. **ChromaDB 创建 collection 时设置 `metadata={"hnsw:space": "cosine"}`**
4. **飞书 Bot 使用 Redis DB 1，后端使用 DB 0**，避免键冲突
5. **文档上传的处理目前是内联同步执行**（在 documents.py 的 _process_document 中），Celery Worker 定义了但未实际使用，后续可替换
6. **所有外部服务调用（ChromaDB/LLM/飞书API）必须有 try/except 和 loguru 日志**
7. **LLM 调用统一通过 litellm**，不直接调用各家 SDK
8. **Embedding 本地模型延迟加载**，避免启动时阻塞
9. **所有用户可见的文本（Prompt/卡片/UI）使用中文**
10. **Python 版本要求 3.11+**，3.14 可能存在兼容性问题
