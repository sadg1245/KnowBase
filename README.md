# 拾光 KnowBase — 私人 AI 学习知识库

拾光会阅读你的私人资料，并陪你完成“理解、练习、复习、回顾”的学习闭环。它既可以在电脑和手机浏览器中使用，也可以通过飞书机器人随时提问和复习。

## 学习版新增能力

- 学习主页：今日任务、连续学习、本周时长和薄弱知识点。
- 知识库详情：学习目标、资料摘要、章节结构、核心知识点和掌握进度。
- 六种 AI 学习方式：直接回答、通俗讲解、深入学习、苏格拉底引导、费曼复述和随堂测试。
- 知识卡片与间隔复习：根据“忘记、模糊、记住、熟练”自动安排下次复习。
- AI 练习与错题本：从知识点生成题目，记录错误并更新掌握度。
- 学习报告：按日、自然周、自然月查看可追溯的学习趋势、目标进度与 AI 建议。
- PWA 移动体验：可添加到手机桌面，并缓存基础应用外壳。
- 私人账号保护：单账号部署，首次打开时创建账号；认证保护默认覆盖全部私人接口。

## AI 导师：资料优先与学习记忆

- 回答策略只有一种：先检索你的私人资料，命中就带 `[资料N]` 引用回答；没有命中就改用模型知识，
  并明确标注为「AI 补充（模型记忆）」，不会把模型记忆伪装成你的资料。
- 资料层与模型层分段显示：资料层保留可点击的引用，模型层标注"这部分不是你的资料"。
  向量检索和关键词检索同时不可用时按错误处理并可重试，不会退化成纯模型问答。
- 学习画像：掌握度、薄弱点、常见错误、学习目标和最近学习会参与讲解方式、举例和难度，
  但永远不作为事实证据，也不占用 `[资料N]` 引用编号。
- 长期记忆：会话小结、重复错题、学习偏好和报告洞察会沉淀为可查看、可编辑、可停用、可删除的记忆，
  存在独立的 `memory_<用户>` 向量集合里，不参与资料证据召回。
- 学习页「导师眼中的我」可以查看画像与记忆，并随时纠正或删除。

## 第一阶段：账号与知识库基础

### 单账号部署，多用户数据结构

应用只允许首次创建一个账号：打开 Web 页面时若尚未建号，会引导填写用户名、密码和称呼；
创建成功后设置入口关闭，之后只能登录与退出。数据库、认证依赖和唯一约束都按多用户结构实现，
所有私人查询都附带服务端所有权条件，客户端提交的 `user_id` 不再进入请求契约。

令牌签名密钥（`JWT_SECRET`）**由程序自管**：留空即可，首次启动会自动生成并保存在
`<应用主目录>/secrets/`（权限 0600），之后一直复用。用户不需要知道也不需要填写它；
只有需要接管已有部署时才显式配置一个 ≥32 位的随机值。

需要在公网暴露时才配置：

```env
# 飞书机器人使用；服务令牌会绑定到唯一账号，未绑定账号时私人请求返回 503
SERVICE_TOKEN=飞书机器人专用随机令牌
BACKEND_ACCESS_TOKEN=与 SERVICE_TOKEN 保持一致
CORS_ORIGINS=https://你的访问域名
```

### 应用主目录（本地优先，用户零配置）

数据库、上传原文、头像封面、向量库、密钥、备份与用户偏好统一放在**应用主目录**下，
用户只需要配置自己的模型 API Key：

| 内容 | 位置 |
|---|---|
| 数据库 | `<主目录>/sqlite/knowbase.db` |
| 上传原文 | `<主目录>/uploads` |
| 头像与封面 | `<主目录>/media` |
| 向量库（嵌入模式） | `<主目录>/chroma` |
| 令牌密钥 | `<主目录>/secrets/jwt_secret` |
| 升级前自动备份 | `<主目录>/backups`（默认保留最近 5 份） |
| 用户偏好与 API Key | `<主目录>/settings.json`（权限 0600，只存本机） |

主目录默认按平台选择：Windows `%APPDATA%\KnowBase`、macOS `~/Library/Application Support/KnowBase`、
Linux `$XDG_DATA_HOME/knowbase`；也可以用环境变量 `KNOWBASE_HOME` 固定位置。
容器部署通过 `DATA_ROOT` / `DATABASE_URL` / `UPLOAD_DIR` / `MEDIA_DIR` 显式覆盖，卷布局不受影响。

同一套机制带来三个"用户不需要操心"的行为：

- **升级前自动备份**：迁移是就地改结构，执行前会自动把 SQLite 整体备份到 `<主目录>/backups`。
- **模型配置落盘**：`/api/settings/llm` 的修改会写入 `settings.json`，重启后仍然生效（过去只存在内存里）。
- **向量库默认嵌入**：不设置 `CHROMA_HOST` 时，ChromaDB 直接跑在应用进程内，
  不需要额外部署向量数据库；`CHROMA_HOST=chromadb` 这类自托管配置仍然生效。
- **首次使用向导**：建号后引导填写自己的模型 API Key（可跳过），之后的错误提示都改成用户能看懂的话；
  本地服务还没起来时，页面显示"暂时连接不上本地服务"并提供重试，而不是抛内部错误。

关于优先级：**本机保存的偏好优先于环境变量**。也就是说，用户在界面里改过模型或 Key 之后，
以 `settings.json` 为准；想让环境变量说了算，就不要在界面里修改这一项。

### 数据库迁移（Alembic）

结构由 `alembic upgrade head` 管理，应用启动不再执行 `create_all` 或兼容迁移 DDL。
Docker 与本地开发的启动命令都会先执行升级，迁移失败时 API 不启动。

```bash
# 在 backend 目录手动升级
python -m app.cli migrate
```

升级已有数据库前，请先备份 SQLite 数据库文件和上传目录。引导流程会检查核心表、关键列与索引，
只有检查通过才登记基线；结构不符时给出可操作错误而不是盲目 stamp。

账号迁移优先复用第一条 `user_profiles.id`，昵称与密码哈希进入 `users`，学习偏好进入
`learning_preferences`。由于旧资料没有用户名，**升级后的账号用户名是 `owner`，密码沿用原来的解锁密码**。
旧库没有个人资料时会创建一个待首次设置的占位所有者。

### 学习领域、封面与标签

- 知识库支持学习领域、学习状态（未开始/学习中/已暂停/已完成）、学习目标与封面（本地上传或 https 外链）。
- 列表与详情返回真实聚合的文档数、知识点数、平均掌握进度和最近学习时间；删除领域只把知识库置为“未分类”。
- 头像与封面保存在受控目录（`MEDIA_DIR`，默认 `./data/media`），只接受受控图片类型、检查文件头与像素范围，文件名随机。
- 文档与知识点共用同一套标签规范化（去空白、去空值、去重、长度与数量上限），人工编辑过的知识点标签在重新生成学习内容时保留，除非显式请求覆盖。

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
# 编辑 .env：只需要填写你自己的模型 API Key（也可以在首次打开页面时按向导填写）
# JWT_SECRET 留空即可，程序会自动生成并保存在数据目录里
# 想用飞书机器人时，再把 SERVICE_TOKEN 与 BACKEND_ACCESS_TOKEN 设为同一个随机值

# 3. 一键启动所有服务
docker compose up -d

# 首次启动会先执行数据库迁移，迁移失败则 API 不会启动（用 docker compose logs backend 查看原因）

# 4. 访问服务
# Web 管理界面:  http://localhost:3000
# 首次打开页面会引导创建唯一一个账号，之后只能登录与退出
# API 文档:      http://localhost:9000/docs
# 飞书机器人:    在飞书中搜索你的机器人名称开始对话
```

**Docker 服务说明：**

| 服务 | 宿主机端口 | 说明 |
|------|------|------|
| frontend | 3000 | Web 管理界面（nginx，`/api` 反代到 backend） |
| backend | 9000 | FastAPI 后端 API（容器内 8000） |
| chromadb | 127.0.0.1:9001 | ChromaDB 向量数据库（容器内 8000，仅本机可访问） |
| redis | 127.0.0.1:6379 | Redis 缓存/队列（仅本机可访问） |
| feishu-bot | — | 飞书机器人（无端口，WebSocket 出站连接） |
| worker | — | Celery 异步任务 Worker |

开发模式（`docker compose -f docker-compose.yml -f docker-compose.dev.yml up`）下 backend 与 frontend 直接暴露
宿主机 8000 / 5173，方便热重载调试。

**启动顺序与数据卷：** backend 容器启动时先执行 `python -m app.cli migrate`（Alembic 升级 + 旧库受控引导），
成功后才拉起 API；worker 依赖 backend 健康检查通过后再启动，避免在迁移完成前写入数据库。
数据库、上传原文与受控媒体（头像/封面）都落在 `backend_data` 卷里：

| 数据 | 容器内路径 | 卷 |
|---|---|---|
| SQLite 数据库 | `/app/data/sqlite/knowbase.db` | `backend_data` |
| 头像与知识库封面 | `/app/data/media` | `backend_data` |
| 上传原文 | `/app/uploads` | `backend_uploads` |
| 向量集合 | `/chroma/chroma` | `chroma_data` |

升级前整卷备份 `backend_data`、`backend_uploads` 与 `chroma_data` 即可。
`DATABASE_URL`、`UPLOAD_DIR`、`MEDIA_DIR` 已在 compose 中按上述挂载点给出默认值，并在 `.env` 里可覆盖（例如换成 PostgreSQL）。

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
# 编辑 .env 填入配置。注意仓库根的 .env 默认是给 Docker 用的
# （UPLOAD_DIR=/app/uploads、MEDIA_DIR=/app/data/media、REDIS_URL=redis://redis:6379/0），
# 本机直接运行时改成相对路径与 localhost：
#   DATABASE_URL=sqlite+aiosqlite:///./data/sqlite/knowbase.db
#   UPLOAD_DIR=./data/uploads
#   MEDIA_DIR=./data/media
#   REDIS_URL=redis://localhost:6379/0
#   CHROMA_HOST=localhost

# 升级数据库结构（首次运行与每次拉取更新后都执行一次）
python -m app.cli migrate

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

## 第五阶段：练习、错题与薄弱知识

进入“练习与错题”（`/practice`），选择知识库、已解析资料、章节或知识点，再设置题量、难度（基础、适中、挑战）、题型、资料约束和可选限时。未选择具体文件时使用该知识库全部已解析文件；界面题量为 1–50 道整数，限时为 1–240 分钟。支持单项选择、多项选择、判断、填空、简答和解释概念六种题型。

生成测验和主观题评分需要先在“偏好设置”配置可用的 AI 模型及其连接信息。严格依据资料开启时，问题、答案和解析必须有选定资料的证据支撑；资料不足会提示实际可生成数量和缺失条件，不会用固定模板补题。未配置模型、服务不可用或生成结果校验失败时会提示错误，不会把不完整题目当作成功测验。可以调整资料范围或恢复模型服务后重新生成。

逐题答题在提交当前题后显示该题反馈；整卷答题在交卷前隐藏答案、解析与引用原文，有未答题时先确认。交卷后展示参考答案、解析、AI 评价、分数及资料引用；引用可定位到原文页码和切片。客观题自动评分，多选要求选项集合完整匹配；简答与概念解释由 AI 按评分标准评价。主观评分暂不可用时保留原答案，标记“评分暂未完成”，暂不计为答错；“重试评分”重新评价同一次作答，不新增答案或重复错误记录。

限时从服务端开始时间计算，刷新或恢复测验不会重置计时；整卷到时自动交卷，逐题模式显示剩余时间但不自动交整卷。浏览器会尽力保留未提交草稿，服务端保存已提交作答。“重新作答”创建新的轮次，上一轮记录仍保留。

答错会自动进入“错题笔记”（`/practice?wrong=1`），展示答案、原因、来源、错误次数及重做记录；旧版练习历史仍可通过页面内的兼容入口访问。打开一条错题的“重新练习”，按原题型独立重做。连续两次成功评分且答对的重做后标为“已经掌握”；再次答错会重置连续答对次数并回到未掌握，评分失败不算错误，也不推进掌握状态。重做仅针对该题，不会提前揭晓同一试卷其他题目的答案。

练习页的“薄弱知识行动单”由五项证据组成：正确率 35%、重复错误 25%、复习反馈 15%、答题用时 10%、学习间隔 15%。总分越高越需要巩固；页面同时显示评分、复习和用时证据数量。缺失证据按中性值处理，等待或失败的 AI 评分不降低正确率；“重新计算”仅刷新当前知识库、资料或知识点范围。

## 第六阶段：学习主页与学习报告

学习主页（`/`）根据真实学习记录生成当天任务，集中展示待复习卡片、待重做错题、推荐继续学习的知识库、最近活动、连续学习天数、本周学习时间和当前薄弱知识点。页面顶部的快速提问会把问题带入学习对话，不会把未发送的文字记作提问。

阅读资料和进行学习对话时，前端每 30 秒发送一次心跳。服务端只累计相邻心跳之间不超过 90 秒的活跃时间；切换标签页、离开页面或结束会话会停止累计。刷新和重复结束请求不会重复生成学习记录。阅读文档、发起提问、完成会话、创建卡片、完成复习、参加测验、掌握知识点和修改目标均由对应业务流程自动记录，客户端不能直接伪造这些事件。

学习报告（`/report`）支持日、自然周和自然月视图。周期边界按用户在“偏好设置”中选择的 IANA 时区计算：周一为每周第一天，月报按自然月统计。学习时长、学习次数、新增知识点、完成复习、练习正确率、掌握度变化和薄弱知识变化均可打开证据抽屉追溯到原始记录。旧版 `/api/learning/report?days=...` 仍保留兼容。

AI 学习建议只在用户点击生成时调用模型。成功结果按报告统计快照缓存；模型未配置、不可用或响应无效时，报告数据仍正常展示，并明确提示可稍后重试，不会生成伪建议。

目标编辑支持每日学习分钟数、每日复习卡片数、每周学习天数、目标完成日期，以及每个知识库的目标掌握度和日期。旧版个人资料中的每日目标字段会与新版全局目标保持同步。学习数据导出接口 `/api/learning/export` 使用格式版本 2，包含目标、活跃学习会话、报告建议及完整活动证据，同时继续保留旧字段。

主要接口：

- `GET /api/learning/dashboard`：今日学习主页聚合数据。
- `GET /api/learning/activities`：按类型、知识库、来源和时间范围分页查询活动。
- `POST /api/learning/study-sessions/{start|:id/heartbeat|:id/finish}`：活跃学习计时。
- `GET /api/learning/reports/{day|week|month}`：自然周期报告。
- `GET /api/learning/reports/{day|week|month}/evidence`：指标证据。
- `POST /api/learning/reports/{day|week|month}/suggestion`：显式生成 AI 建议。
- `GET|PUT|DELETE /api/learning/goals...`：全局与知识库目标管理。

开发验证：

```bash
# 后端
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests -q

# 前端
cd frontend; npm test
npm run build
```

AI 导师相关的接口：`GET /api/learning/learner-profile` 返回画像快照，
`GET|POST /api/learning/memories` 与 `PATCH|DELETE /api/learning/memories/{id}` 管理长期记忆；
`/api/chat` 的 SSE `evidence` 事件会带上 `answer_policy`、`model_fallback`、`profile_injected`
和 `memory_hits`，`done` 事件带 `answer_layers`。

需要巩固的知识点提供重新阅读、通俗讲解、生成新例子、针对性练习、加入近期复习五个行动。讲解和例子链接会选择对应资料并预填输入框，必须由你点击发送才调用 AI。针对性练习会预选知识点；近期复习链接进入复习中心，薄弱度计算已按规则保存的复习任务会在今天页面和复习中心显示，可打开或标记完成。系统避免同一知识点同类型的待完成任务重复创建；薄弱知识还影响后续出题优先级和到期卡片顺序，原有翻卡、四档评分及卡片管理继续可用。

升级现有 SQLite 安装时，启动流程改用 Alembic：先校验旧结构、登记基线 revision，再执行后续迁移，
保留旧题号、答案、历史计数、原始文件路径与知识库 ID。部署前请备份数据库和上传目录。
运行时兼容入口 `run_compat_migrations` 已退役，只保留 SQLite FTS5 检索索引的幂等准备。
现有 PostgreSQL 安装同样走同一条迁移链，但不在本次 SQLite 验收范围内，需要另行执行并验证。

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
| GET | `/api/auth/status` | 是否已建号、是否需要首次设置 |
| POST | `/api/auth/setup` | 首次建号（仅无账号时可用） |
| POST | `/api/auth/login` / `/api/auth/logout` | 登录与退出 |
| GET/PATCH | `/api/me` | 当前用户资料（昵称、头像） |
| POST/DELETE | `/api/me/avatar` | 上传或清除头像 |
| GET/PUT | `/api/me/preferences` | 读取或更新学习偏好 |
| GET/POST/PATCH/DELETE | `/api/learning-domains` | 学习领域管理 |
| POST/DELETE | `/api/workspaces/{id}/cover` | 上传或清除知识库封面 |
| GET | `/api/media/{folder}/{filename}` | 受控媒体读取（随机文件名） |

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
| `JWT_SECRET` | 令牌密钥；留空自动生成并存到应用主目录 | 留空即可 |
| `KNOWBASE_HOME` / `DATA_ROOT` | 应用主目录（数据库、媒体、密钥、备份、偏好） | `%APPDATA%\KnowBase` |
| `SERVICE_TOKEN` | 飞书机器人服务令牌，绑定唯一账号 | 随机字符串 |
| `MEDIA_DIR` | 头像与封面受控目录 | `./data/media` |
| `IMAGE_MAX_SIZE_MB` | 图片上传大小上限 | `4` |
| `IMAGE_MAX_PIXELS` | 图片像素总量上限 | `20000000` |
| `TAG_MAX_LENGTH` / `TAG_MAX_COUNT` | 单个标签长度与标签数量上限 | `32` / `30` |

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
