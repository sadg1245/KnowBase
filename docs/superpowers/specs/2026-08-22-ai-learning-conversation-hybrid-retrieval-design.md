# AI 学习会话与混合检索升级设计

## 1. 背景

当前 AI 学习页已经具备知识库与文件选择、六种学习模式、向量检索、流式回答、来源抽屉和保存卡片，但仍是单轮 RAG 原型：前端不保存 `conversation_id`，没有会话列表和管理接口；严格资料模式仅依赖提示词；检索只有 ChromaDB 向量召回；移动端固定宽度的学习模式栏会严重挤压消息区。

本设计把 AI 学习升级为可持久化、可继续、可评测的个人学习会话系统，同时保留本地优先、Docker 部署和当前知识库数据。

## 2. 目标

1. 提供完整会话生命周期：新建、自动标题、重命名、收藏、筛选、继续和删除。
2. 六种学习模式产生稳定且可辨识的教学行为。
3. 回答明确区分私人资料、AI 补充和未被资料证实的推断。
4. 严格资料模式在证据不足时由后端硬性拒答，而不是依赖模型自律。
5. 使用 SQLite FTS5 与 ChromaDB 实现关键词和向量混合召回、确定性重排和可配置证据阈值。
6. 保存检索候选、排名、分数和引用关系，支持后续质量评测。
7. 从回答直接生成卡片、笔记和错题，并提交有用/无用反馈。
8. 采用用户确认的“专注三栏”桌面布局，并在移动端退化为单列消息布局。

## 3. 非目标

- 不引入 Elasticsearch、OpenSearch、Qdrant 或新的常驻服务。
- 第一版不下载大型 cross-encoder 重排模型；使用确定性的融合重排。
- 不增加互联网搜索；“AI 补充”只来自当前配置模型的通用知识。
- 不在本阶段实现扫描 PDF OCR。
- 不重做练习、复习中心和知识库管理页面，只保证它们与新会话动作兼容。
- 不实现多人协作、云端同步和跨设备账号体系。

## 4. 总体架构

继续采用 FastAPI + SQLAlchemy + SQLite + ChromaDB + React + Ant Design 的模块化单体架构。

后端拆出三个职责明确的服务：

- `ConversationService`：会话 CRUD、消息历史、自动标题、收藏、笔记和反馈。
- `HybridRetrievalService`：关键词召回、向量召回、融合、重排、证据判定和检索记录。
- `LearningAnswerService`：六种模式提示、严格资料策略、引用校验、推荐追问和 SSE 事件。

原 `/api/chat` 保留为流式回答入口。请求没有 `session_id` 时自动新建会话，以兼容旧前端和其他调用方；新页面始终显式传入当前 `session_id`。

## 5. 数据模型

### 5.1 ChatSession

表名 `chat_sessions`：

- `id`: UUID 主键。
- `user_id`: 当前仍使用 `default`，为未来用户体系保留。
- `workspace_id`: 可空外键；删除知识库时置空，不删除历史会话。
- `title`: 会话标题；初始为“新学习会话”。
- `selected_document_ids`: JSON 数组，保存当前资料范围。
- `preferred_mode`: `direct|simple|deep|socratic|feynman|quiz`。
- `strict_sources`: 布尔值。
- `is_favorite`: 布尔值。
- `summary`: 可空文本。
- `created_at`、`updated_at`、`last_message_at`: 带时区时间。

按 `user_id`、`workspace_id`、`is_favorite` 和 `last_message_at` 建索引。

### 5.2 Conversation

保留现有 `conversations` 表和原字段，新增：

- `session_id`: `chat_sessions.id` 外键。
- `mode`: 生成该助手消息时使用的学习模式。
- `evidence_status`: `supported|limited|insufficient|error`。
- `retrieval_run_id`: 可空外键。
- `follow_up_questions`: JSON 数组，最多三个。
- `generation_status`: `complete|partial|failed`。

`sources` 继续保存最终引用快照，因此即使原文日后删除，历史回答仍可说明当时使用了什么证据。

### 5.3 LearningNote

表名 `learning_notes`：

- `id`、`workspace_id`、`session_id`、`message_id`。
- `title`、`content`。
- `source_snapshot`: 保存引用快照。
- `created_at`、`updated_at`。

既支持保存单条回答，也支持保存整段会话总结。

### 5.4 ChatFeedback

表名 `chat_feedback`：

- `id`、`message_id`。
- `helpful`: 布尔值。
- `category`: `accurate|unclear|unsupported|citation|other`，可空。
- `note`: 用户备注，可空。
- `created_at`。

每条助手消息每个用户只保留一条当前反馈，重复提交执行更新。

### 5.5 DocumentChunk 与 FTS5

表名 `document_chunks`：

- `id`: 与 ChromaDB chunk ID 一致。
- `workspace_id`、`document_id`。
- `source_file`、`page_num`、`heading`、`chunk_index`。
- `content`: 原始片段文本。
- `tokenized_content`: 使用 jieba 搜索分词后的文本。
- `created_at`。

建立 FTS5 虚拟表 `document_chunks_fts`，索引 `tokenized_content`、`heading` 和 `source_file`。插入、更新、删除片段时同步维护 FTS 行。

### 5.6 RetrievalRun 与 RetrievalHit

`retrieval_runs` 保存：

- 会话、用户消息、查询、知识库和文件范围。
- 向量/关键词召回是否成功及降级原因。
- 使用的 top-k、阈值和融合配置快照。
- 最终 `evidence_status`、最高分和创建时间。

`retrieval_hits` 每个候选保存：

- `retrieval_run_id`、`chunk_id`、文档和来源快照。
- `vector_rank`、`keyword_rank`、`vector_score`、`keyword_score`。
- `fusion_score`、`rerank_score`、`final_rank`。
- `selected_as_evidence`、`cited_in_answer`。

## 6. API 设计

### 6.1 会话

- `GET /api/chat/sessions?workspace_id=&favorite=`：按最后活动时间倒序列出会话。
- `POST /api/chat/sessions`：创建会话，接收知识库、文件范围、模式和严格开关。
- `GET /api/chat/sessions/{session_id}`：返回会话及消息。
- `PATCH /api/chat/sessions/{session_id}`：重命名、收藏或修改学习范围和偏好。
- `DELETE /api/chat/sessions/{session_id}`：删除会话和消息；不删除由会话生成的卡片、笔记和错题。
- `POST /api/chat/sessions/{session_id}/summary-note`：生成或保存会话总结笔记。

### 6.2 消息动作

- `POST /api/chat/messages/{message_id}/card`：从回答创建复习卡片。
- `POST /api/chat/messages/{message_id}/note`：从回答创建笔记。
- `POST /api/chat/messages/{message_id}/mistake`：以最近一条用户问题为题干、助手回答为参考答案创建错题记录。
- `PUT /api/chat/messages/{message_id}/feedback`：创建或更新反馈。

错题动作使用现有 `QuizQuestion`，增加可空 `origin_message_id`，题型设为 `short`，避免建立重复错题系统。

### 6.3 流式聊天

`POST /api/chat` 请求新增必选优先、兼容可空的 `session_id`。后端返回以下 SSE 事件：

- `session`: 会话 ID 和自动标题变化。
- `evidence`: `supported|limited|insufficient`、检索是否降级及说明。
- `token`: 回答增量。
- `sources`: 经校验的引用。
- `suggestions`: 三个推荐追问。
- `done`: 消息 ID、会话 ID、置信度和完成状态。
- `error`: 可重试错误和已保存的部分消息 ID。

## 7. 文档索引与迁移

新上传文件继续执行现有解析、切分和向量入库，同时把相同 chunk upsert 到 `document_chunks` 和 FTS5。

应用升级后执行幂等回填：

1. 创建新表、索引和 FTS5 虚拟表。
2. 按现有 `user_id` 中的历史 conversation UUID 聚合旧消息，为每组创建一个“历史学习会话”，填入 `session_id`。
3. 从每个 ChromaDB workspace collection 分页读取现有 chunk，回填 `document_chunks` 和 FTS5。
4. 回填失败不阻止应用启动；该知识库暂时显示“关键词索引构建中”，并使用纯向量检索。
5. 文档删除时删除对应 ChromaDB chunk 和 FTS chunk；历史消息、来源快照和学习产物保留。

所有迁移必须可重复执行，不覆盖现有知识库、文件、卡片、题目或学习进度。

## 8. 混合检索与重排

### 8.1 候选召回

每次查询在同一知识库和相同 `document_ids` 过滤条件下并行执行：

- ChromaDB 向量召回前 20 个片段。
- SQLite FTS5/BM25 关键词召回前 20 个片段。

中文查询使用 jieba 搜索模式分词，MATCH 查询对引号和 FTS 操作符做转义。文件过滤为空表示该知识库全部已就绪文件。

### 8.2 融合和确定性重排

先使用加权 RRF 合并候选，`k=60`，向量权重 `0.65`，关键词权重 `0.35`。随后把各分数归一到 0～1，计算：

`rerank_score = 0.50 * rrf_norm + 0.30 * vector_norm + 0.15 * bm25_norm + 0.05 * structure_bonus`

`structure_bonus` 由标题命中、完整短语命中和相邻片段关系组成，上限为 1。最终选择前 8 个片段；构建提示词时按来源和页码合并重复相邻片段，最多保留 8 个引用编号。

### 8.3 证据等级

默认阈值写入配置并允许环境变量覆盖：

- `supported`: 最高 `rerank_score >= 0.58`，且第二名 `>= 0.45`，或存在完整短语强命中。
- `limited`: 最高分 `>= 0.42` 但不满足 supported。
- `insufficient`: 没有候选或最高分 `< 0.42`。

阈值和实际分数随 `RetrievalRun` 保存，后续可用真实反馈重新校准，而不改历史记录。

## 9. 证据控制与回答分层

### 9.1 严格资料模式

- 只有 `supported` 才调用模型生成答案。
- `limited` 和 `insufficient` 返回确定性的资料不足响应，不允许模型自由补充。
- 模型上下文只包含最终证据片段，不提供外部工具。
- 每个事实段落必须带至少一个 `[资料N]`；后端只接受存在于本次 sources 的编号。
- 无有效引用的段落标记为不受支持并从严格回答中移除；如果移除后没有实质内容，返回资料不足。

### 9.2 非严格模式

回答使用固定分层：

1. `来自私人资料`：只描述证据支持的内容并使用 `[资料N]`。
2. `AI 补充`：模型通用知识，明确声明不来自私人资料。
3. `尚未被资料证实`：必要推断及其不确定性；没有推断时不显示。

`insufficient` 时先说明私人资料没有答案，再生成独立的 AI 补充区；不得把 AI 补充伪装成引用内容。

### 9.3 六种学习模式

- `direct`: 先结论，再给最短证据链。
- `simple`: 使用简单语言、一个类比和一个例子。
- `deep`: 按概念、原理、推导、例子、误区组织。
- `socratic`: 每轮只提出一个关键问题并给必要提示，用户作答后再推进。
- `feynman`: 先要求用户复述；收到复述后输出“准确部分、理解漏洞、重新表述”。
- `quiz`: 围绕证据出一道题，不立即揭晓答案；用户回答后判定并提供资料解释，可加入错题本。

会话保存当前模式，使苏格拉底、费曼和测试模式能在后续轮次继续状态，而不是每次重新开始。

## 10. 前端设计

采用用户确认的“专注三栏”。

### 10.1 桌面端（视口宽度 >= 1280px）

- 左栏 230px：新建会话、搜索、知识库筛选、收藏和历史会话。
- 中栏 `minmax(0, 1fr)`：会话标题、消息、推荐追问、引用和固定输入框。
- 右栏 240px：六种学习模式、严格资料开关、知识库、文件范围、当前证据状态。

现有 `LearningChat.tsx` 仅负责页面编排，拆分为：

- `SessionSidebar`
- `ChatTranscript`
- `ChatComposer`
- `LearningModePanel`
- `EvidenceDrawer`
- `MessageActions`
- `FollowUpSuggestions`
- `MobileLearningControls`

状态和 SSE 生命周期分别由 `useChatSessions`、`useStreamingChat` 管理，避免继续扩张单个页面文件。

### 10.2 中等宽度（900～1279px）

- 会话列表进入抽屉。
- 中间消息区和右侧学习工具保持双栏。
- 顶部提供清晰的“会话”按钮，不依赖应用全局导航。

### 10.3 移动端（< 900px）

- 页面只保留单列消息区。
- 会话列表使用左侧抽屉。
- 学习模式和严格资料设置使用底部面板。
- 知识库、文件范围和当前模式显示为可横向滚动的范围栏。
- 输入框固定底部，并为消息列表预留安全区和软键盘空间。
- 回答操作和引用允许自动换行，不设置固定侧栏宽度。

### 10.4 消息内容

助手消息显示证据状态和三个回答层级。每条回答提供引用、卡片、笔记、错题、复制和反馈操作；回答后显示最多三个基于当前会话生成的追问。点击引用打开现有来源抽屉，显示文件、页码、章节、原始片段和检索分数。

## 11. 错误处理与降级

- FTS5 不可用：使用纯向量检索，SSE evidence 事件和页面显示“关键词检索暂不可用”。
- ChromaDB 不可用：使用关键词检索。
- 两者都不可用：不调用模型，返回可重试的检索失败。
- 重排计算失败：使用 RRF 排序结果。
- 模型流中断：保存已生成内容为 `partial`，页面提供“继续生成”和“重新回答”。
- 自动标题失败：使用第一条用户问题的前 24 个字符。
- 推荐追问失败：不影响主回答，隐藏追问区域。
- 会话或笔记删除：必须二次确认。
- 用户快速切换会话：中止旧会话请求，旧请求不得写入当前页面状态。
- 同一消息动作重复提交：卡片、笔记、错题和反馈接口使用幂等约束或更新语义。
- 通知按请求去重，禁止同一错误连续堆叠多个 toast。

## 12. 测试策略

### 12.1 后端单元测试

- FTS 查询转义和中文分词。
- document ID 过滤同时应用于关键词与向量召回。
- RRF、归一化和确定性重排公式。
- 三档证据阈值边界。
- 严格模式在 limited/insufficient 时不调用 LLM。
- 严格回答剔除无效引用和无引用段落。
- 会话自动标题回退、收藏、筛选、重命名和级联删除。
- 消息生成卡片、笔记、错题和反馈的幂等性。
- 旧 conversation 数据迁移和 Chroma chunk 回填可重复执行。

外部模型、ChromaDB 和 embedding 在单元测试中使用固定 fake，不依赖网络和真实额度。

### 12.2 后端集成测试

- 新建会话 -> 连续两轮提问 -> 重新读取历史。
- 指定知识库和文件的混合检索。
- ChromaDB 或 FTS 单边失败时降级。
- SSE 事件顺序和消息最终持久化。
- 删除原文后历史来源快照仍可读取。

### 12.3 前端测试

- 会话新建、切换、重命名、收藏、筛选和删除。
- 切换会话时取消旧流并隔离消息。
- 六种模式与严格开关写回会话。
- evidence 状态、回答分层、引用抽屉和推荐追问。
- 卡片、笔记、错题和反馈操作状态。
- 部分回答的继续生成与重新回答。

### 12.4 浏览器验收

使用 1440px、1024px 和 390px 三种视口执行：

1. 打开 AI 学习并选择知识库和特定文件。
2. 新建会话、提问、查看引用并继续第二轮。
3. 刷新页面后继续同一会话。
4. 重命名、收藏、筛选和删除会话。
5. 从回答保存卡片、笔记和错题，提交反馈。
6. 在六种模式中验证明显不同的结构或轮次行为。
7. 严格模式对不足证据执行确定性拒答。
8. 移动端会话抽屉、底部模式面板、横向范围栏和固定输入框均可操作且不遮挡内容。

控制台不得出现未解释错误；页面不得出现横向溢出、竖排正文、遮挡输入框或重复 toast。

## 13. 交付顺序

虽然最终一次验收全部目标，但实现按两批稳定交付：

1. 会话与学习闭环：迁移、会话 API、消息状态、专注三栏、移动端、卡片/笔记/错题/反馈。
2. 检索与证据质量：FTS chunk 索引、回填、混合召回、重排、阈值、分层回答和评测记录。

每批都必须通过自己的后端测试、前端构建和浏览器流程后再进入下一批，最后重新构建 Docker 容器并执行完整回归。

## 14. 最终验收标准

- 用户可以新建、继续、重命名、收藏、筛选和删除会话。
- 刷新或重新进入页面后，消息和学习范围保持一致。
- 六种模式具有设计中定义的不同交互行为。
- 每条私人资料结论具有可点击且真实存在的引用。
- 非严格模式明确区分私人资料、AI 补充和未证实推断。
- 严格模式在证据不足时不调用模型自由回答。
- 混合检索候选和最终引用可在数据库中追踪评测。
- 用户可以从回答生成卡片、笔记和错题并提交反馈。
- 1440px、1024px 和 390px 视口均无内容挤压、竖排或不可操作控件。
- 现有知识库、文档、卡片、题目和学习进度在迁移后保持可用。
