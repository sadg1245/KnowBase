# 拾光 KnowBase — 私人 AI 学习知识库

拾光会阅读你的私人资料，并陪你完成“理解、练习、复习、回顾”的学习闭环。它既可以在电脑和手机浏览器中使用，也可以通过飞书机器人随时提问和复习。

## 学习版新增能力

- 学习主页：今日任务、连续学习、本周时长和薄弱知识点。
- 知识库详情：学习目标、资料摘要、章节结构、核心知识点和掌握进度。
- 六种 AI 学习方式：直接回答、通俗讲解、深入学习、苏格拉底引导、费曼复述和随堂测试。
- 知识卡片与间隔复习：根据“忘记、模糊、记住、熟练”自动安排下次复习。
- AI 练习与错题本：从知识点生成题目，记录错误并更新掌握度。
- 学习报告：按 7、30、90 天查看学习节奏、复习量和练习正确率。
- PWA 移动体验：可添加到手机桌面，并缓存基础应用外壳。
- 私人空间保护：远程部署时可开启密码锁；飞书机器人支持服务令牌。

### 开启私人空间密码

生产或远程访问时，在 `.env` 中设置：

```env
AUTH_ENABLED=true
JWT_SECRET=请替换为足够长的随机字符串
SERVICE_TOKEN=请替换为飞书机器人专用随机令牌
BACKEND_ACCESS_TOKEN=与 SERVICE_TOKEN 保持一致
CORS_ORIGINS=https://你的访问域名
```

首次打开 Web 页面时，系统会引导设置私人空间密码。本地开发默认关闭密码锁，避免影响现有使用方式。

基于 RAG（检索增强生成）的个人知识库系统，支持导入多种格式文档，通过飞书机器人实现移动端智能问答。

## 项目简介

KnowBase 是一个自托管的私人知识数据库，核心理念是 **"你的知识，随时可问"**。

用户可以将本地的 Word、PDF、PPT、Markdown 等格式文件导入系统，系统自动完成文档解析、向量化存储和索引构建。当用户通过手机飞书向机器人提问时，系统基于知识库进行 RAG 检索增强生成，返回精准答案并标注来源引用。

**核心能力：**

- 支持 9 种文档格式导入（PDF、DOCX、PPTX、Markdown、TXT、XLSX、CSV、HTML、DOC）
- 飞书机器人 WebSocket 长连接，无需公网 IP，本地即可运行
- 多模型 LLM 灵活切换（DeepSeek、OpenAI、通义千问、智谱 GLM、Ollama 本地模型）
- 中文优化的 Embedding 模型（BGE-small-zh），检索精度高
- RAG 流式回答，实时生成，附带来源文件引用
- 工作区隔离，支持按主题分类管理知识
- Web 管理界面，文件上传、文档管理、检索测试一站式操作
- Docker Compose 一键部署

## 项目结构

```
anything_llm/
├── docker-compose.yml              # Docker 部署配置（6 个服务）
├── docker-compose.dev.yml          # 开发环境覆盖配置
├── .env.example                    # 环境变量模板
│
├── backend/                        # FastAPI 后端服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # FastAPI 应用入口
│       ├── config.py               # 配置管理（pydantic-settings）
│       ├── api/
│       │   ├── deps.py             # 依赖注入（DB Session、Settings）
│       │   └── routes/
│       │       ├── workspaces.py   # 工作区 CRUD API
│       │       ├── documents.py    # 文档上传与管理 API
│       │       ├── search.py       # RAG 检索与对话 API（SSE 流式）
│       │       └── settings.py     # 系统设置 API（LLM/Embedding 配置）
│       ├── core/
│       │   ├── rag_engine.py       # RAG 引擎（检索 → 上下文组装 → LLM 生成）
│       │   ├── llm_manager.py      # 多模型 LLM 管理器（LiteLLM 统一代理）
│       │   ├── embedding.py        # Embedding 服务（本地 BGE / OpenAI）
│       │   ├── vector_store.py     # ChromaDB 向量存储操作
│       │   └── text_splitter.py    # 中文感知文本切片器
│       ├── collector/
│       │   ├── pipeline.py         # 文档处理流水线（解析→切片→向量化→入库）
│       │   ├── tasks.py            # Celery 异步任务定义
│       │   └── parsers/
│       │       ├── base.py         # 解析器抽象基类
│       │       ├── pdf_parser.py   # PDF 解析（PyMuPDF）
│       │       ├── docx_parser.py  # Word 解析（python-docx）
│       │       ├── pptx_parser.py  # PPT 解析（python-pptx）
│       │       └── markdown_parser.py  # Markdown 解析
│       ├── models/                 # SQLAlchemy 数据模型
│       │   ├── base.py             # 异步引擎与会话管理
│       │   ├── workspace.py        # 工作区模型
│       │   ├── document.py         # 文档模型
│       │   └── conversation.py     # 对话历史模型
│       └── schemas/
│           └── schemas.py          # Pydantic 请求/响应模型
│
├── feishu-bot/                     # 飞书机器人服务
│   ├── Dockerfile
│   ├── requirements.txt
│   └── bot/
│       ├── main.py                 # 入口：WebSocket 长连接
│       ├── handler.py              # 消息处理与分发
│       ├── commands.py             # 指令解析与路由
│       ├── cards.py                # 飞书消息卡片构建
│       ├── auth.py                 # Token 管理（自动刷新）
│       └── config.py               # Bot 配置
│
├── frontend/                       # React Web 前端
│   ├── Dockerfile
│   ├── nginx.conf                  # Nginx 配置（SPA + API 代理）
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── App.tsx                 # 主布局（侧边导航 + 路由）
│       ├── main.tsx                # React 入口
│       ├── pages/
│       │   ├── Dashboard.tsx       # 仪表盘（统计概览）
│       │   ├── Workspaces.tsx      # 工作区管理
│       │   ├── Documents.tsx       # 文档列表与状态
│       │   ├── Upload.tsx          # 文件拖拽上传
│       │   ├── SearchTest.tsx      # RAG 检索测试
│       │   └── Settings.tsx        # 系统设置
│       ├── components/
│       │   ├── FileUploader.tsx    # 文件上传组件
│       │   └── SourceCard.tsx      # 来源引用卡片
│       ├── services/
│       │   └── api.ts              # Axios API 调用层
│       └── stores/
│           └── appStore.ts         # Zustand 状态管理
│
└── data/                           # 数据目录（Docker volume 映射）
    ├── uploads/                    # 原始文件存储
    ├── vectordb/                   # ChromaDB 持久化数据
    └── sqlite/                     # SQLite 数据库文件
```

## 技术栈

### 后端

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI (Python 3.11+) | 异步原生，自动 OpenAPI 文档 |
| 任务队列 | Celery + Redis | 文档解析/向量化异步处理 |
| 文档解析 | PyMuPDF / python-docx / python-pptx / BeautifulSoup | 9 种格式全覆盖 |
| 文本切片 | 自研 TextSplitter | 递归字符切分，中文标点感知 |
| Embedding | sentence-transformers (BGE-small-zh-v1.5) | 中文优化，本地运行，可切换 OpenAI |
| 向量数据库 | ChromaDB | 轻量开箱即用，每工作区独立 collection |
| 关系数据库 | SQLite / PostgreSQL | SQLAlchemy ORM，可无缝切换 |
| LLM 接入 | LiteLLM | 统一代理调用 OpenAI/DeepSeek/通义千问/GLM/Ollama |
| 日志 | Loguru | 结构化日志，全链路追踪 |

### 前端

| 组件 | 技术 | 说明 |
|------|------|------|
| 框架 | React 18 + TypeScript | 类型安全 |
| UI 库 | Ant Design 5.x | 中文友好，企业级组件 |
| 构建工具 | Vite | 快速 HMR 开发体验 |
| 状态管理 | Zustand | 轻量无 boilerplate |
| 文件上传 | react-dropzone | 拖拽上传 + 进度显示 |

### 飞书机器人

| 组件 | 技术 | 说明 |
|------|------|------|
| SDK | lark-oapi | 飞书官方 Python SDK |
| 连接方式 | WebSocket 长连接 | 无需公网 IP 和域名 |
| HTTP 客户端 | httpx | 异步 HTTP 调用 |
| 缓存 | Redis | Token 缓存 + 用户状态 |

### 基础设施

| 组件 | 技术 | 说明 |
|------|------|------|
| 容器化 | Docker + Docker Compose | 一键启动全部 6 个服务 |
| 反向代理 | Nginx | SPA 路由 + API 代理 |
| 缓存/队列 | Redis 7 | 会话管理 + Celery 消息代理 |

## 项目启动

### 方式一：Docker Compose 部署（推荐）

**前置条件：** 安装 Docker 和 Docker Compose

```bash
# 1. 进入项目目录
cd E:\anything_llm

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入飞书 App ID/Secret 和 LLM API Key

# 3. 一键启动所有服务
docker compose up -d

# 4. 访问服务
# Web 管理界面:  http://localhost:3000
# API 文档:      http://localhost:8000/docs
# 飞书机器人:    在飞书中搜索你的机器人名称开始对话
```

**Docker 服务说明：**

| 服务 | 端口 | 说明 |
|------|------|------|
| frontend | 3000 | Web 管理界面 |
| backend | 8000 | FastAPI 后端 API |
| chromadb | 8001 | ChromaDB 向量数据库 |
| redis | 6379 | Redis 缓存/队列 |
| feishu-bot | — | 飞书机器人（无端口，WebSocket 出站连接） |
| worker | — | Celery 异步任务 Worker |

### 方式二：本地开发启动

**前置条件：** Python 3.11+、Node.js 18+、Redis、ChromaDB

#### 1. 启动基础设施

```bash
# 启动 Redis
docker run -d --name knowbase-redis -p 6379:6379 redis:7-alpine

# 启动 ChromaDB
docker run -d --name knowbase-chroma -p 8001:8000 chromadb/chroma:latest
```

#### 2. 启动后端

```bash
cd backend

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp ../.env.example ../.env
# 编辑 .env 填入配置

# 启动开发服务器（热重载）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

后端启动后访问 http://localhost:8000/docs 查看 API 文档。

#### 3. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端启动后访问 http://localhost:5173，API 请求自动代理到后端。

#### 4. 启动飞书机器人（可选）

```bash
cd feishu-bot

# 安装依赖
pip install -r requirements.txt

# 启动 Bot（确保 .env 中已配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET）
python -m bot.main
```

### 飞书机器人配置

1. 登录 [飞书开放平台](https://open.feishu.cn/)，进入开发者后台
2. 创建「自建应用」，获取 `App ID` 和 `App Secret`
3. 在「应用功能」中启用「机器人」能力
4. 配置 API 权限：`im:message`、`im:message:send_as_bot`、`im:chat`、`im:resource`
5. 在「事件与回调」中选择「使用长连接接收事件」，订阅 `im.message.receive_v1`
6. 发布应用版本

### 飞书指令

| 指令 | 格式 | 功能 |
|------|------|------|
| 直接提问 | `Python 装饰器怎么用？` | 基于知识库 RAG 回答 |
| 搜索 | `/search 关键词` | 仅检索，返回相关文档片段 |
| 知识库状态 | `/status` | 查看文档数量、最近更新等 |
| 切换工作区 | `/ws 工作区名称` | 切换当前查询的知识库工作区 |
| 帮助 | `/help` | 显示所有可用指令 |

### 支持的文档格式

| 格式 | 解析器 | 说明 |
|------|--------|------|
| PDF | PyMuPDF | 按物理页提取文本；不提供 OCR |
| Word (.docx) | python-docx | 保留段落结构和标题层级 |
| Word (.doc) | 转换后解析 | 旧格式 |
| PPT (.pptx) | python-pptx | 逐页提取文本+备注 |
| Markdown | 内置解析 | 按标题分段，保留代码块 |
| TXT | chardet + 直读 | 自动检测编码 |
| Excel (.xlsx) | openpyxl | 每行转为键值对文本 |
| CSV | 内置 csv 模块 | 表头+数据行配对 |
| HTML | BeautifulSoup | 去除标签，保留正文 |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/workspaces` | 获取所有工作区 |
| POST | `/api/workspaces` | 创建工作区 |
| DELETE | `/api/workspaces/{id}` | 删除工作区 |
| POST | `/api/workspaces/{id}/documents` | 上传文件 |
| GET | `/api/workspaces/{id}/documents` | 获取文档列表 |
| DELETE | `/api/documents/{id}` | 删除文档 |
| POST | `/api/search` | RAG 知识检索 |
| POST | `/api/chat` | 知识问答（SSE 流式） |
| GET/PUT | `/api/settings/llm` | LLM 模型配置 |
| GET/PUT | `/api/settings/embedding` | Embedding 配置 |
| GET | `/api/settings/system` | 系统信息 |

完整 API 文档启动后端后访问 http://localhost:8000/docs。

## 环境变量

详见 `.env.example`，主要配置项：

| 变量 | 说明 | 示例 |
|------|------|------|
| `FEISHU_APP_ID` | 飞书应用 App ID | `cli_xxxxxxxxxx` |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | `xxxxxxxxxxxxxxxxxx` |
| `DEFAULT_LLM_PROVIDER` | 默认 LLM 提供商 | `deepseek` |
| `DEFAULT_LLM_MODEL` | 默认模型名称 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | `sk-xxxxxxxx` |
| `OPENAI_API_KEY` | OpenAI API Key | `sk-xxxxxxxx` |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | `sk-xxxxxxxx` |
| `ZHIPU_API_KEY` | 智谱 API Key | `xxxxxxxx` |
| `DEFAULT_EMBEDDING` | Embedding 模型 | `BAAI/bge-small-zh-v1.5` |
| `CHUNK_SIZE` | 文本切片大小（字符） | `1000` |
| `RAG_TOP_K` | 检索返回条数 | `5` |

## 成本估算

**最低成本方案（推荐起步）：**

| 项目 | 费用 |
|------|------|
| 服务器 | 自有电脑 / 轻量云服务器 ≈ 0-50 元/月 |
| Embedding | BGE 本地模型 = 免费 |
| LLM | DeepSeek ≈ 10-30 元/月 |
| 向量数据库 | ChromaDB 本地 = 免费 |
| 飞书机器人 | 免费 |
| **月均总计** | **约 10-80 元** |

## 第二阶段：结构化学习工作流

上传请求只保存文件和数据库记录，然后把解析任务提交给 Celery；请求不会同步执行文档解析、向量化或 LLM 调用。解析成功后，工作进程会自动排队生成文档摘要、章节摘要、核心概念、重要术语、易错点、前置知识、推荐学习顺序、复习点和知识点。

运行该流程需要 Redis、Celery worker 和 ChromaDB。开发环境 worker 命令为：

```bash
celery -A app.collector.tasks worker --loglevel=debug --concurrency=2 --pool=solo
```

文档解析状态 `status`：

| 状态 | 含义 |
|---|---|
| `pending` | 已创建记录，等待提交处理 |
| `processing` | 正在解析、切片和建立索引 |
| `ready` | 解析及索引已完成，可预览和生成学习内容 |
| `failed` | 解析或任务派发失败，可在文档详情页查看原因并重新解析 |

学习内容状态 `learning_status`：

| 状态 | 含义 |
|---|---|
| `not_started` | 尚未生成 |
| `queued` | 已提交到 Celery |
| `generating` | 正在调用 LLM 并校验结构化结果 |
| `ready` | 摘要与知识点已生成 |
| `failed` | 生成失败，可查看原因并重新生成 |

知识库详情页展示学习目标、进度、文档、章节、核心知识点、最近学习记录和继续学习建议。文档详情路由为 `/knowledge/{workspaceId}/documents/{documentId}`；回答来源含稳定 `chunk_id` 时会附带 `?chunk=...&page=...` 并定位到对应页或切片，历史来源缺少 `chunk_id` 时仍在证据抽屉中显示。

文档名称和标签、AI 生成的知识点均可编辑；知识点还支持删除、合并、标记重点/已掌握以及生成卡片或练习。解析失败使用“重新解析”，学习内容失败使用“重新生成学习内容”。系统不提供 OCR，扫描版 PDF 需要先在外部完成文字识别。
