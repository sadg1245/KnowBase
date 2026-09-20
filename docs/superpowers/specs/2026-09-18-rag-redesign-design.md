# RAG 重构设计：多格式、多类型知识库

> 版本：v1.0
> 日期：2026-09-18
> 依据文档：《个人自托管 AI 学习助手：多格式、多类型知识库 RAG 技术设计文档》v1.0
> 适用范围：KnowBase 后端采集层（`backend/app/collector`）、检索层（`backend/app/services/hybrid_retrieval.py`）、编排层（`backend/app/api/routes/search.py`）、数据模型（`backend/app/models`）

---

## 1. 背景

### 1.1 现状

KnowBase 当前已经具备一条可用的 RAG 链路，且检索侧质量高于典型原型：

- **入库**：`DocumentPipeline.process_document()` 用解析器工厂把文件转成 `{content, metadata}` 片段，再交给 `TextSplitter` 按 1000/200 字符递归切分，向量写入 ChromaDB，同时镜像到 `document_chunks` 与 FTS5 虚拟表 `document_chunks_fts`。
- **检索**：`HybridRetrievalService` 并行执行 Chroma 向量召回与 SQLite FTS5/BM25 召回，用加权 RRF（`k=60`，向量 0.65 / 关键词 0.35）融合，再用确定性公式 `0.50·rrf + 0.30·vector + 0.15·bm25 + 0.05·structure` 重排，按三档阈值判定证据等级，并把候选、排名、分数与引用关系持久化到 `retrieval_runs` / `retrieval_hits`。
- **个性化**：`LearnerProfileService` 输出掌握度、薄弱点与目标，`LearningMemoryService` 维护长期记忆，两者注入提示词，但不参与检索。
- **工程约束**：单账号、本地优先零配置、SQLite 权威数据源、内嵌 Chroma（Docker 下为 `chromadb` 容器）、48 个后端测试文件。

### 1.2 与目标架构的差距

| 设计文档要求 | 现状 | 差距性质 |
|---|---|---|
| 统一 `Document` / `Block` 模型 | 解析器直接产出 `{content, metadata}` | 缺抽象层 |
| `DocumentClassifier` 文档类型识别 | 不存在，`documents` 表无 `document_type` | 缺失 |
| `StructureAnalyzer` 结构树 | 只有解析器顺带产出的 `section_path` | 缺失 |
| `KnowledgeUnit` 知识单元 | 不存在。`knowledge_points` 表只服务学习页展示，不参与检索 | 缺失 |
| 结构优先 / 语义次之 / 字符兜底的切分 | 只有递归字符切分 | 策略层缺失 |
| Parent-Child 两级块 | 不存在，父级内容从不进入上下文 | 缺失 |
| Chunk 大小校验（min/target/max） | 只有 `CHUNK_SIZE=1000` 单一上限 | 缺失 |
| LLM 富化回填 chunk 元数据 | 富化结果写入 `documents` 与 `knowledge_points`，不回填 chunk | 链路断裂 |
| 多向量（content/summary/keyword/question） | 单向量（仅 content） | 缺失；本设计用 FTS5/BM25 承担 keyword 一路，多向量保留 content/summary/question |
| 题目与答案分离索引 | 不存在，练习防泄题只靠提示词 | 缺失 |
| Query Analyzer / Rewrite / 意图路由 | 用户问题直接进 embedding | 缺失 |
| 元数据预过滤（subject / difficulty / content_type） | 无 | 缺失 |
| Reranker | 无模型，只用确定性公式 | 缺失 |
| Parent Expansion / Context Builder | 检索结果直接拼接成上下文 | 缺失 |
| 画像参与检索（难度适配） | 画像只进提示词 | 部分缺失 |
| 分阶段入库状态与耗时观测 | `pending/processing/ready/failed` 四态 | 粗粒度 |
| 检索调试接口 | 无（只能读审计表） | 缺失 |

### 1.3 已发现的具体缺陷

这些缺陷与本次重构直接相关，随本次重构一并修复：

1. **距离度量不一致**：`VectorStore.get_or_create_collection()` 未设置 `hnsw:space`，ChromaDB 默认使用 L2 距离；而 `search.py::_vector_recall()` 按 `score = 1 - distance` 换算余弦相似度。同一项目里 `documents.py` 的遗留内联路径又显式设置了 `cosine`。
2. **查询向量与入库向量走两条路径**：入库用 `EmbeddingService`，查询用 `search.py::_get_embedding_function()` 直接构造 `SentenceTransformer`，模型与参数可能漂移。
3. **上传白名单与解析器工厂不一致**：`ALLOWED_EXTENSIONS` 接受 `.rst/.json/.xml/.yaml/.yml`，但 `_FILE_TYPE_MAP` 没有对应解析器，文件会先入库再在解析阶段失败。
4. **README 宣称支持 `.doc`，实际没有 DOC 解析器**，也不在上传白名单内。
5. **遗留死代码**：`documents.py::_process_document()` 与 `_chunk_text()` 不被上传路径调用，只被测试 patch，且是一套与 `TextSplitter` 重复的切分实现。

### 1.4 目标

> 不按文件格式设计 RAG，而按内容语义结构设计 RAG。

把入库从「解析 → 定长切分 → 向量化」升级为「解析 → 分类 → 结构分析 → 知识单元 → 策略切分 → 富化 → 多路索引」，把检索从「向量 + 关键词」升级为「查询理解 → 意图路由 → 元数据过滤 → 混合召回 → 重排 → 父级扩展 → 上下文构建 → 画像注入」，使系统回答的不再是「哪些文档包含这些词」，而是「根据用户当前学习目标、知识水平与问题意图，哪些知识单元最该出现在这次的上下文里」。

---

## 2. 本次技术栈决策

### 2.1 决策内容

**架构层全量对齐设计文档；索引层保留现有向量库；模型层更换嵌入模型并新增重排。**

### 2.2 与源设计文档的差异对照

| 文档推荐 | 本设计 | 理由 |
|---|---|---|
| Qdrant | **保留 ChromaDB** | 个人知识库规模（万级 chunk）下 Chroma 的 HNSW + metadata 过滤足够；换库要重建全部索引且增加一个常驻服务，收益最低、成本最高。文档自身也写「开发期 ChromaDB，正式项目更推荐 Qdrant」，即把 Qdrant 当作规模触发项而非架构前提。 |
| `BAAI/bge-m3` | **采纳（dense 单通道）** | 关键是上下文窗口 8192 与 1024 维，而非它的多向量能力。 |
| bge-m3 的 sparse / ColBERT 多向量 | **不启用** | 稀疏召回由现有 FTS5/BM25 + jieba 承担，语义与工程成本可控；多向量只保留 content/summary/question 三种。因此无需引入 `FlagEmbedding`。 |
| `BAAI/bge-reranker-v2-m3` | **采纳，做成三态可插拔** | `local`（本地 CrossEncoder）/ `api`（OpenAI 兼容 rerank 接口）/ `none`（退回现有确定性重排）。 |
| BM25 / OpenSearch / SQLite FTS | **保留 SQLite FTS5** | 已在用，且与 SQL 权威数据源同库，无需额外服务。 |
| LangGraph | **不引入，用 Celery + 显式阶段编排替代** | 两条工作流都是线性 DAG；用 Celery 链与阶段表即可获得同等可观测性与重试能力，节点命名与文档保持一致，未来若真要迁移 LangGraph 是机械替换。 |
| PostgreSQL / MySQL | **保留 SQLite** | 单账号本地优先；Alembic 迁移与 FTS5 触发器已按此建立。 |
| OCR / Vision Parser | **第一版不做，仅保留降级钩子** | 扫描件与公式识别是独立且昂贵的能力；本次先做到「识别出是扫描件并明确标注」，不静默产出空内容。 |
| 目录结构 `ai_learning_assistant/app/**` | **新增 `backend/app/rag/**`，与现有模块共存** | 一次性搬迁会打断 48 个测试的既有导入路径（如 `app.collector.pipeline.DocumentPipeline`）；采用新包 + 旧路径兼容门面。 |
| API `/api/v1/**` | **沿用现有 `/api/**`，新增 3 个端点** | 前端已依赖现有路径与 SSE 契约；文档的 API 语义全部映射到现有路由。 |

### 2.3 兼容性硬约束

以下契约在本次重构中**不得改变**：

1. `POST /api/chat` 的 SSE 事件序列：`session` → `evidence` → `token`* → `sources` → `suggestions` → `done`，以及 `error` 的 `{error, retryable, message_id}` 结构。
2. 来源条目字段：`content / source_file / page_num / score / document_id / heading / chunk_id`。
3. 回答中的 `[资料N]` 引用编号体系，以及「资料层 / AI 补充层 / 未被资料证实层」的分层语义。
4. `documents.status` 的既有取值 `pending|processing|ready|failed`（新增阶段信息走新列，不改旧列语义）。
5. 记忆不参与资料证据召回，也不占用 `[资料N]` 编号。
6. 现有 48 个后端测试与前端测试必须继续通过。

---

## 3. 目标架构

### 3.1 入库流水线

```text
上传文件
  ↓
FileTypeDetector        扩展名 + 文件头双重校验
  ↓
ParserFactory           9 类解析器，统一输出 Document/Block
  ↓
Unified Document        Document + Block[]
  ↓
DocumentClassifier      规则优先 + LLM 兜底 → document_type
  ↓
StructureAnalyzer       章节树 / 题目树 → 结构节点与父子关系
  ↓
KnowledgeUnitExtractor  chapter/section/concept/definition/formula/example/code/question/solution
  ↓
ChunkRouter             按 document_type 选择策略
  ├── Structure-aware Chunking
  └── Semantic Chunking
  ↓
ChunkNormalizer+Validator  去重、归一化、大小校验、递归兜底
  ↓
Parent-Child 组装       parent = 小节 / 题干+解答，child = 语义单元
  ↓
LLM Enrichment          summary / keywords / knowledge_points / subject / difficulty / content_type / questions
  ↓
Embedding               content / summary / question 三种向量
  ↓
Indexing                SQL（权威）+ Chroma（向量）+ FTS5（BM25）
  ↓
READY
```

### 3.2 查询流水线

```text
用户问题
  ↓
QueryAnalyzer           intent / subject / knowledge_points / difficulty / content_type / learning_mode
  ↓
QueryRewrite            用最近会话主题补全指代与省略
  ↓
LearningProfile         掌握度、薄弱点 → 难度区间与偏好内容类型
  ↓
RetrievalRouter         意图 → 允许 / 排除的 content_type
  ↓
MetadataFilter          subject / document_type / content_type / difficulty / unit_type
  ↓
Hybrid Recall           Chroma 多向量（content/summary/question） + FTS5 BM25
  ↓
CandidateMerge          加权 RRF，按逻辑 chunk_id 归并
  ↓
Reranker                bge-reranker-v2-m3（local/api），失败退回确定性重排
  ↓
ParentExpansion         子块命中 → 取父块完整上下文
  ↓
ContextBuilder          去重、排序、Token 预算、来源编号、模式过滤
  ↓
LLM                     六种学习模式提示词 + 分层回答契约
  ↓
AI Tutor 回答（含 [资料N] 引用）
```

---

## 4. 代码结构

### 4.1 新增包

```text
backend/app/rag/
├── contracts.py          Document / Block / KnowledgeUnit / Chunk / QueryAnalysis 数据契约
├── parsers/
│   ├── factory.py        ParserFactory（类型映射 + 文件头校验）
│   ├── blocks.py         Block 构建工具（标题栈、表格、公式、代码块）
│   └── adapters.py       现有解析器的 Block 化适配（实现仍在 collector/parsers）
├── analyzers/
│   ├── document_classifier.py
│   ├── structure_analyzer.py
│   └── knowledge_extractor.py
├── chunking/
│   ├── base.py           ChunkStrategy 抽象
│   ├── router.py         ChunkRouter
│   ├── textbook.py exam.py paper.py markdown.py note.py
│   ├── semantic.py       SemanticChunker
│   ├── fallback.py       RecursiveCharacterSplitter
│   └── validator.py      ChunkNormalizer + 大小校验
├── enrichment/
│   └── metadata_enricher.py
├── query/
│   ├── analyzer.py rewriter.py router.py
├── retrieval/
│   ├── dense.py sparse.py hybrid.py reranker.py parent.py context.py
├── indexing/
│   ├── vector_index.py keyword_index.py index_versions.py
├── pipelines/
│   ├── ingest_pipeline.py
│   └── query_pipeline.py
└── settings.py           重构专用配置读取（复用 app.config.settings）
```

### 4.2 与现有模块的关系

| 现有位置 | 处理方式 |
|---|---|
| `app/collector/parsers/*.py` | 保留为解析实现，新增 `parse_document()` 返回 `Document`；旧 `parse()` 保留兼容 |
| `app/collector/pipeline.py` | 保留 `DocumentPipeline` 类名与方法签名，内部委托给 `rag.pipelines.ingest_pipeline` |
| `app/core/vector_store.py` | 保留为 Chroma 访问层，新增距离度量与索引指纹能力 |
| `app/core/text_splitter.py` | 保留为 `FallbackChunkStrategy` 的实现 |
| `app/services/hybrid_retrieval.py` | 保留 `HybridRetrievalService` 与公共函数签名，内部接入元数据过滤、多向量与重排 |
| `app/api/routes/search.py` | 保留路由与 SSE 契约，检索调用改为 `rag.pipelines.query_pipeline` |
| `app/services/learning_content.py` | 保留（学习页产物），其富化结果同时回填 chunk 元数据 |
| `app/services/learner_profile.py` | 保留，新增检索期难度适配查询 |
| `app/api/routes/documents.py` | 删除死代码 `_process_document()` / `_chunk_text()`，上传白名单改由 `ParserFactory.supported_types()` 提供 |

---

## 5. 统一文档模型

### 5.1 Document

```python
class Document(BaseModel):
    document_id: str
    workspace_id: str
    filename: str
    file_type: str
    title: str | None = None
    document_type: str | None = None
    classification_confidence: float | None = None
    blocks: list[Block] = []
    metadata: dict[str, Any] = {}
```

与源文档相比增加 `workspace_id`（多知识库隔离是硬约束）与分类置信度（便于降级判断）。

### 5.2 Block

```python
class Block(BaseModel):
    block_id: str
    type: Literal[
        "heading", "paragraph", "list", "code", "formula",
        "table", "image", "question", "answer", "quote", "caption",
    ]
    content: str
    page: int | None = None
    heading_level: int | None = None
    order: int
    section_path: list[str] = []
    latex: str | None = None
    language: str | None = None
    table: list[list[str]] | None = None
    metadata: dict[str, Any] = {}
```

`order` 与 `section_path` 是相对源文档的补充：前者支撑语义切分的相邻关系与 Parent-Child 组装，后者是现有 `document_chunks.section_path` 的延续，保住已上线的章节导航功能。

### 5.3 公式表示

公式统一为：

```json
{ "type": "formula", "latex": "\\frac{\\partial z}{\\partial x}", "text": "z 对 x 的偏导数" }
```

`latex` 可空（无法可靠提取时退化为 `text`），但**公式块不得被切分**：`ChunkValidator` 把 formula 块视为不可分割原子，超出 `max_chunk_tokens` 时整块单独成 chunk 并标注 `oversized_ok=true`。

---

## 6. 解析层

### 6.1 ParserFactory

```python
class ParserFactory:
    _registry: dict[str, type[BaseParser]] = {}

    @classmethod
    def register(cls, file_type: str, parser_cls: type[BaseParser]) -> None: ...

    @classmethod
    def get_parser(cls, file_type: str) -> BaseParser: ...

    @classmethod
    def supported_types(cls) -> set[str]: ...
```

改造要点：

1. **注册表取代 if/elif 链**（现为 `DocumentPipeline._get_parser` 中的条件分支）。
2. `supported_types()` 作为上传白名单的**唯一来源**，从根上消除 §1.3 第 3 条的「白名单与工厂不一致」。
3. `register()` 通过模块导入副作用完成注册，新增解析器不改工厂代码。
4. 保留 `_PARSER_CACHE` 的解析器复用行为。

### 6.2 文件类型映射（对齐后）

| 扩展名 | 解析器 | 输出 |
|---|---|---|
| `.pdf` | `PDFParser` | 页级 Block，带 TOC 标题栈 |
| `.docx` | `DocxParser` | 标题分段 Block，含 table 块 |
| `.doc` | `DocParser` | 经 LibreOffice/antiword 转换后复用 DOCX 分支；转换器缺失时给出可操作错误 |
| `.md` / `.markdown` | `MarkdownParser` | 标题层级 Block，代码块独立成块 |
| `.txt` | `TextParser` | 段落 Block |
| `.pptx` | `PptxParser` | 幻灯片级 Block |
| `.html` / `.htm` | `HtmlParser` | 标题与段落 Block |
| `.xlsx` | `XlsxParser` | 每个工作表一个 table 块 + 行级 paragraph 块 |
| `.csv` | `CsvParser` | 表头 + 行 Block |

`.rst` 由 `MarkdownParser` 的宽松模式处理（复用标题正则），`.json/.xml/.yaml/.yml` 归入 `TextParser` 并标注 `content_type="code"`。**准入条件：不允许存在「上传成功但解析必然失败」的组合**，要么补齐解析器，要么从白名单移除。

### 6.3 PDF 策略

```text
PDF → 文本提取 → 版面/质量判定
        ├── 文本正常        → 普通 Parser（现有 PDFParser 增强）
        └── 扫描/公式/乱码  → 标记 scanned / formula_heavy，走降级路径
```

第一版具体做法：

- 每页统计「可提取字符数 / 页面面积」与「CJK 占比」，低于阈值标记 `scanned=true`。
- 整份文档全为扫描页时，额外记录 `parse_degraded="scanned_pdf"`，文档详情页明确提示「该文件为扫描件，当前未做 OCR，暂不参与检索」，而不是像现在这样产出空 chunk 后静默通过。
- 公式密集页（`$...$`、`\(...\)`、`\begin{...}` 出现频率）标记 `formula_heavy=true`，富化阶段对这些 chunk 关闭摘要压缩，避免公式语义被改写。
- Vision/OCR 解析器作为 `ParserFactory` 中的一个可选实现位保留，第一版不注册。

---

## 7. Document Classifier

### 7.1 支持类型

```text
textbook | exam | paper | notes | tutorial | documentation | slides | qa | code_document | unstructured
```

### 7.2 判定顺序

1. **规则优先**（零成本、可解释）：
   - 出现「第X章 / 第X节 / 习题」→ `textbook`
   - 出现「大题 / 小题 / 答案 / 解答 / 解析」→ `exam`
   - 出现 `Abstract / Method / Experiment / Conclusion` → `paper`
   - Markdown 标题密度高 → `notes` 或 `tutorial`（依是否含代码块）
   - PPTX → `slides`；XLSX/CSV → `documentation`
2. 规则命中且置信度 >= 0.8 → 直接采用，不调用 LLM。
3. 否则调用 LLM，强制 JSON：

```json
{
  "document_type": "textbook",
  "confidence": 0.92,
  "reasons": ["存在章节编号", "存在连续知识主题"]
}
```

4. **失败降级**：LLM 不可用或解析失败 → `unstructured`，`classification_confidence=0`，进入语义切分路径，不阻断入库。

### 7.3 落库

`documents.document_type`（新列）+ `documents.classification_meta`（JSON，存 reasons 与 confidence）。

---

## 8. Structure Analyzer

识别对象：标题层级、章节层级、列表、公式、代码、题目、答案、表格、图片。

输出为结构树，写入两张表：

- `structure_nodes`：`node_id / document_id / parent_node_id / node_type / title / level / order / block_start / block_end / page_start / page_end`
- `document_chunks.parent_id` 指向该树上的父节点所对应的 chunk。

两类结构模板：

```text
textbook / notes / tutorial
Document → Chapter → Section → (Concept | Formula | Example | Code | Table)

exam
Document → Question → (SubQuestion | Solution | Answer)
```

题目树是 §16「题目与答案分离」的结构前提：先有 Question/Solution 父子关系，才能在练习模式下只召回题干、在讲解模式下召回题解。

**降级**：结构识别失败（例如无明显标题）→ 不写 `structure_nodes`，文档整体走 `SemanticChunkStrategy`，`document_type` 保持分类结果不变。

---

## 9. KnowledgeUnit

真正服务于学习系统的核心抽象，字段对齐源文档第 11 节，并补充仓库所需的隔离列：

```python
class KnowledgeUnit(BaseModel):
    unit_id: str
    document_id: str
    workspace_id: str
    parent_id: str | None = None
    unit_type: str
    title: str | None = None
    content: str
    subject: str | None = None
    chapter: str | None = None
    section: str | None = None
    knowledge_points: list[str] = []
    difficulty: int | None = None
    source_chunk_ids: list[str] = []
    metadata: dict[str, Any] = {}
```

`unit_type` 取值：`chapter | section | concept | definition | formula | example | code | question | solution | answer | note | table | image`。

### 9.1 与既有 `knowledge_points` 的分工

两者**不合并**，因为它们是不同层次的对象，合并会同时污染检索与学习记录：

| | `knowledge_units`（新增） | `knowledge_points`（既有） |
|---|---|---|
| 层次 | 文档结构层，与原文片段一一对应 | 学习层，可跨文档聚合、可人工编辑 |
| 来源 | 结构与切分产物（确定性） | LLM 归纳 + 用户编辑 |
| 消费者 | 检索、上下文构建、题解关联 | 卡片、练习、掌握度、复习计划 |
| 生命周期 | 随文档重新索引重建 | 保留用户编辑，重索引不覆盖 |

关联方式：`knowledge_points.unit_id`（新增可空外键）。`replace_document_learning_content()` 生成知识点时，若其 `source_chunk_index` 能映射到某个 unit，则回填 `unit_id`，让「薄弱知识点 → 相关原文知识单元」可追溯。映射不上的知识点保持 `unit_id=NULL`，不影响现有功能。

### 9.2 提取规则

- 结构树节点 → `chapter` / `section` unit。
- 命中定义句式（「X 是指」「称为」「定义为」「is defined as」）→ `definition`。
- 含公式块的语义单元 → `formula`。
- 含例题标记（「例 X」「例题」「Example」）→ `example`。
- 题目树中的题干 → `question`，解答 → `solution`，答案 → `answer`。
- 代码块 + 其前后解释段落 → `code`。
- 兜底：语义切分产生的单元 → `concept`。

提取是**确定性规则 + 已有的关键词/摘要富化结果**，不再额外引入一次 LLM 调用（LLM 调用集中在 §13 富化阶段，避免入库成本翻倍）。

---

## 10. 切分层

### 10.1 策略接口

```python
class ChunkStrategy(ABC):
    @abstractmethod
    def chunk(self, document: Document, units: list[KnowledgeUnit]) -> list[Chunk]: ...
```

### 10.2 路由表

| document_type | 策略 | 切分依据 |
|---|---|---|
| `textbook` | `TextbookChunkStrategy` | Chapter → Section → KnowledgePoint |
| `exam` | `ExamChunkStrategy` | Question + SubQuestion + Solution |
| `paper` | `PaperChunkStrategy` | Abstract / Method / Experiment / Conclusion |
| `notes` | `NoteChunkStrategy` | Heading 层级 + 语义补充 |
| `tutorial` / `documentation` | `MarkdownChunkStrategy` | Heading 层级，代码块与说明配对 |
| `slides` | `SlideChunkStrategy` | Slide / Topic |
| `qa` | `QaChunkStrategy` | Q + A 成对 |
| `code_document` | `CodeChunkStrategy` | 函数/类边界 + 说明 |
| `unstructured` | `SemanticChunkStrategy` | 主题漂移检测 |
| 未知 / 策略异常 | `FallbackChunkStrategy` | 递归字符切分 |

```python
class ChunkRouter:
    def get_strategy(self, document_type: str) -> ChunkStrategy:
        return self._mapping.get(document_type, FallbackChunkStrategy())
```

未知类型必须返回兜底策略而非抛异常（对齐源文档第 44 节）。

### 10.3 Semantic Chunking

```text
句子切分 → 批量 Embedding → 相邻句余弦相似度 → 低于阈值处切分 → 单元成块
```

- 阈值 `SEMANTIC_SPLIT_THRESHOLD` 默认 0.62，按源文档第 17 节伪代码实现。
- 批量 embedding 复用入库阶段同一模型，**不额外加载模型**。
- 单段长度超过 `SEMANTIC_SPLIT_MAX_SENTENCES`（默认 400）时先按段落预切，避免二次方开销。
- 失败（embedding 不可用）→ 直接降级到 `FallbackChunkStrategy`。

### 10.4 大小校验与归一化

```text
min_chunk_tokens    = 150
target_chunk_tokens = 400 ~ 800（默认 600）
max_chunk_tokens    = 1200
```

处理顺序不可颠倒（对齐源文档第 18 节「不要反过来先固定长度切」）：

1. 先按结构/语义产出候选块。
2. 超过 `max` → 在**同一语义单元内**递归细分（使用 `FallbackChunkStrategy`）。
3. 小于 `min` → 与同父节点相邻块合并；跨父节点不合并，并记录原因。
4. 原子块（formula / code / table）不参与细分与合并，超限时整块保留并标记。
5. 归一化：统一换行、去除重复页眉页脚、去掉与相邻块完全重复的尾部重叠。

**Token 口径**：以 embedding 模型自带 tokenizer 为准；模型未加载时使用中英混合估算器（CJK 字符计 1 token，拉丁词计 1.3 token），估算器与真实 tokenizer 的偏差由单测约束在 ±10% 以内。这一点是本次换模型的直接动因：`bge-small-zh-v1.5` 上限 512 token，无法承载 400–800 的目标块大小。

---

## 11. Parent-Child 与 Parent Expansion

### 11.1 两级结构

- **Parent Chunk**：完整上下文（一个小节、一道题的题干+解答、一个概念的完整说明）。主要作为上下文来源。
- **Child Chunk**：语义单元（定义、公式说明、例题、解题步骤），进入向量与关键词索引。

### 11.2 存储

`document_chunks` 增加 `chunk_level`（`parent|child`）与 `parent_id`（逻辑 chunk id）：

- `parent_id IS NULL` 的行即 parent，本身也参与全文检索（用户可能直接命中小节标题）。
- 子块命中后按 `parent_id` 批量取父块全文。

### 11.3 Parent Expansion 规则

1. 命中子块 → 取其父块。
2. 父块 Token 数超过 `RAG_PARENT_MAX_TOKENS`（默认 2000）时，退回子块并附相邻子块各一条，避免单个来源挤占预算。
3. 同一父块下的多个子块同时命中 → 上下文中只保留父块一次，来源编号共用，`retrieval_hits` 仍逐条记录。

---

## 12. Chunk 数据模型

扩展既有 `document_chunks` 表（不新建并行 `chunks` 表，避免两套索引真相）：

| 新增列 | 类型 | 用途 |
|---|---|---|
| `unit_id` | String(36) NULL | 关联 `knowledge_units` |
| `parent_id` | String(255) NULL | 逻辑父 chunk |
| `chunk_level` | String(10) | `parent` / `child`，默认 `child` |
| `content_type` | String(32) | concept/definition/formula/example/code/question/solution/answer/note/table |
| `document_type` | String(32) | 冗余自 `documents.document_type`，供过滤与调试 |
| `subject` | String(128) NULL | 学科 |
| `summary` | Text NULL | 富化摘要 |
| `keywords` | JSON | 关键词数组 |
| `knowledge_points` | JSON | 知识点名称数组 |
| `difficulty` | Integer NULL | 1–5 |
| `page_end` | Integer NULL | 跨页块结束页 |
| `enrichment_status` | String(16) | `pending` / `ready` / `failed` / `skipped` |
| `index_version` | Integer | 索引结构版本，用于重建判定 |
| `metadata` | JSON | 其余扩展字段 |

既有列 `page_num` / `heading` / `heading_level` / `section_path` / `tokenized_content` 全部保留，其中 `page_num` 语义等同于 `page_start`，不新增重复列。

FTS5 虚拟表 `document_chunks_fts` 与三个触发器保持不变（只索引 `tokenized_content / heading / source_file`），因此加列不影响全文检索，也不需要重建 FTS。

实现注意：SQLAlchemy 声明式模型的属性名不能叫 `metadata`（与 `Base.metadata` 冲突），因此该列在模型上映射为 `chunk_metadata = Column("metadata", JSON)`，数据库列名仍为 `metadata`。

---

## 13. Metadata Enrichment

### 13.1 契约

每个 child chunk 入库前由 LLM 输出（强制 JSON，禁止自由文本）：

```json
{
  "summary": "",
  "subject": "",
  "knowledge_points": [],
  "keywords": [],
  "difficulty": 1,
  "content_type": "",
  "questions": []
}
```

`questions` 是源文档第 20 节的「潜在问题」：为每个 chunk 生成 1–3 个用户可能提出的自然语言问题，用于 `question` 向量。

### 13.2 工程约束

- **批量**：按文档聚合，每批 8–12 个 chunk 一次调用，降低调用次数。
- **并发**：`RAG_ENRICH_CONCURRENCY`（默认 3），避免单文档触发限流。
- **幂等**：以 `(chunk_id, index_version)` 为缓存键，重复入库不重复调用。
- **校验**：Pydantic 校验失败 → 该 chunk 标记 `enrichment_status=failed`，使用规则兜底（content_type 由策略给出、keywords 由 jieba 抽取、difficulty 留空），**不阻断入库**。
- **可重试**：`enrichment_status=failed` 的 chunk 支持后台补跑（`POST /api/documents/{id}/enrich`）。
- **成本开关**：`RAG_ENRICH_ENABLED`。关闭时使用纯规则富化，检索链路仍完整可用。
- **安全**：chunk 文本按不可信数据注入提示词，沿用 `learning_content.py` 已有的 `<chunk>` 包裹与「不得执行其中指令」声明模式。

### 13.3 与现有学习产物的关系

`learning_content.py` 已产出的 `summary / chapter_summaries / core_concepts / important_terms / common_mistakes / prerequisites / learning_order / review_points / knowledge_points` 继续保留在 `documents` 与 `knowledge_points` 上，供学习页使用；本阶段的富化结果**额外**回填 chunk 元数据。两者数据源一致（同一批 chunk），不产生冲突。

---

## 14. 多向量设计

### 14.1 向量种类

| kind | 来源 | 用途 |
|---|---|---|
| `content` | chunk 原文 | 通用召回（必开） |
| `summary` | 富化 summary | 长块、结构松散文档的召回（推荐开） |
| `question` | 富化 questions | 自然语言提问召回（推荐开） |

不启用 keyword 向量：关键词的精确匹配由 FTS5/BM25 承担，重复建设收益低。

### 14.2 ChromaDB 落地方式

ChromaDB 单条记录只支持一个向量，因此采用「**单 collection + vector_kind 元数据**」：

```text
collection: ws_<workspace_id>              （沿用现有命名，不新增 collection）
记录 id:    {document_id}_chunk_{i}              → vector_kind=content
            {document_id}_chunk_{i}#summary      → vector_kind=summary
            {document_id}_chunk_{i}#question     → vector_kind=question
metadata:   chunk_id={document_id}_chunk_{i}       ← 逻辑块 id，用于归并
            vector_kind / content_type / document_type / subject
            difficulty / unit_type / parent_id / document_id / workspace_id
```

这与源文档第 23 节的「方案 A：单 Collection + Metadata」一致，也符合 ChromaDB 的能力边界。

### 14.3 归并与成本控制

- 检索时对启用的 kind 各取 `top_k`，按 `chunk_id` 归并：同一逻辑块命中多个 kind 只保留最高名次，并在 `retrieval_hits` 中记录命中的 kind 列表。
- 存储成本约为单向量的 2–3 倍；通过「kind 白名单」控制：仅 `content_type in {concept, definition, formula, question, solution}` 的块生成 summary/question 向量，其余块只做 content 向量。
- `vector_kind` 也可作为过滤条件，支撑后续「只按问题召回」的实验开关。

---

## 15. 向量库与索引

### 15.1 距离度量统一

- collection 创建时显式设置 `hnsw:space="cosine"`；既有 collection 在启动自检中发现缺失该设置时，记入 `degraded_reasons` 并提示重建索引，不再出现「L2 距离被当成余弦」的情况。
- 向量召回统一按 `similarity = 1 - distance` 换算（归一化向量的余弦距离定义），与入库时的 `normalize_embeddings=True` 一致。
- 查询与入库共用同一个 `EmbeddingService` 单例，删除 `search.py::_get_embedding_function()` 的独立模型加载路径，从根上消除 §1.3 第 2 条。

### 15.2 索引指纹

collection metadata 写入指纹：

```json
{
  "embedding_model": "BAAI/bge-m3",
  "embedding_dimension": 1024,
  "chunk_schema_version": 2,
  "distance": "cosine"
}
```

指纹不一致时：

1. 该 workspace 标记 `index_stale=true`；
2. 检索仍可用，但 `evidence` 事件追加 `index_stale` 提示（不改变既有事件字段，只新增可选键）；
3. 后台按文档逐篇重建（§25）。

ChromaDB 不允许同一 collection 内混用不同维度，因此维度变化时**必须整 collection 重建**，不能部分追加。这是本次换 embedding 模型必须付出的成本。

### 15.3 索引写入

沿用 `VectorStore.replace_document()` 的「先删后写」语义，扩展到：

```text
删除条件：{"$or": [{"doc_id": doc}, {"document_id": doc}]}   ← 兼容历史 metadata
写入内容：按 kind 展开的多条记录，metadata 含 chunk_id 与 vector_kind
```

删除文档时三层索引同步：Chroma（按 `document_id` 的两种历史字段名）、`document_chunks`（含新列）、FTS5（触发器自动）。

---

## 16. 题目与答案分离

### 16.1 分离规则

- 题干 → `content_type="question"`。
- 解答 → `content_type="solution"`。
- 纯答案（无过程）→ `content_type="answer"`。
- 题干与解答的关系通过 `parent_id` 与 `unit_type=question` 的父子单元表达，保证可回溯。

### 16.2 检索期控制

`RetrievalRouter` 按意图决定允许的内容类型：

```python
ROUTES = {
    "practice":             {"allow": ["question"]},
    "solution_explanation": {"allow": ["solution", "example", "concept", "definition"]},
    "concept_explanation":  {"allow": ["concept", "definition", "example"]},
    "formula_lookup":       {"allow": ["formula", "definition"]},
    "review":               {"allow": ["question", "solution", "concept", "definition"]},
    "note_lookup":          {"allow": ["note", "concept"]},
    "default":              {"allow": None},
}
```

`allow=None` 表示不过滤；未列出的意图一律走 `default`。

Router 的输入是 Query Analyzer 的 `preferred_content` 与 `exclude_content`：先按 `intent` 取上表的路由集合，再用 `exclude_content` 做减法，最终得到 `allow` 集合。显式排除永远优先于意图路由。

### 16.3 防御性保证

过滤在**召回层**生效（Chroma 元数据过滤 + SQL WHERE），不是在拿到结果后丢弃。练习模式下 `solution` 与 `answer` 不会进入候选集，因此也就不会进入上下文。这一点由 §26.4 的单测强制。

练习模式的题目来源同时升级：`/api/assessments/quiz-sets/generate` 由「纯 LLM 出题」改为「先按知识点与难度检索 `content_type=question`，命中不足时再用 LLM 补足」，并在返回值中标注每题的来源是资料还是生成。

---

## 17. 查询理解

### 17.1 Query Analyzer

输入：用户问题 + 会话最近 N 轮 + 当前 workspace / 文件范围。

输出：

```json
{
  "intent": "practice",
  "subject": "高等数学",
  "knowledge_points": ["隐函数求导"],
  "difficulty": { "min": 3, "max": null },
  "preferred_content": ["question"],
  "exclude_content": ["solution"],
  "confidence": 0.81
}
```

实现策略 `RAG_QUERY_ANALYZER`：

- `rules`：关键词与句式规则（「给我一道…题」→ practice；「为什么」「怎么推导」「证明」→ solution_explanation）。
- `llm`：强制 JSON 输出。
- `hybrid`（默认）：规则高置信度即返回；否则调用 LLM。

**超时**：`RAG_QUERY_ANALYZE_TIMEOUT_SECONDS`（默认 8）。超时或失败 → `intent=default`、`allow=None`，按当前行为继续检索，绝不阻塞回答。

**缓存**：以 `(query_hash, workspace_id, mode)` 为键做进程内 LRU + 短 TTL。

### 17.2 Intent 类型

```text
concept_explanation | definition_lookup | practice | solution_explanation | example_search
| review | note_lookup | formula_lookup | comparison | learning_plan
```

### 17.3 Query Rewrite

仅在存在可指代成分时触发（「这里」「它」「为什么要求二阶偏导」等），用最近会话主题补全：

```text
原始：这里为什么要求二阶偏导？
上下文主题：多元函数极值
改写：多元函数极值判定中为什么需要利用二阶偏导数判断极值
```

约束：

- 改写结果只用于**检索**；送给 LLM 的仍是用户原问题，避免改写引入的语义漂移污染回答。
- 改写结果与原问题**同时**参与召回，两路结果一并融合，防止改写变差时反而降低召回。
- 无会话上下文时跳过改写，不做无依据扩写。

---

## 18. 混合检索与重排

### 18.1 保留部分

现有实现整体保留并扩展：并行召回（`asyncio.gather` + `return_exceptions=True`）、单边失败降级与 `degradation_reason` 记录、加权 RRF（`k=60`，向量 0.65 / 关键词 0.35）、确定性重排公式作为兜底排序器、`retrieval_runs` / `retrieval_hits` 审计。

### 18.2 新增：元数据预过滤

在召回**之前**构造过滤条件（向量侧走 Chroma `where`，关键词侧走 SQL WHERE）：

```text
workspace_id（必填）
document_ids（可选）
content_type IN (...) / NOT IN (...)     来自 RetrievalRouter
subject = ...                            来自 QueryAnalysis
difficulty BETWEEN ...                   来自 QueryAnalysis + LearnerProfile
document_type IN (...)                   来自用户显式筛选（可空）
vector_kind IN ('content','summary','question')
```

过滤条件必须**同时**应用到向量与关键词两路，否则会出现「关键词侧捞回了被排除的题解」这类污染。多值过滤在 Chroma 侧用 `$in`，在 SQL 侧用 `IN`，由同一个过滤对象生成，避免两处手写出现偏差。

### 18.3 新增：Reranker

```python
class RerankerService(Protocol):
    async def score(self, query: str, passages: list[str]) -> list[float]: ...
```

三种实现，由 `RAG_RERANK_PROVIDER` 选择：

| 值 | 实现 | 说明 |
|---|---|---|
| `local`（默认） | `sentence_transformers.CrossEncoder("BAAI/bge-reranker-v2-m3")` | 首次使用下载模型；Docker 镜像装的是 CPU 版 torch，20–30 个候选在 CPU 上需数秒 |
| `api` | OpenAI 兼容 `/rerank` 接口（如 DashScope `gte-rerank`） | 无需本地模型，需配置 Key 与 base_url |
| `none` | 直通 | 退回确定性重排 |

流程：`Dense Top 20 + BM25 Top 20 → 按 chunk_id 归并（约 20–30 候选）→ Reranker → Top 8`。

融合公式扩展为：

```text
final = 0.55·rerank_norm + 0.25·rrf_norm + 0.15·vector_norm + 0.05·structure_bonus
```

`RAG_RERANK_PROVIDER=none` 时退回现有 `0.50 / 0.30 / 0.15 / 0.05` 权重，保证关闭重排时行为与今天一致。重排器**并行打分**，并在 `RAG_RERANK_TIMEOUT_SECONDS`（默认 20）超时后放弃，记录 `degradation_reason="rerank_timeout"`，用确定性排序继续回答——重排超时不是错误。

### 18.4 证据阈值重标定

新增 reranker 分数会改变分数分布，因此 `RAG_SUPPORTED_THRESHOLD`、`RAG_SECOND_THRESHOLD`、`RAG_LIMITED_THRESHOLD` 必须重标定，不能沿用 0.58 / 0.45 / 0.42：

1. 用现有真实问题构造标注集（问题 → 期望命中的 chunk）。
2. 分别统计三档在 `rerank_provider=local|none` 下的分数分布。
3. 按「优先压低假阳性」的目标选阈值，写入配置默认值。
4. 每次切换 provider 或模型版本都要重新标定；当时使用的阈值随 `retrieval_runs.config_snapshot` 落库（字段已存在，天然支持回溯）。

### 18.5 延迟预算

| 阶段 | 目标 |
|---|---|
| 查询分析（规则命中） | < 50 ms |
| 查询分析（LLM） | < 3 s，超时 8 s 兜底 |
| 向量召回 + BM25 | < 500 ms |
| 重排（local，30 候选，CPU） | < 8 s，超时 20 s 后降级 |
| 重排（api） | < 2 s |
| 父级扩展 + 上下文构建 | < 100 ms |

---

## 19. Context Builder

职责：去重、排序、Parent 扩展、Token 控制、来源整理、模式过滤。

```python
class ContextBuilder:
    def build(self, results: list[RetrievalCandidate], *, max_tokens: int = 6000, mode: str) -> ContextResult: ...
```

`ContextResult` 包含三个字段：`blocks: list[ContextBlock]`（已排序、已合并、可直接拼进提示词）、`sources: list[dict]`（与既有 `serialize_source()` 字段完全一致，保证 SSE 与前端不受影响）、`token_count: int`。

具体规则：

1. **父级合并**：同一父块只出现一次，来源编号共用。
2. **排序**：按最终分数降序，但保证至少一个 `content_type=definition` 的块排在首个概念类块之前（初学者友好）。
3. **Token 预算**：`RAG_CONTEXT_MAX_TOKENS` 默认 6000；超预算时从最低分块开始裁剪，父块优先保留。
4. **来源编号**：继续输出 `[资料N]`，编号与 `sources` 数组下标严格一致（现有 `parse_layered_answer` 依赖这一契约）。
5. **模式过滤**：`practice` 模式剔除 solution/answer；`simple` 模式优先 definition/example；`deep` 模式保留 formula/derivation。
6. **去重**：内容相似度 > 0.95 的块只保留分数高的一条。

---

## 20. 个性化 RAG

### 20.1 画像数据的两个用途

| 用途 | 数据 | 是否作为事实证据 |
|---|---|---|
| 提示词注入（现有） | 掌握度、薄弱点、目标、最近学习 | 否 |
| 检索期适配（新增） | 同一份画像 | 否，只影响过滤与排序 |

硬约束保持不变：画像与记忆**不得**作为事实证据，也不占用 `[资料N]` 编号。

### 20.2 难度适配

```text
目标难度区间 = [max(1, level - 1), min(5, level + 1)]
```

其中 `level` 由 `weak_knowledge_states` / `user_knowledge_mastery` 折算（掌握度 0–1 → 1–5 档）。
找不到该知识点的掌握度记录时不加难度过滤，只按查询意图过滤。

### 20.3 内容类型偏好

```text
新手（level <= 2）：优先 definition / intuition / simple_example
熟练（level >= 4）：优先 derivation / advanced_example / exercise
```

表现为**排序加权**而非硬过滤：满足偏好类型的候选在 `structure_bonus` 之外叠加 `profile_bonus`（上限 0.1），避免把唯一正确证据过滤掉。

### 20.4 数据来源

复用现有 `LearnerProfileService.build()`，新增一个只读方法 `difficulty_preference(workspace_id, knowledge_points)`，输出难度区间与偏好类型；不新增表，不改变现有画像结构。

---

## 21. 端到端流程与编排

### 21.1 节点命名（对齐源文档第 42 节）

| 入库 | 查询 |
|---|---|
| Parse Node | Analyze Node |
| Classify Node | Rewrite Node |
| Structure Node | Retrieve Node |
| Chunk Node | Rerank Node |
| Metadata Node | Context Node |
| Embedding Node | Tutor Node |
| Index Node | — |

### 21.2 编排实现

不引入 LangGraph，用「显式阶段管道 + Celery 任务」实现同等语义：

- `IngestPipeline.run(document_id)` 顺序调用上述节点，每进入一个节点写入 `document_pipeline_events`（`document_id / node / status / started_at / finished_at / duration_ms / detail`）。
- Celery 任务按节点拆分（`parse_document_task` → `analyze_document_task` → …），失败可单节点重试，不需要重跑整条链路。
- `QueryPipeline.run(...)` 为纯异步函数链，不依赖 Celery（查询必须同步返回）。
- 节点内部异常一律转成 `NodeResult(status="failed", reason=...)` 并触发对应降级，而不是抛到顶层。

选择理由：两条流水线都是线性 DAG，Celery 已在本项目承担异步职责并已配置 `task_always_eager` 测试路径；LangGraph 会引入新的运行时与状态序列化成本，而收益（条件分支、循环、检查点）本设计均未使用。

---

## 22. API 设计

### 22.1 新增端点

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/debug/retrieval` | 检索调试，返回 `query_analysis / dense_results / bm25_results / merged_results / reranked_results / final_context` |
| `POST` | `/api/documents/{document_id}/reindex` | 重建单文档索引（删除旧索引 → 重新 parse/chunk/embed/index） |
| `POST` | `/api/rag/practice` | 按 `subject / knowledge_point / difficulty` 检索题目，供练习页使用 |
| `POST` | `/api/documents/{document_id}/enrich` | 补跑富化失败的 chunk |

`/api/debug/retrieval` 仅在 `RAG_DEBUG_ENDPOINT_ENABLED=true`（默认开发环境开启、生产关闭）时注册，且必须通过既有认证依赖。

### 22.2 语义映射（不新增 `/api/v1` 前缀）

| 源文档 | 本仓库 |
|---|---|
| `POST /api/v1/documents/upload` | `POST /api/workspaces/{workspace_id}/documents`（现有） |
| `GET /api/v1/documents/{id}` | `GET /api/documents/{document_id}`（现有） |
| `DELETE /api/v1/documents/{id}` | `DELETE /api/documents/{document_id}`（现有，需扩展到三层索引同步删除） |
| `POST /api/v1/rag/query` | `POST /api/chat`（现有，SSE 契约不变） |
| `POST /api/v1/rag/practice` | 新增 `/api/rag/practice` |
| `POST /api/v1/documents/{id}/reindex` | 新增 `/api/documents/{document_id}/reindex`（现有 `/reprocess` 保留为别名） |

### 22.3 文档状态响应扩展

`GET /api/documents/{document_id}/status` 增加可选字段：`pipeline_stage`、`stage_history`、`index_stale`、`parse_degraded`、`enrichment_pending`。既有字段保持不变，前端可渐进接入。

---

## 23. 状态机、配置与可观测

### 23.1 状态机

```text
UPLOADED → PARSING → CLASSIFYING → STRUCTURING → CHUNKING → ENRICHING → EMBEDDING → INDEXING → READY
                                                                                              ↘ FAILED
```

兼容做法：

- `documents.status` 继续只取 `pending | processing | ready | failed`（`pending` ≈ UPLOADED，`processing` 覆盖中间全部阶段，`ready` ≈ READY，`failed` ≈ FAILED）。
- 细粒度阶段写入新列 `documents.pipeline_stage`，历史数据默认 `NULL`，前端按需显示。
- 阶段事件写入 `document_pipeline_events`，用于耗时统计与失败定位。

### 23.2 新增配置项

```text
# 分块
RAG_CHUNK_MIN_TOKENS=150
RAG_CHUNK_TARGET_TOKENS=600
RAG_CHUNK_MAX_TOKENS=1200
RAG_CHUNK_OVERLAP_RATIO=0.15
RAG_SEMANTIC_SPLIT_THRESHOLD=0.62
RAG_SEMANTIC_SPLIT_MAX_SENTENCES=400

# 嵌入
DEFAULT_EMBEDDING=BAAI/bge-m3
RAG_EMBEDDING_PROVIDER=local
RAG_EMBEDDING_DIMENSION=1024
RAG_EMBEDDING_MAX_TOKENS=8192

# 多向量
RAG_MULTIVECTOR_KINDS=content,summary,question

# 重排
RAG_RERANK_PROVIDER=local
RAG_RERANK_MODEL=BAAI/bge-reranker-v2-m3
RAG_RERANK_CANDIDATES=30
RAG_RERANK_TOP_N=8
RAG_RERANK_TIMEOUT_SECONDS=20

# 查询理解与上下文
RAG_QUERY_ANALYZER=hybrid
RAG_QUERY_ANALYZE_TIMEOUT_SECONDS=8
RAG_CONTEXT_MAX_TOKENS=6000
RAG_PARENT_MAX_TOKENS=2000

# 富化与索引
RAG_ENRICH_ENABLED=true
RAG_ENRICH_CONCURRENCY=3
RAG_INDEX_VERSION=2
RAG_DEBUG_ENDPOINT_ENABLED=false
```

既有 `CHUNK_SIZE` / `CHUNK_OVERLAP` 保留（`FallbackChunkStrategy` 仍在使用），但不再是主切分参数。

### 23.3 观测字段

按源文档第 47 节记录：`document_id / parser / document_type / chunk_count / embedding_count / parse_time / analyze_time / chunk_time / enrich_time / embedding_time / index_time / retrieval_time / rerank_time / total_query_time`。

落点：`document_pipeline_events`（入库）+ `retrieval_runs`（新增 `query_analysis`、`rerank_provider`、`rerank_time_ms`、`filter_snapshot`、`vector_kinds_hit` 列，查询）。

---

## 24. 异常与 Fallback

逐条对齐源文档第 44 节，并补上本仓库特有的情况：

| 场景 | 行为 |
|---|---|
| 文档分类失败 | → `unstructured`，走语义切分 |
| 结构识别失败 | → 不写 `structure_nodes`，整体语义切分 |
| 语义切分失败（embedding 不可用） | → `RecursiveCharacterSplitter` |
| 富化失败 | 该 chunk `enrichment_status=failed`，规则兜底，入库继续 |
| embedding 失败 | 文档 `status=failed`，`error_message` 记录原因，支持重试 |
| 向量库不可用 | 关键词检索单边降级（现有行为） |
| 关键词索引不可用 | 向量检索单边降级（现有行为） |
| 两者都不可用 | 不调用模型，返回可重试的检索失败（现有行为） |
| 重排模型不可用 / 超时 | 降级为确定性重排，`degradation_reason="rerank_unavailable"/"rerank_timeout"` |
| 查询分析失败 / 超时 | `intent=default`，不过滤 |
| 父级扩展失败（父块缺失） | 直接用子块，记录 `parent_missing` |
| 扫描件无文本 | `parse_degraded="scanned_pdf"`，明确提示未做 OCR，不静默通过 |
| 索引指纹不匹配 | 标记 `index_stale`，后台重建，期间按旧索引继续服务 |

所有降级都必须落到 `degradation_reason` 或 `error_message`，不允许出现「静默降级」。

---

## 25. 迁移与重新索引

### 25.1 数据库迁移

迁移按实施阶段拆分，每个 revision 只包含该阶段真正会用到的结构，避免先建空表再回填：

| revision | 阶段 | 内容 |
|---|---|---|
| `0004_rag_pipeline_events` | 阶段 0 | `documents.pipeline_stage`；新建 `document_pipeline_events` |
| `0005_rag_parse_degradation` | 阶段 1 | `documents.parse_degraded` |
| `0006_rag_structure_units` | 阶段 2 | `documents.document_type` / `classification_meta`；`document_chunks` 结构列（`unit_id`、`parent_id`、`chunk_level`、`content_type`、`document_type`、`subject`、`page_end`）及索引；新建 `knowledge_units`、`structure_nodes`；`knowledge_points.unit_id` |
| `0007_rag_multivector_index` | 阶段 3 | `documents.index_stale`；`document_chunks` 富化与索引列（`summary`、`keywords`、`knowledge_points`、`difficulty`、`enrichment_status`、`index_version`、`metadata`）；`retrieval_runs.query_analysis` / `vector_kinds_hit` |
| `0008_rag_rerank_profile` | 阶段 4 | `retrieval_runs.rerank_provider` / `rerank_time_ms` / `filter_snapshot` |

每个 revision 的通用规则：

1. 全部 DDL 使用 inspect 存在性判断，保持可重复执行（与 `0003_ai_tutor_memory.py` 的写法一致）。
2. `downgrade()` 只删除本 revision 新增的结构，不触碰既有数据。
3. `down_revision` 串联成链，任何阶段都可以单独升级到该阶段并保持应用可运行。

### 25.2 向量索引重建（换模型的必然动作）

`bge-small-zh-v1.5`（512 维）→ `bge-m3`（1024 维）维度不同，Chroma collection 无法混用，必须重建：

```text
1. 启动自检发现索引指纹不匹配
2. 对每个 workspace 的每个 ready 文档入队 reindex 任务
3. 逐个文档执行：删除旧向量（两种 metadata 字段名）→ 重新 parse → chunk → enrich → embed → 写 Chroma + document_chunks
4. 全部完成前，检索继续按旧索引服务；命中旧索引的 chunk 仍可正常回答
5. 全部完成后清除 index_stale
6. 重建期间的检索结果带 index_stale 提示，不报错
```

重建是**幂等且可中断**的：单文档失败不影响其他文档，失败文档进入重试队列。

### 25.3 兼容与回滚

- 回滚路径：把 `DEFAULT_EMBEDDING` 改回 `BAAI/bge-small-zh-v1.5` 并再次触发重建；DDL 可 downgrade。
- 旧 metadata 兼容：`doc_id` 与 `document_id`、`page_num` 与 `page_start` 的读写兼容在索引层统一处理（现有 `_document_where()` 已用 `$or` 处理文档 ID，扩展到其余字段）。
- 历史会话与学习产物不受影响：`conversations.sources` 保留来源快照，`knowledge_points` 的人工编辑保留。

---

## 26. 测试策略

### 26.1 Parser / Block 测试

- PDF、DOCX、MD、TXT、PPTX、HTML、XLSX、CSV 均能产出非空 `Block[]`，且 Block 类型正确。
- 公式块保留 LaTeX；代码块不被截断；DOCX 表格转成 `table` 块而非纯文本。
- 上传白名单与 `ParserFactory.supported_types()` 一致（回归 §1.3 第 3 条）。

### 26.2 Chunk 测试

- 章节完整性：一个小节不被跨节合并。
- 题目与答案正确关联，且可分别索引。
- 代码块与公式块完整（原子性）。
- 大小不变量：所有非原子块落在 `[min, max]` 内，或带有明确的 `oversized_ok` / `merged_reason` 标注。
- Token 估算器与真实 tokenizer 偏差在 ±10% 以内。

### 26.3 Retrieval 测试

- 标注集上统计 `Recall@5`、`Recall@10`、`MRR`、`NDCG`，并分别记录 `rerank_provider=local|none` 的基线。
- 元数据过滤同时作用于向量与关键词两路（构造「只有关键词侧会召回被排除类型」的用例）。
- RRF、归一化与融合公式的数值正确性（现有 `test_hybrid_retrieval.py` 扩展）。
- 多向量按 `chunk_id` 归并：同一逻辑块命中多个 kind 只出现一次。
- Parent Expansion：命中子块返回父块；父块超限时回退子块。

### 26.4 学习专项测试（对齐源文档第 50 节）

- **练习模式**：返回的候选集中不含 `solution` / `answer`（在召回层断言，而非在最终上下文断言）。
- **解题模式**：允许检索到 solution。
- **初学者模式**：definition/example 的排序优先于 derivation。
- **高级模式**：允许高级推导内容进入上下文。
- **引用编号**：`[资料N]` 与 `sources` 下标一一对应，且不因父级合并出现悬空编号。
- **画像边界**：画像与记忆不出现在 `sources` 中，不占用引用编号。

### 26.5 回归与集成测试

- 现有 48 个后端测试全部通过；特别是 `test_hybrid_retrieval.py`、`test_document_jobs.py`、`test_content_filter.py`、`test_phase_two_parsers.py`、`test_source_navigation.py`、`test_chat_architecture.py`。
- 集成链路：上传 → 阶段事件齐全 → 检索命中 → SSE 事件序列不变 → 引用可点击。
- 降级链路：逐一切断 embedding / Chroma / FTS / LLM / reranker，验证降级原因与用户可见提示。
- 迁移测试：0004 迁移可重复执行；`downgrade` 不破坏既有数据。
- 前端测试：`sourceNavigation`、`answerLayers`、`learningMessageContent` 等现有用例不受来源结构变化影响。

---

## 27. 分阶段实施

按源文档第 52 节的 MVP 顺序展开，每阶段结束都必须保持可部署、可回滚、测试全绿。

### 阶段 0：基线与安全网（重构前置）

- 建立检索评测标注集（现有真实问题 → 期望 chunk），记录当前 `Recall@5 / MRR` 基线。
- 修复 §1.3 的 5 个缺陷（距离度量、查询/入库 embedding 路径统一、白名单一致性、DOC 声明、死代码）。
- 补齐 `document_pipeline_events` 与阶段列。

验收：基线指标入库；缺陷全部有回归测试；现有测试全绿。

### 阶段 1：统一文档模型与解析层

- `Document` / `Block` 契约与 `ParserFactory` 注册表。
- 8 类解析器 Block 化，公式/代码/表格显式建模。
- PDF 质量判定与扫描件标记。

验收：所有格式产出 Block[]；解析器测试通过；扫描件不再静默通过。

### 阶段 2：分类、结构、知识单元与切分

- `DocumentClassifier`、`StructureAnalyzer`、`KnowledgeUnitExtractor`。
- `ChunkStrategy` 策略族 + `ChunkRouter` + `ChunkValidator`。
- 语义切分与递归兜底。
- Parent-Child 组装。

验收：结构不变量测试通过；`document_type` 落库；父块可展开。

### 阶段 3：富化与多向量索引

- LLM 富化（批量、并发、幂等、失败可重试）。
- `knowledge_units` / `structure_nodes` 落库。
- 多向量写入与索引指纹。
- **切换 embedding 到 bge-m3 并完成全量重建。**

验收：chunk 元数据齐全；多向量归并正确；重建完成后评测指标不低于阶段 0 基线。

### 阶段 4：查询理解与重排

- Query Analyzer / Rewrite / RetrievalRouter / Metadata Filter。
- Reranker 三态接入与超时降级。
- 阈值重标定。
- Context Builder 与 Parent Expansion。
- 学习范围（`RetrievalScope` + `ScopeResolver`）插入在 Query Rewrite 与 RetrievalRouter 之间，
  见 `docs/superpowers/specs/2026-09-18-ai-learning-scope-dynamic-retrieval-design.md`。

验收：评测指标显著优于基线；练习模式不返回答案；降级路径可复现。

### 阶段 5：学习场景与个性化

- 题目/答案分索引接入练习与错题。
- 画像参与检索期难度适配与偏好加权。
- `/api/debug/retrieval` 调试端点与观测面板。

验收：源文档第 1 节的 11 项能力（概念讲解、教材问答、题目检索、练习生成、解题讲解、错题回顾、笔记检索、个性化学习、学习路径推荐、上下文补全、长期知识记忆）逐项可用并有测试佐证。

---

## 28. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| bge-m3 首次下载与内存占用（约 2GB 级） | 首次入库/查询变慢，低配机器压力大 | 启动时按需加载并提供 `RAG_EMBEDDING_PROVIDER=openai` 的云端 embedding 备选；文档中明确硬件建议 |
| CPU 重排延迟 | 查询变慢 | 默认候选 30、超时 20 s 降级；提供 `api` 与 `none` 两种替代；提示可调 `RAG_RERANK_TOP_N` |
| 全量重建期间索引不一致 | 检索质量临时下降 | 重建期间继续用旧索引；带 `index_stale` 提示；逐文档幂等重建 |
| 富化成本（每个 chunk 一次 LLM） | 入库变慢、费用上升 | 批量 8–12 个/次、并发 3、`RAG_ENRICH_ENABLED` 开关、失败不阻断 |
| 阈值重标定不准导致误判 | 假阳性（不相关被判 supported）或过度拒答 | 用标注集重标定；阈值随 `retrieval_runs` 留痕可回溯；保留 `none` 基线对照 |
| 多向量使存储翻倍 | 磁盘占用 | kind 白名单只对概念/定义/公式/题解生成；`RAG_MULTIVECTOR_KINDS` 可裁剪 |
| 结构识别在无标题文档上失效 | 退回定长切分 | 明确降级路径与原因记录，不静默 |
| 新旧索引元数据字段名并存 | 过滤失效 | 过滤对象统一生成，两种字段名同时兼容（沿用 `$or` 模式），由单测覆盖 |

---

## 29. 验收清单

入库侧：

1. 8 类格式均可产出带类型的 `Block[]`，公式保留 LaTeX，代码块与公式块不被拆散。
2. `documents.document_type` 被分类填充，分类失败降级 `unstructured` 且入库继续。
3. 每个 ready 文档都有 `knowledge_units` 与 `structure_nodes`（无结构文档允许为空）。
4. 每个 child chunk 都有 `content_type`、`parent_id`（若有父）、`summary`/`keywords`/`difficulty`（富化成功或规则兜底）。
5. 扫描件被明确标记且不参与检索，而不是产出空 chunk 后静默通过。
6. `document_pipeline_events` 记录全部节点与耗时。

检索侧：

7. 用户提问先经过 Query Analyzer；LLM 不可用或超时时行为与今天一致。
8. 元数据过滤同时作用于向量与关键词两路。
9. 练习模式在召回层就排除 solution/answer。
10. Reranker 生效时评测指标优于基线；不可用/超时时自动降级且可追溯。
11. 命中子块时上下文中出现父块完整上下文；同一父块不重复占用编号。
12. `[资料N]` 编号与 `sources` 一一对应，画像与记忆不占用编号。
13. `POST /api/chat` 的 SSE 事件序列与来源字段与重构前完全一致。

工程侧：

14. 现有 48 个后端测试与前端测试全部通过。
15. 迁移可重复执行，`downgrade` 安全。
16. 每一条降级路径都有 `degradation_reason`，无静默降级。
17. `/api/debug/retrieval` 能完整回放一次查询的各阶段结果。
