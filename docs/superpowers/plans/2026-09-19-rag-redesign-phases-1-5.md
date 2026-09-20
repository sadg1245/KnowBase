# RAG 重构阶段 1–5 执行计划与状态

> 依据：`docs/superpowers/specs/2026-09-18-rag-redesign-design.md`（§5–§22）与项目设计文档 §9.18。
> 目标：按阶段把「解析 → 分类 → 结构 → 切分 → 富化 → 索引 → 查询 → 重排 → 上下文 → 个性化」逐段落到可验收的代码。
> 约定：每个阶段都必须保持既有召回契约与 SSE 契约不变，只新增或替换内部实现。

## 阶段 0：基线与安全网

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 检索评测指标（Recall@k / MRR / NDCG）与用例装载 | ✅ | `backend/app/rag/eval/metrics.py`、`backend/tests/test_rag_eval_metrics.py` |
| 离线运行器（label / run） | ✅ | `backend/app/rag/eval/runner.py` |
| 统一查询与入库的 embedding 路径 | ✅ | `test_embedding_path.py` |
| Chroma collection 距离度量固定 cosine | ✅ | `test_vector_store_space.py` |
| 上传白名单与解析器工厂共用真相 | ✅ | `documents.ALLOWED_EXTENSIONS` ← `pipeline.supported_file_types()` ← `ParserFactory.supported_types()` |
| 入库阶段事件与 `pipeline_stage` | ✅ | `document_pipeline_events`、`test_pipeline_events.py` |
| 真实基线指标入库 | ⛔ 待执行 | `backend/tests/rag_eval/baseline.json` 仍是 `no_ready_documents`，`cases.jsonl` 仍是占位 |

基线采集（需要 Docker 或本地 Redis/Celery + 可用 embedding + 至少一份 ready 文档）：

```powershell
docker compose up -d --build
docker compose exec backend python -c "import sqlite3;c=sqlite3.connect('/app/data/sqlite/knowbase.db');print(c.execute('select learning_status,count(*) from documents group by 1').fetchall())"
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -m app.rag.eval.runner label --query "什么是条件概率" --workspace <workspace_id>
# 人工确认相关 chunk_id 后写入 backend/tests/rag_eval/cases.jsonl（≥8 条用例）
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -m app.rag.eval.runner run --cases tests/rag_eval/cases.jsonl --out /tmp/rag_baseline.json
```

## 阶段 1：统一文档模型与解析层

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| `Document` / `Block` / `ParseQuality` 契约 | ✅ | `backend/app/rag/contracts.py` |
| Block 构建工具（标题栈、表格、公式、代码、列表、引用） | ✅ | `backend/app/rag/parsers/blocks.py` |
| `ParserFactory` 注册表 + 扩展名别名 + 文件头校验 | ✅ | `backend/app/rag/parsers/factory.py` |
| 注册表成为上传白名单与解析路由的唯一来源 | ✅ | `pipeline.supported_file_types()` 与 `_get_parser()` 均委托注册表 |
| 章节级 chunk → `Block[]` 适配 + 解析质量判定 | ✅ | `backend/app/rag/parsers/adapters.py` |
| DOCX 原生 Block 化（表格按单元格建模，避免管道符歧义） | ✅ | `DocxParser.parse_blocks` |
| Markdown / PDF / TXT 结构化 Block | ✅ | 适配层标题栈 + 代码/公式/表格识别 |
| PPTX / XLSX / CSV / HTML 原生 Block 化 | ✅ | `app/rag/parsers/native.py`：表格按单元格建模、幻灯片标题/正文分块 |
| 扫描件不再静默通过（落库 + 不建索引 + 文档页提示） | ✅ | 迁移 0006 + `documents.parse_degraded` / `parse_quality`；降级文档不进入切分与向量化；`DocumentDetail` 显示扫描件提示 |
| `pipeline._FILE_TYPE_MAP` 与注册表同源 | ✅ | `_FILE_TYPE_MAP = ParserFactory.file_type_aliases()` |

## 阶段 2：分类、结构与知识单元 ✅

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 文档分类（规则优先 + LLM 兜底 + unstructured 降级） | ✅ | `app/rag/analyzers/document_classifier.py` |
| 结构树（章节树 / 题目树 + 父节点跨度聚合） | ✅ | `app/rag/analyzers/structure_analyzer.py` |
| 知识单元抽取（章节/定义/公式/例题/代码/题干/解答） | ✅ | `app/rag/analyzers/knowledge_extractor.py` |
| 幂等落库 + 分类列 | ✅ | `app/rag/analyzers/persistence.py`、迁移 0007 |
| `knowledge_points.unit_id` 追溯 | ✅ | 迁移 0007（可空外键，删除单元时置空） |
| 流水线接入（parsing → structure → chunking → embedding → indexing） | ✅ | `DocumentPipeline.process_document` |
| 验收测试 | ✅ | `test_rag_analyzers.py`（9 项）、`test_document_analysis_persistence.py`（含重新索引幂等） |

已知边界：分类只使用解析出的文本与结构信号，扫描件（无可提取文本）不写分类结果，`document_type` 保持 NULL。

## 阶段 3：切分、富化与多向量索引

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 切分策略族（结构/题目/问答/代码/语义/兜底） | ✅ | `app/rag/chunking/strategies.py`、`semantic.py` |
| `ChunkRouter` 按 `document_type` 路由 + 未知/异常兜底 | ✅ | `app/rag/chunking/router.py` |
| 大小校验与归一化（150/1200 上限、原子块不切分、同父合并、重叠去重） | ✅ | `app/rag/chunking/validator.py`、`test_rag_chunking.py` |
| Parent-Child 与 chunk 元数据（迁移 0008） | ✅ | `document_chunks.chunk_level / parent_id / unit_id / content_type / … / index_version`；parent 行落库、仅 child 进向量 |
| 流水线接入（chunking → embedding → indexing） | ✅ | 切分在正文边界过滤**之后**执行；`chunks_count` 只计 child |
| 富化：规则 + LLM 批量 + 状态 + 补跑端点 | ✅ | `app/rag/enrichment/metadata_enricher.py`、`POST /api/documents/{id}/enrich`、`test_rag_enrichment.py` |
| 多向量（content / summary / question）+ 归并 + kind 白名单 | ✅ | `app/rag/indexing/multivector.py`（写入展开）、`search._vector_recall`（按逻辑 chunk_id 归并、证据正文取 content 向量）、`retrieval_hits.vector_kinds`（迁移 0009） |
| 索引指纹与 `index_stale` 提示（§15.2） | ✅ | `app/rag/indexing/index_versions.py`（读 / 写 / gap 判定）+ 入库后写入指纹 + `/api/chat` 的 `evidence.index_stale` 可选键 |
| embedding 保持现状（不切换到 bge-m3） | ⛔ 已决策不做 | 2026-09-20 决策：继续使用现有 embedding 模型，不做 bge-m3 切换与全量重建。指纹与 `index_stale` 机制保留，将来需要时仍可切换（见下方「决策记录」）。阶段 3 验收不再要求换模型 |
| 验收：评测指标不低于阶段 0 基线 | ⛔ 待执行 | 依赖阶段 0 基线采集 |

## 阶段 4：查询理解、重排与上下文 ✅

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| Query Analyzer（意图 / 语言 / 实体 / 公式与代码线索） | ✅ | `app/rag/query/analyzer.py` |
| Query Rewrite（默认关闭，确定性扩展） | ✅ | `app/rag/query/rewriter.py` |
| 路由计划（练习模式排除答案、意图偏好内容类型、概念类走多向量） | ✅ | `app/rag/query/router.py` |
| Reranker 三态（none / local / api + 超时与异常降级） | ✅ | `app/rag/retrieval/reranker.py` |
| Parent Expansion（父块整节 + 超预算退回子块与相邻块 + 同父去重） | ✅ | `app/rag/retrieval/parent.py` |
| Context Builder（[资料N] 编号、预算、重复块跳过） | ✅ 已接线 | `app/rag/retrieval/context.py`，`/api/chat` 上下文改用该构建器（格式与既有提示词一致） |
| 重排 / Parent Expansion / 练习模式过滤接入 `/api/chat` 主链路 | ✅ | `app/rag/retrieval/orchestrator.py`（sources 仍逐条子块、引用编号沿用首个命中；上下文用父块去重）+ `/api/chat` 接线；证据事件新增 `query_intent / rerank_degraded / context_notes` 可选键 |
| Metadata 预过滤（subject / difficulty / content_type / document_type） | ✅ | `build_metadata_where`（Chroma）+ `build_sql_metadata_filter`（FTS）语义一致、两条召回都下推；`test_rag_metadata_filter.py` |
| 阈值重标定（用标注集回写 supported / second / limited） | 🚧 机制就绪 | `app/rag/eval/calibration.py` + `runner calibrate`；样本不足或标签单一显式拒绝给建议，真实数字仍需标注集 |
| 题目 / 答案分索引接入练习与错题（§16） | ✅ | chunk 级 `content_type=question/answer` 已落库；`/api/chat` 接受 `mode="practice"` 并在召回层排除 answer/solution；练习结果页「问 AI 老师（不透露答案）」入口；`POST /api/rag/practice` 返回资料原题（见下方补充） |
| 验收：降级路径可复现 | ✅ | `test_rag_query_retrieval.py` 覆盖重排超时 / 分数不匹配 / 父块超预算 |

## 阶段 5：学习场景与个性化

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 画像参与检索期软先验 + 排序 Bonus（≤0.1，不影响证据分级） | ✅ | `ScopeResolver.profile_preferences` + `_profile_hint_bonus` |
| 范围解析（strict/focused/smart/global）+ 扩展阶梯 + 审计 | ✅ | `scope_resolver.py` + `scoped_retrieval.py` |
| 难度适配与内容类型偏好（§20.2 / §20.3） | ✅ | `LearnerProfileService.difficulty_preference` + `_profile_preference_bonus`（掌握度 → 难度档 → 区间与内容类型，只进排序） |
| `/api/debug/retrieval` | ✅ | 默认关闭（`RAG_DEBUG_ENDPOINT_ENABLED`），开启后返回范围、证据状态与逐条分项打分 |
| 观测面板（前端） | ✅ | 学习页「检索诊断」抽屉 `RetrievalDiagnostics`：范围 / 证据 / 降级 / `index_stale` / 上下文处理 + 逐条候选分项打分；run id 由 SSE `evidence` 新增可选键提供 |
| 11 项学习能力逐项可用并有测试佐证 | ✅ | 见下表 |
| Metadata 硬预过滤（subject / difficulty / content_type / document_type） | ✅ | `build_metadata_where`（Chroma）+ `build_sql_metadata_filter`（FTS，语义一致）；`RetrievalRequest.metadata_filter` 下推到两条召回；练习模式把 `exclude_content_types` 直接下推 |
| 阈值重标定 | ✅ 机制就绪 | `app/rag/eval/calibration.py` + `runner calibrate`；样本不足或标签单一显式拒绝给出建议（真实数字仍需标注集） |

### 11 项学习能力与证据

| # | 能力 | 实现位置 | 测试佐证 |
| --- | --- | --- | --- |
| 1 | 概念讲解 | `/api/chat` 教学模式 + 来源优先分层回答 | `test_learning_answer_policy`、`test_prompt_assembly` |
| 2 | 教材问答 | 范围解析 + 混合召回 + 父块扩展 | `test_retrieval_scope`、`test_rag_orchestrator` |
| 3 | 题目检索 | `content_type=question` 分块 + 练习模式路由 | `test_rag_chunking`、`test_rag_query_retrieval` |
| 4 | 练习生成 | `assessment_service` 题库与测验运行 | `test_assessment_api`、`test_assessment_service` |
| 5 | 解题讲解 | 题干/解答分块（`ExamChunkStrategy`）+ 分层回答 | `test_rag_chunking`、`test_learning_answer_policy` |
| 6 | 错题回顾 | 错题记录 + 薄弱知识状态 + 复习中心 | `test_weakness_service`、`test_review_service` |
| 7 | 笔记检索 | 学习笔记与长期记忆召回 | `test_learning_memory_service`、`test_memory_hooks` |
| 8 | 个性化学习 | 画像注入 + 难度/内容类型偏好（只影响排序） | `test_learner_profile_service`、`test_rag_profile_difficulty` |
| 9 | 学习路径推荐 | 仪表盘知识库排序 + 目标进度 + 学习顺序 | `test_dashboard_service`、`test_goal_service` |
| 10 | 上下文补全 | Parent Expansion + Context Builder + 会话历史 | `test_rag_orchestrator`、`test_prompt_assembly` |
| 11 | 长期知识记忆 | 记忆落库 + 混合召回 + 导师注入 | `test_learning_memory_service`、`test_tutor_api` |

## 阶段 4 补充：练习语境端到端可达（2026-09-20 追加）

### 决策记录（2026-09-20）：不切换 embedding 模型

- **决策**：保持当前 embedding 模型，不做 `bge-m3` 切换，也不做全量重建。
- **直接后果**：切分上限 `MAX_CHUNK_TOKENS = 1200` 大于当前模型窗口（`bge-small-zh-v1.5` 为 512 token），
  `sentence-transformers` 会静默截断，超出窗口的尾部不会进入向量。设计文档 §10.4 的 400–800 目标块大小
  原本是按 `bge-m3` 的 8192 窗口定的，现在这条前提不再成立。
- **本次已采取**：embedding 侧显式统计并告警（`EmbeddingService.last_truncation`、`max_input_tokens`），
  把静默截断变成可读信号；原子块（公式/代码/表格）按设计不细分，所以即使将来收紧切分上限，这条检查仍然必要。
- **仍待决策**：是否把切分上限收到模型窗口内（例如 ~480 token）。代价是重新入库生成索引；
  当前重构尚未发布、也还没有真实基线，所以现在做的成本接近 0，越晚做越贵。

问题：检索层已经能按 `practice` 排除答案，但 `ChatRequest.mode` 的模式白名单里没有 `practice`，
HTTP 层根本进不到这条路径；前端练习页也没有任何追问入口，所以「练习页尚未切换调用」一直悬着。

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| `/api/chat` 接受 `mode="practice"` 并给出练习语境提示词 | ✅ | `app/schemas/schemas.py` 模式白名单 + `learning_answer_service.MODE_INSTRUCTIONS["practice"]`；`test_chat_practice_context.py` |
| `POST /api/rag/practice` 按知识点/难度返回资料原题 | ✅ | `app/api/routes/rag.py`、`app/schemas/rag.py`；`test_rag_practice_endpoint.py`（只返回 child 原题、排除 solution/answer、未知知识点 fail-closed、跨库 404、limit 校验） |
| 练习结果页「问 AI 老师（不透露答案）」入口 | ✅ | `QuizResults` / `QuizRunner` / `Practice` 透传 handler，经 `quickQuestionDestination(..., 'practice')` 进入学习会话；`practiceComponents.test.tsx`、`quickQuestion.test.tsx` |
| quiz 生成的题目来源升级（§16.3「先检索原题、命中不足再用 LLM 补足」） | ⛔ 待实施 | 生成链路目前仍是「知识点证据 + LLM 出题」；`/api/rag/practice` 已就绪，等生成器接入 |

## 每阶段通用约束

## 阶段 3 增强：富化与入库解耦（2026-09-19 追加）

问题：富化原本同步跑在入库主链路里，一本 600 页书要 60+ 次模型调用，
chunking 阶段实测 246 秒，前端等待超时（后端仍在正常处理）。

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 入库只写 content 向量并立刻 `ready` | ✅ | `DocumentPipeline.process_document` 末尾按 `RAG_ENRICH_ENABLED` 标记 `enrichment_state` 并派发后台任务 |
| 后台富化任务（增量补 summary/question 向量） | ✅ | `app/rag/enrichment/job.py`、Celery `collector.enrich_document`、`document_jobs.enqueue_document_enrichment` |
| 增量向量写入（不动 content，先删精确 id 再 upsert） | ✅ | `VectorStore.delete_ids` + `expand_child_vectors(include_content=False)` |
| 进度与可重试 | ✅ | 迁移 0010：`documents.enrichment_state / enrichment_progress`；`POST /api/documents/{id}/enrich` 补跑 |
| 界面提示 | ✅ | 文档详情页显示「后台增强中 / 部分完成 / 已完成 / 未成功」与已处理片段数 |
| 重复执行幂等 | ✅ | 已 ready 的 chunk 不再调用模型；无新富化且上次已写向量时跳过重写 |

## 阶段 2 增强：学习内容生成的两级降级 ✅

原问题：只把前 30 个 chunk 喂给模型并要求整篇结构化（20 字段 Pydantic 校验），
大文档容易整篇 `failed`（实测 20 个校验错误），且"只覆盖前 30 个 chunk"既未落库也未提示。

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| 首选"整篇一次"路径 | ✅ | `generate_document_learning_content`：成功即写全文材料，覆盖率记 `strategy=whole_document` |
| 失败/超预算 → 按章分批降级 | ✅ | `chapter_groups` + `_chapter_prompt`（章节提示词带 `CHAPTER SCOPE` 标记）+ `_generate_by_chapters` |
| 逐章校验与合并 | ✅ | 每章独立走 `build_learning_material` 校验；`merge_chapter_materials` 按顺序合并、去重、限长 |
| 覆盖率与部分完成 | ✅ | 迁移 0011 `documents.learning_coverage`；`learning_status` 支持 `partial`，失败章节写入 `learning_error_message` |
| 幂等与增量重试 | ✅ | 章节产物缓存在 coverage 中；重跑只重跑失败/缺失章节（`force=True` 才整篇重跑，显式"重新生成"走 force） |
| 不做硬截断 | ✅ | 单章文档整篇失败时如实上报，不伪造 partial |
| 前端提示 | ✅ | 文档详情页显示"学习内容部分完成（x/y 章）"与缺失章节提示 |
| 验收测试 | ✅ | `test_learning_content_fallback.py`（6 项：整篇路径、按章降级、部分失败、只补失败章节、单章不伪造 partial、合并去重） |

- 只新增内部实现，不改 SSE 事件名与 `/api/chat`、`/api/documents` 既有响应字段。
- 每阶段结束必须跑：相关单测 + `test_hybrid_retrieval.py`、`test_retrieval_scope.py`、`test_scope_security.py`、`test_chat_architecture.py` 回归。
- 任何质量缺陷（扫描件、解析降级、索引过期）都必须显式落库并能在文档详情页看到，不允许静默通过。
- 评测指标只能来自真实运行；不可用时如实写 `no_ready_documents`，不得编造。
