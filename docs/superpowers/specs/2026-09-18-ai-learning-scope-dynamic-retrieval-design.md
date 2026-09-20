# AI 学习范围与动态检索架构重构设计（重写版）

> 版本：v2.0（对源文档《拾光 KnowBase：AI 学习范围与动态检索架构重构设计文档 v1.0》的重写）
> 日期：2026-09-18
> 适用项目：拾光 KnowBase（自托管个人 AI 学习助手）
> 文档类型：架构设计（本文件只定义架构与契约，不含代码改动）
> 关联文档：
> - `docs/superpowers/specs/2026-09-18-rag-redesign-design.md`
> - `docs/superpowers/specs/2026-09-18-ai-tutor-learning-profile-design.md`
> - `docs/2026-09-18-knowbase-project-design.md`

---

## 0. 文档说明与重写原则

### 0.1 为什么重写

源文档给出的方向（`LearningSession + RetrievalScope + ScopeResolver + Personalized RAG`）是正确的，但它是一份**平台无关的抽象设计**，与本仓库的真实实现存在若干冲突，直接照着实现会踩到已经固化的契约。

本重写版遵守四条原则：

1. **以现有代码为准**：所有结论都标注真实的模块、表、字段与契约，而不是设想中的结构。
2. **不破坏已冻结契约**：`source_first` 三层回答、`strict_sources` 兼容字段被忽略、所有权 fail-closed、`selected_document_ids` 兼容，都不因本重构而改变。
3. **可执行**：每个阶段都能落到具体的文件与函数，并给出可验收的判定。
4. **删掉做不到的部分**：源文档中依赖当前不存在的数据结构、或与既有契约冲突的设计，在本版中被删除或降级，并在第 14 章逐条对照说明。

### 0.2 重写后的三处核心变化

| 源文档 | 本重写版 | 原因 |
| --- | --- | --- |
| `allow_model_knowledge` 作为 Scope 字段 | **删除**，模型知识不进 Scope | 回答层已固定为 `source_first` + 显式模型兜底 + 三层回答，Scope 若也能控制模型知识会产生两个真值来源 |
| `knowledge_point_ids` 直接映射 Chroma metadata filter | **降级为软先验 + 文档映射** | 现有 chunk metadata 里没有知识点字段（见 4.3），直接做 filter 会静默匹配不到任何内容 |
| SMART 三级扩展（当前库 → 相关库 → 全库） | **SMART 两级扩展（当前库 → 全部个人库）** | 「相关 Workspace 识别」需要跨库相关性排序能力，当前没有，v1 不做 |

### 0.3 术语约定

用户可见的词只有一个：**学习范围**。
`RetrievalScope`、`ScopeResolver`、`MetadataFilter`、`Collection`、`Top-K` 都属于内部实现，不出现在 UI 文案中。

---

## 1. 现状盘点（基于真实代码）

### 1.1 当前链路

```text
POST /api/chat                        backend/app/api/routes/search.py
  │
  ├─ if not payload.workspace_id: HTTPException(400, "Please choose a knowledge base ...")
  ├─ owned_workspace(db, payload.workspace_id, current_user)          # 所有权校验（仅 workspace）
  ├─ ConversationService.create_session / update_session(
  │        workspace_id, document_ids, mode, strict_sources)
  ├─ HybridRetrievalService(db, partial(_vector_recall, owned_workspace_ids=owned_ids))
  │        .retrieve(query, workspace_id=..., document_ids=..., session_id=..., ...)
  ├─ LearnerProfileService(db, user).build(workspace_id=..., question=...)
  ├─ LearningMemoryService.recall(question, workspace_id=...)
  └─ build_learning_prompt(...) → SSE 流式回答 → Conversation 落库（含 sources / retrieval_run_id）
```

### 1.2 现有能力矩阵

| 能力 | 现状 | 位置 |
| --- | --- | --- |
| 知识库 / 文档 / 知识点 | 已有 | `workspaces` / `documents` / `knowledge_points` |
| 混合检索（向量 + FTS5） | 已有 | `services/hybrid_retrieval.py` |
| 加权 RRF 融合 + 结构化重排 | 已有 | `weighted_rrf` / `rerank_score` |
| 证据分级 | 已有，三档 | `classify_evidence`：`supported` / `limited` / `insufficient` |
| 学习会话 | 已有（即 `ChatSession`） | `models/chat.py` |
| 会话级文件约束 | 已有，必填语义 | `chat_sessions.selected_document_ids` |
| 用户画像 | 已有，按 workspace 聚合 | `services/learner_profile.py` |
| 长期记忆 | 已有 | `services/learning_memory.py` |
| 检索审计 | 已有基础版 | `retrieval_runs` / `retrieval_hits` |
| 向量召回多库循环 | **已具备**（`workspace_id=None` 时遍历 `owned_workspace_ids`） | `search.py::_vector_recall` |
| 关键词召回多库 | **不具备**（`c.workspace_id = :workspace_id` 单值） | `hybrid_retrieval.py::_keyword_recall` |
| 范围（Scope）概念 | **不具备** | — |
| 动态范围扩展 | **不具备** | — |
| 知识点驱动的检索 | **不具备** | — |

结论：基础设施足够，缺的是**范围契约层**与**跨库融合执行**，不是重建检索系统。

### 1.3 现存的具体问题

| 编号 | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| P1 | AI 学习被硬绑定单一知识库 | `search.py` 中 `if not payload.workspace_id: raise HTTPException(400, ...)` | 无法跨库、无法「全部知识库」、无法无文件学习 |
| P2 | `document_ids` 未经所有权校验 | `payload.document_ids` 直接传入 `HybridRetrievalService.retrieve` | 传入他人文档 id 会构造出越权过滤条件（当前因 workspace 已校验，危害被缓解，但一旦放开多库即为真实越权） |
| P3 | 关键词召回单库 | `AND c.workspace_id = :workspace_id` | 跨库扩展只能拿到向量侧结果，证据质量不对称 |
| P4 | 检索参数以 `workspace_id + selected_document_ids` 形式扩散 | `ChatSession` / `Conversation` / `RetrievalRun` / 前端 `api.ts` / `LearningChat.tsx` | 每加一种范围都要改一遍签名，属源文档 §43.1 明令避免的形态 |
| P5 | 范围决策不可审计 | `retrieval_runs` 只有 `workspace_id` / `document_ids` | 无法回答「为什么这次搜到了另一个知识库」 |
| P6 | 画像不参与范围判断 | `LearnerProfileService.build` 仅按 `workspace_id` 过滤 | 画像只能影响讲解，不能影响「去哪找」 |
| P7 | 前端把「选知识库 + 选文件」当必填前置 | `LearningChat.tsx::createSession` 在 `!workspaceId` 时直接 warning 并打开设置抽屉 | 用户必须手工决定检索范围，学习被退化为文档聊天 |
| P8 | 跨库分数不可比 | Chroma 按 collection 返回距离，`_vector_recall` 用 `1 - distance` 后**跨 collection 直接排序** | 不同库的分数尺度不同，直接合并会系统性偏向某一库 |

---

## 2. 设计目标与非目标

### 2.1 目标

G1 AI 学习不再以「选中文件」为前提，`Document Selection` 降级为**可选约束**。
G2 引入统一范围契约 `RetrievalScope`，替代所有 `workspace_id + selected_document_ids` 形式的检索参数。
G3 引入 `ScopeResolver`，把抽象范围解析为可执行范围，并按证据质量决定是否扩展。
G4 支持跨知识库检索，且融合方式在数学上可比（分数可比 + 排名融合）。
G5 范围决策全程可审计、可复现、可解释。
G6 用户始终保有明确控制权：`strict` 范围内绝不自动扩展。
G7 前端只暴露「学习范围」，不暴露检索内部概念。

### 2.2 非目标（本版明确不做）

N1 不拆独立的 `learning_sessions` 表（继续复用 `chat_sessions`）。
N2 不做「相关 Workspace 识别」与跨库相关性排序。
N3 不做单一大 Collection 的全局索引重建（保留一 Workspace 一 Collection）。
N4 不改动回答层策略（`source_first` + 三层回答 + 模型兜底判定逻辑不变）。
N5 不让画像进入证据判断链路。
N6 不引入新的向量库或搜索引擎。

---

## 3. 领域模型

### 3.1 分层职责

```text
User
 │
 ├── LearningDomain
 │
 ├── Workspace（知识库）        ← 资料组织单元 + 默认学习上下文，不是唯一检索边界
 │      ├── Document            ← 知识来源
 │      │      └── KnowledgeUnit（结构层语义对象，文档结构派生）
 │      └── KnowledgePoint      ← 学习层核心对象，能力画像的锚点
 │
 ├── LearningProfile            ← 影响范围 / 排序 / 难度 / 提示词
 │
 └── ChatSession（MVP 期的 LearningSession）
         ├── workspace_id（默认上下文，可空）
         ├── scope_mode
         ├── scope_config
         ├── preferred_mode（教学模式）
         ├── selected_document_ids（兼容字段 → 映射进 scope_config）
         └── Conversation[]
```

### 3.2 三条职责边界

| 对象 | 是 | 不是 |
| --- | --- | --- |
| Workspace | 默认学习上下文、默认检索起点 | 绝对检索边界 |
| Document | 知识来源、精读入口 | 能力主体 |
| KnowledgePoint | 能力主体、掌握度锚点 | 检索过滤键（见 4.3） |

用户掌握的是 `KnowledgePoint`，不是 `Document`。文档掌握度只能作为阅读进度指标，不进入能力画像核心。

### 3.3 为什么不拆 `learning_sessions`

源文档 §25 的判断在本仓库同样成立，且更彻底：`chat_sessions` 已经承载了会话生命周期、`preferred_mode`、`selected_document_ids`、收藏、摘要、`last_message_at` 排序，以及前端 `useChatSessions` 的完整交互。拆表会同时改动 ORM、迁移、REST、SSE、前端状态与既有测试，收益为零。

**决策**：MVP 只给 `chat_sessions` 增加 `scope_mode` / `scope_config`；当出现「一个学习会话包含多个 Chat Session」或「练习/复习/AI Tutor 共用同一会话」的真实需求时再拆表。

---

## 4. RetrievalScope 契约

### 4.1 数据结构

```python
# app/schemas/scope.py（新增）
from typing import Literal
from pydantic import BaseModel, Field

ScopeMode = Literal["strict", "focused", "smart", "global"]


class RetrievalScope(BaseModel):
    """用户视角的范围描述（持久化在 chat_sessions.scope_config 的语义部分）。"""

    mode: ScopeMode = "smart"

    workspace_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    knowledge_point_ids: list[str] = Field(default_factory=list)

    # 仅 focused 生效：是否允许从「优先文件」扩展到「当前知识库」
    allow_workspace_expansion: bool = False


class ResolvedRetrievalScope(BaseModel):
    """可直接驱动检索的可执行范围（每次请求实时计算，不入库为主键）。"""

    mode: ScopeMode

    # 硬过滤：检索层必须遵守，空列表表示「不过滤该维度」
    hard_workspace_ids: list[str] = Field(default_factory=list)
    hard_document_ids: list[str] = Field(default_factory=list)

    # 软优先：只影响排序权重，不排除任何候选
    preferred_workspace_id: str | None = None
    preferred_document_ids: list[str] = Field(default_factory=list)
    preferred_knowledge_point_ids: list[str] = Field(default_factory=list)

    # 扩展控制
    expansion_enabled: bool = False
    expansion_ceiling: Literal["none", "workspace", "owned_workspaces"] = "none"
    # 扩展到上限后允许使用的知识库集合（仅 focused 使用）
    expansion_workspace_ids: list[str] = Field(default_factory=list)

    # 审计
    resolved_by: Literal["explicit", "session", "fallback"] = "explicit"
    resolution_reason: list[str] = Field(default_factory=list)
    dropped_ids: list[str] = Field(default_factory=list)
```

### 4.2 与源文档的字段差异

| 源文档字段 | 本版处理 | 说明 |
| --- | --- | --- |
| `allow_cross_workspace` | 由 `mode` + `expansion_ceiling` 表达 | 两个开关表达同一件事会产生矛盾状态（如 `strict` + `allow_cross_workspace=true`） |
| `allow_model_knowledge` | 删除 | 回答层契约，不属于范围层 |
| `hard_filter_documents` / `hard_filter_workspaces` | 改为 `hard_document_ids` / `hard_workspace_ids` 的**空列表语义** | 用「列表是否为空」表达是否过滤，避免布尔位与列表不一致 |
| `resolution_reason: list` | 保留并扩展 | 追加 `resolved_by` / `dropped_ids` |

### 4.3 `knowledge_point_ids` 的真实能力边界（重要修正）

源文档 §16 假设可以构造：

```python
filters = {"knowledge_points": {"$contains_any": scope.knowledge_point_ids}}
```

**当前不成立。** 现有 chunk metadata 只包含 `doc_id` / `document_id` 类字段、`page_num`、`heading`、`heading_level`、`section_path`、`chunk_index`（见 `hybrid_retrieval.py::upsert_document_chunks`），没有知识点字段。按源文档实现会得到一个永远匹配不到结果的 filter。

本版采用两级方案：

| 级别 | 做法 | 阶段 |
| --- | --- | --- |
| v1 | 知识点 → `knowledge_points.document_id` / `workspace_id` 解析为「优先文档 + 优先知识库」，作为**软先验**参与排序；同时对 `heading` / `section_path` 与知识点标题做匹配加权 | Phase D |
| v2 | 新增 `chunk_knowledge_points` 映射（chunk_id ↔ knowledge_point_id），才能做真正的硬过滤 | 后续 |

### 4.4 持久化形态

`chat_sessions.scope_config`（JSON）只存用户可见语义，不存解析结果：

```json
{
  "workspace_ids": ["ws_ai"],
  "document_ids": [],
  "knowledge_point_ids": ["kp_langgraph_state"],
  "allow_workspace_expansion": true
}
```

`scope_mode` 单独成列（便于索引与统计），`mode` 不重复写入 `scope_config`。

---

## 5. 四种模式语义（最终定义）

| mode | 起点 | 硬过滤 | 扩展阶梯 | 扩展上限 | 典型场景 | 前端标签 |
| --- | --- | --- | --- | --- | --- | --- |
| `strict` | 指定文档或指定知识库 | 有（文档 > 知识库） | **不扩展** | `none` | 只根据这篇论文回答 / 只学这本教材 | 当前文件、指定资料（关闭扩展）、当前知识库 |
| `focused` | 优先文件 | 知识库级（若给定） | 文件 → 当前知识库 | `workspace` | 精读一本书，允许引用同库补充资料 | 指定资料（开启扩展） |
| `smart` | 当前知识库（可缺省） | 无 | 当前库 → 全部个人库 | `owned_workspaces` | 默认学习 | 智能选择 |
| `global` | 全部个人知识库 | 无 | 无需扩展 | `owned_workspaces` | 跨领域比较、综合复习 | 全部知识库 |

### 5.1 三种「限定」的精确区别

```text
strict  + document_ids   →  只在这些文档里找，找不到就回答「资料不足」，绝不外扩
focused + document_ids   →  先在这些文档里找，不够时扩到这些文档所在的知识库
smart   + workspace_ids  →  先在指定知识库找，不够时扩到用户全部知识库
```

### 5.2 不可破坏契约：strict 不扩展

```text
若 scope.mode == "strict"：
    expansion_enabled 必须为 False
    即使 evidence_status == "insufficient" 也不得扩展
```

这条契约是「用户明确限定范围」与「系统自作主张」之间的分界线，必须由测试守住。

### 5.3 前端映射

```text
学习范围
● 智能选择（推荐）   → mode=smart,  workspace_ids=[当前库]（若有）, allow_workspace_expansion=true
○ 当前知识库         → mode=strict, workspace_ids=[当前库]
○ 当前文件           → mode=strict, document_ids=[当前文档]
○ 指定资料           → mode=strict|focused, document_ids=[...]
                        └─ 开关「资料不足时允许搜索当前知识库」：开 → focused，关 → strict
○ 全部知识库         → mode=global
```

### 5.4 无知识库时的退化

```text
smart 且无 workspace_id  → 退化为 global（全部个人知识库）
smart 且 ScopeResolver 异常 → 退化为「当前 Workspace」；若无 Workspace → global
strict/focused 且无任何可解析范围 → 视为配置错误，回退到当前 Workspace，并在 resolution_reason 记录
```

---

## 6. ScopeResolver

### 6.1 职责

只做一件事：把**抽象范围**变成**可执行范围**，并解释为什么。
它不检索、不排序、不判断证据。

### 6.2 位置

```text
backend/app/services/scope_resolver.py   （新增）
```

### 6.3 接口

```python
class ScopeResolver:
    def __init__(
        self,
        db: AsyncSession,
        *,
        user: User,
        owned_workspace_ids: list[str],
    ) -> None: ...

    async def resolve(
        self,
        *,
        query: str,
        session: ChatSession | None,
        scope: RetrievalScope,
        workspace_id: str | None = None,
        profile: LearnerProfileSnapshot | None = None,
    ) -> ResolvedRetrievalScope: ...
```

### 6.4 解析算法（与模式一一对应）

```python
async def resolve(...) -> ResolvedRetrievalScope:
    # 0. 安全前置：所有权收敛（见第 8 章）
    owned = set(owned_workspace_ids)
    requested_ws = scope.workspace_ids or ([workspace_id] if workspace_id else [])
    ws_ok, ws_dropped = partition(requested_ws, owned)
    docs_ok, docs_dropped, doc_ws = await self._filter_owned_documents(scope.document_ids, owned)

    if scope.mode == "strict":
        # 文档优先于知识库；两者都给定时取「文档所在库 ∩ 给定库」的语义
        return ResolvedRetrievalScope(
            mode="strict",
            hard_document_ids=docs_ok,
            hard_workspace_ids=[] if docs_ok else ws_ok,
            preferred_workspace_id=workspace_id if workspace_id in owned else None,
            expansion_enabled=False,
            expansion_ceiling="none",
            resolution_reason=["explicit_strict"],
            dropped_ids=ws_dropped + docs_dropped,
        )

    if scope.mode == "focused":
        ceiling_ws = ws_ok or sorted(doc_ws) or ([workspace_id] if workspace_id in owned else [])
        return ResolvedRetrievalScope(
            mode="focused",
            hard_workspace_ids=ceiling_ws,
            preferred_workspace_id=ceiling_ws[0] if ceiling_ws else None,
            preferred_document_ids=docs_ok,
            expansion_enabled=bool(scope.allow_workspace_expansion and ceiling_ws),
            expansion_ceiling="workspace",
            resolution_reason=["explicit_focused"],
            dropped_ids=ws_dropped + docs_dropped,
        )

    if scope.mode == "global":
        return ResolvedRetrievalScope(
            mode="global",
            hard_workspace_ids=list(owned),  # 始终写入收敛后的具体集合
            preferred_workspace_id=workspace_id if workspace_id in owned else None,
            expansion_enabled=False,
            expansion_ceiling="owned_workspaces",
            resolved_by="explicit",
            resolution_reason=["explicit_global"],
            dropped_ids=ws_dropped + docs_dropped,
        )

    # smart
    start_ws = ws_ok or ([workspace_id] if workspace_id in owned else [])
    return ResolvedRetrievalScope(
        mode="smart",
        hard_workspace_ids=start_ws,      # 第一轮只搜起点库
        preferred_workspace_id=start_ws[0] if start_ws else None,
        preferred_document_ids=docs_ok,
        preferred_knowledge_point_ids=scope.knowledge_point_ids,
        expansion_enabled=bool(start_ws),
        expansion_ceiling="owned_workspaces",
        resolved_by="session" if session and not ws_ok else "explicit",
        resolution_reason=_smart_reasons(start_ws, profile),
        dropped_ids=ws_dropped + docs_dropped,
    )
```

> 实现不变式：`hard_workspace_ids` 始终是**已收敛到当前用户所有权**的具体知识库集合，
> 空列表只表示「该用户没有任何知识库」，检索层必须按 fail-closed 处理，不得解释为「不过滤」。

`_smart_reasons` 把画像线索变成可读审计文本，例如：

```text
["当前知识库为 AI Agent", "画像薄弱点 LangGraph State 与查询相关", "起点范围 1 个知识库"]
```

### 6.5 画像如何参与解析（有界）

画像只影响三类决策，且都有上限：

| 决策 | 允许 | 禁止 |
| --- | --- | --- |
| 起点知识库排序 | 按 `preferred_workspace_id` 加权 | 画像不得扩大 `hard_workspace_ids` |
| 知识点软先验 | 薄弱 + 与查询相关的知识点进入 `preferred_knowledge_point_ids` | 不得作为硬过滤 |
| 排序 Bonus | `profile_bonus ≤ 0.10` | 不得改变 `evidence_status`（见 7.4） |

---

## 7. 检索执行层重构

### 7.1 请求对象

源文档 §15 的 `RetrievalRequest` 方向正确，本版落到真实签名：

```python
# backend/app/services/hybrid_retrieval.py
@dataclass
class RetrievalRequest:
    query: str
    scope: ResolvedRetrievalScope
    owned_workspace_ids: list[str]
    session_id: str | None = None
    user_message_id: str | None = None
    profile_bonus: dict[str, float] | None = None   # chunk_id → bonus（0..1）
    profile_hints: list[str] | None = None          # 画像薄弱点标题，命中标题/正文时有界加权
    vector_top_k: int = 20
    keyword_top_k: int = 20
    selected_top_k: int = 8


class HybridRetrievalService:
    async def retrieve_scoped(self, request: RetrievalRequest) -> HybridRetrievalResult: ...

    # 兼容壳：旧调用方无需一次性改完
    async def retrieve(self, *, query, workspace_id, document_ids, **kwargs) -> HybridRetrievalResult:
        scope = legacy_scope(workspace_id=workspace_id, document_ids=document_ids)
        return await self.retrieve_scoped(RetrievalRequest(...))
```

`legacy_scope()` 必须产出 `mode="strict"`（见 9.3 的兼容映射），保证旧调用方行为**逐字节不变**。

### 7.2 向量召回：多 Collection

`_vector_recall` 已支持 `workspace_id=None` 时遍历 `owned_workspace_ids`，改造点只有三个：

```python
async def _vector_recall(
    *,
    query: str,
    workspace_ids: list[str],          # 由 str | None 改为显式列表
    document_ids: list[str],
    top_k: int,
) -> list[dict]:
```

1. `workspace_ids` 为空 → 使用调用方传入的 owned 全集（由执行层决定，函数内不做权限推断）。
2. 每个 collection 的候选保留 `workspace_id` 字段，供审计与融合权重使用。
3. **每个 collection 内部先归一化**再进入全局融合（修正 P8）。

`document_ids` 过滤复用现有 `_document_where()`（同时兼容 `doc_id` 与 `document_id` 两种历史 metadata 键）。

### 7.3 关键词召回：改为集合过滤

```python
# 现在
"AND c.workspace_id = :workspace_id"

# 改为
"AND c.workspace_id IN :workspace_ids"   # SQLAlchemy bindparam(expanding=True)
```

`hard_document_ids` 沿用现有 `document_id IN (...)` 分支，只需把参数名从单个 workspace 换成列表。

### 7.4 跨库融合（修正源文档 §18 的缺口）

源文档只说了「不要简单拼接」，但没给做法。本版规定三步：

```text
① 每个 collection 取 Top-K（K = SCOPE_PER_WORKSPACE_TOP_K）
       ↓
② 分库分数归一（消除距离尺度差异）
   score'_c = normalize_within_collection(1 - distance)
       ↓
③ 全局 RRF 融合（复用 weighted_rrf）+ 结构重排（复用 rerank_score）
      rank 来自 ② 之后的全库统一排名
       ↓
④ 排序 = 基础重排分 + 画像 Bonus（≤ 0.10）
       ↓
⑤ 证据分级只用基础分，不用 Bonus
```

第 ⑤ 步是本版新增的硬约束：

```python
base_score = rerank_score(...)                              # 用于 classify_evidence
final_score = base_score + PROFILE_RANK_BONUS_MAX * bonus   # 用于最终排序
evidence_status = classify_evidence([base_score, ...])      # 不受画像影响
```

理由：源文档 §33.4 要求「画像不进入证据」，但若 Bonus 参与证据分级，新手画像会**降低**证据等级并触发不必要的范围扩展，等于画像间接污染了证据判断。
`profile_bonus` 需写入 `retrieval_hits`（新增列），保证审计可复现。

### 7.5 父级扩展（Parent Expansion）

保留 RAG 重构设计中的 Parent Expansion 位置不变：在 Reranker 之后、ContextBuilder 之前。跨库检索不改变该顺序，`parent_id` 解析仍以 chunk 自身所属 collection 为准。

---

## 8. 安全与所有权

### 8.1 现状与风险

当前 `document_ids` 未经所有权校验（P2）。单库场景下 `workspace_id` 校验挡住了越权，但本重构放开多库后，这是**真实可利用的越权面**。

### 8.2 强制规则

```text
R1 ScopeResolver 只能在 owned_workspace_ids 内解析范围。
R2 所有 document_ids 必须验证 ∈ 该用户拥有的 workspace 的文档集合。
R3 客户端传入的 workspace_ids / document_ids / knowledge_point_ids 一律不可信。
R4 无法验证的 id 一律剔除，并记入 ResolvedRetrievalScope.dropped_ids。
R5 剔除后范围为空 → fail-closed（返回空结果），不得退化为「不过滤」。
R6 全部过滤条件最终仍由 RetrievalRun 所属 user 的 owned 集合兜底。
```

### 8.3 实现位置

```python
# backend/app/services/ownership.py（扩展）
@dataclass
class OwnedScope:
    workspace_ids: list[str]
    document_ids: list[str]
    document_workspace_ids: dict[str, str]           # 文档 → 所属知识库
    knowledge_point_ids: list[str]
    knowledge_point_document_ids: dict[str, str | None]
    knowledge_point_workspace_ids: dict[str, str]
    dropped_ids: list[str]


async def resolve_owned_scope(
    db: AsyncSession,
    user: User,
    *,
    workspace_ids=(),
    document_ids=(),
    knowledge_point_ids=(),
) -> OwnedScope:
    """把客户端范围收敛到当前用户拥有的资源，并返回被剔除的 id。"""
```

复用现有 `owned_workspace()` / `_owned_workspace_ids()`，不新增权限模型。

### 8.4 端点权限契约

| 端点 | 校验 |
| --- | --- |
| `PATCH /api/chat/sessions/{id}/scope` | 会话归属 + 范围内所有 id 归属 |
| `POST /api/chat`（带 `scope_override`） | 同上，请求级覆盖同样收敛 |
| `GET /api/chat/retrieval-runs/{run_id}` | 运行记录所属 user（经 session 归属反查） |

---

## 9. 数据模型与迁移

### 9.1 新增迁移

```text
0005_learning_scope
```

```text
chat_sessions.scope_mode     VARCHAR(32) NOT NULL DEFAULT 'strict'
chat_sessions.scope_config   JSON        NOT NULL DEFAULT '{}'

retrieval_runs.scope_mode          VARCHAR(32)
retrieval_runs.scope_snapshot      JSON    NOT NULL DEFAULT '{}'
retrieval_runs.scope_resolution    JSON    NOT NULL DEFAULT '{}'
retrieval_runs.expansion_rounds    INTEGER NOT NULL DEFAULT 0
retrieval_runs.expanded_scope      BOOLEAN NOT NULL DEFAULT 0

retrieval_hits.profile_bonus       FLOAT   NOT NULL DEFAULT 0.0
```

### 9.2 回填策略（关键）

```text
scope_mode 默认值必须是 'strict'，不是 'smart'。
理由：迁移前行为 = 单库 + 可选文件过滤 + 从不扩展 = strict。
      默认 'smart' 会在迁移瞬间改变所有历史会话的检索行为。
```

回填规则：

```python
if session.selected_document_ids:
    scope_mode = "strict"
    scope_config = {"document_ids": session.selected_document_ids}
elif session.workspace_id:
    scope_mode = "strict"
    scope_config = {"workspace_ids": [session.workspace_id]}
else:
    scope_mode = "smart"
    scope_config = {}
```

### 9.3 兼容映射（不可破坏）

```text
selected_document_ids  →  RetrievalScope.document_ids
workspace_id           →  RetrievalScope.workspace_ids
（无 scope 字段）      →  mode = strict（旧行为等价）
strict_sources         →  继续忽略（回答层已固定 source_first）
```

读路径：`_session()` 响应在不破坏 `document_ids` / `workspace_id` 的前提下，**新增** `scope` 对象。
写路径：`PATCH /api/chat/sessions/{id}` 收到 `document_ids` 时同步更新 `scope_config.document_ids`，保持两个视图一致。

### 9.4 ORM 变更

```python
# models/chat.py
class ChatSession(Base):
    ...
    scope_mode = Column(String(32), nullable=False, default="strict")
    scope_config = Column(JSON, nullable=False, default=dict)
```

`RetrievalRun` / `RetrievalHit` 同步增加上述列。


---

## 10. API 设计

### 10.1 会话范围

```http
PATCH /api/chat/sessions/{session_id}/scope

{
  "mode": "smart",
  "workspace_ids": ["ws_ai"],
  "document_ids": [],
  "knowledge_point_ids": [],
  "allow_workspace_expansion": true
}
```

```http
GET /api/chat/sessions/{session_id}/scope

{
  "mode": "smart",
  "scope": { "...RetrievalScope..." },
  "last_resolution": { "...ResolvedRetrievalScope...", "resolved_at": "..." }
}
```

### 10.2 对话请求

```http
POST /api/chat
```

```json
{
  "question": "...",
  "session_id": "...",
  "workspace_id": null,
  "document_ids": [],
  "scope_mode": "smart",
  "scope_config": {"allow_workspace_expansion": true},
  "scope_override": null
}
```

契约变化（相对现状）：

| 项 | 现状 | 重构后 |
| --- | --- | --- |
| `workspace_id` 必填 | 必填，缺失 400 | **可空**；为空且 `scope_mode=smart` → 全局个人库 |
| `document_ids` 语义 | 「限定文件」 | 兼容保留，等价于 `scope_config.document_ids` |
| 新增 | — | `scope_mode` / `scope_config` / `scope_override` |
| 响应 SSE | `session` / `evidence` / `sources` / `suggestions` / `done` | 追加 `scope` 事件（含 `expansion_rounds` / `resolution_reason`） |

`scope_override` 只对当次请求生效，不写入会话。

### 10.3 检索审计查询

源文档 §35 建议 `/api/debug/retrieval`。本仓库目前没有 `debug` 命名空间，且该端点会暴露检索内部细节，因此改为**归属校验 + 运行记录粒度**：

```http
GET /api/chat/retrieval-runs/{run_id}

{
  "scope_mode": "smart",
  "input_scope": {"...": "..."},
  "resolved_scope": {"...": "..."},
  "expansion": [
    {"round": 0, "workspace_ids": ["ws_ai"], "evidence_status": "insufficient"},
    {"round": 1, "workspace_ids": ["ws_ai", "ws_nlp"], "evidence_status": "supported"}
  ],
  "dense_results": [],
  "keyword_results": [],
  "reranked_results": [],
  "final_context": []
}
```

### 10.4 审计记录示例

```json
{
  "scope_mode": "smart",
  "initial_workspace_ids": ["ws_ai"],
  "final_workspace_ids": ["ws_ai", "ws_nlp"],
  "expanded_scope": true,
  "expansion_rounds": 1,
  "reasons": [
    "当前知识库召回证据为 insufficient",
    "查询涉及 Word2Vec",
    "允许扩展至全部个人知识库"
  ]
}
```

---

## 11. 前端设计

### 11.1 交互形态

`LearningChat.tsx` 顶部新增：

```text
学习范围：智能选择 ▼
```

菜单：

```text
智能选择（推荐）
当前知识库
当前文件
指定资料
全部知识库
```

当前上下文条（不出现检索术语）：

```text
当前学习：AI Agent / RAG
学习范围：智能选择
教学模式：深入学习
```

指定资料被选中时：`学习范围：指定资料 · 3 个文件`，点击展开文件列表。

范围扩展发生后，用一句人话解释：

```text
已在「全部知识库」中找到补充资料
```

### 11.2 改造点

| 文件 | 改动 |
| --- | --- |
| `frontend/src/pages/LearningChat.tsx` | 新增范围选择器；`createSession` 不再强制要求 `workspaceId`；上下文条增加学习范围 |
| `frontend/src/pages/learningScope.ts`（新增） | 前端选项 ↔ `scope_mode` / `scope_config` 的纯函数映射，便于单测 |
| `frontend/src/pages/documentScope.ts` | 保持现状（文件多选组件复用） |
| `frontend/src/services/api.ts` | `ChatSession` 增加 `scope`；`createChatSession` / `updateChatSession` 支持 scope；`streamChat` 支持 `scopeMode` / `scopeConfig` |
| `frontend/src/hooks/useChatSessions.ts` | 会话创建/更新参数透传 scope |

### 11.3 入口映射

| 入口 | 行为 | Scope |
| --- | --- | --- |
| DocumentDetail「用 AI 学习此文档」 | 精读保留 | `strict` + `document_ids=[当前文档]` |
| KnowledgeBase「开始 AI 学习」 | 以库为起点 | `smart` + `workspace_ids=[当前库]` |
| Dashboard「继续学习 LangGraph State」 | 推荐驱动，无需选文件 | `smart` + `knowledge_point_ids=[...]`（workspace 由知识点反查） |
| 会话侧边栏新建 | 默认 | `smart`（沿用上次范围） |

### 11.4 前端不暴露的字段

```text
RetrievalScope / MetadataFilter / Collection / Top-K / RRF / Reranker / Evidence Threshold
```

---

## 12. 与既有设计的关系

### 12.1 插入位置

```text
RAG 重构阶段 0  基线
阶段 1  文档模型
阶段 2  结构与切分
阶段 3  富化与多向量
阶段 4  查询理解与重排
        ├─ 4a  QueryAnalyzer / QueryRewrite
        ├─ 4b  LearningContext + ScopeResolver     ← 本设计插入点
        ├─ 4c  MetadataFilter + 多库 Retriever
        └─ 4d  Reranker + Parent Expansion + ContextBuilder
阶段 5  学习场景与个性化
```

### 12.2 完整查询链路（重构后）

```text
User Query
    ↓
Query Analyzer
    ↓
Query Rewrite
    ↓
Learning Context Builder
    ├── Session（学习目标 / 当前知识点 / 教学模式）
    ├── Profile（画像快照）
    └── Memory（长期记忆）
    ↓
ScopeResolver（+ Ownership 收敛）
    ↓
ResolvedRetrievalScope
    ↓
Retrieval Router
    ├── 单库 → 单 Collection
    └── 多库 → 多 Collection（分库 Top-K + 分库归一）
    ↓
Metadata Filter（Chroma where / SQLite FTS where）
    ↓
Dense Search           FTS5 / BM25
    └──────────┬──────────┘
               ↓
      Candidate Merge（全局 RRF）
               ↓
      Reranker（+ Profile Bonus ≤ 0.1）
               ↓
      Evidence Classifier（只用基础分）
               ↓
      证据不足 & 允许扩展 → 下一轮（回到扩展阶梯）
               ↓
      Parent Expansion
               ↓
      Context Builder
               ↓
      Tutor（source_first 三层回答）
```

### 12.3 与画像重构的关系

| 画像用途 | 是否允许 | 说明 |
| --- | --- | --- |
| 影响检索范围 | 允许（有界） | 只影响起点排序与软先验 |
| 影响排序 | 允许（≤ 0.10） | Bonus，不做硬过滤 |
| 影响难度适配 | 允许 | 既有能力 |
| 影响提示词 | 允许 | 既有 `format_profile_block` |
| 影响证据真值 | **禁止** | 证据分级只用检索基础分 |

---

## 13. 范围扩展机制

### 13.1 扩展阶梯

```text
Level 0  指定 Document            （strict / focused 起点）
Level 1  当前 Workspace           （smart 起点）
Level 2  全部个人知识库           （smart 扩展目标 / global 起点）

模型知识不属于检索 Scope，属于回答层兜底。
```

### 13.2 触发条件

```python
if evidence_status == "supported":
    stop()                       # 证据充分，立即作答
elif evidence_status == "limited":
    if scope.expansion_enabled:
        expand_once()            # 只扩一轮，倾向用当前证据作答
    else:
        stop()
elif evidence_status == "insufficient":
    if scope.expansion_enabled:
        expand_scope()           # 扩到阶梯上限
    else:
        stop()                   # 无上限时用模型兜底作答
```

### 13.3 扩展预算（源文档缺失，本版补齐）

新增配置项：

```text
SCOPE_DEFAULT_MODE                  = "smart"
SCOPE_MAX_EXPANSION_ROUNDS          = 2
SCOPE_EXPANSION_LATENCY_BUDGET_MS   = 3000
SCOPE_PER_WORKSPACE_TOP_K           = 10
PROFILE_RANK_BONUS_MAX              = 0.10
```

熔断规则：

```text
R1 扩展轮数 ≤ SCOPE_MAX_EXPANSION_ROUNDS
R2 检索累计耗时 > SCOPE_EXPANSION_LATENCY_BUDGET_MS → 停止扩展，用已有证据作答
R3 扩展后候选未增加 → 标记 expanded_scope=false，不重复扩展同一范围
R4 单侧检索失败（向量或关键词任一可用即继续）→ 记录 degradation_reason，不阻断回答
R5 strict 模式 → 永不进入扩展分支
```

---

## 14. 与源文档的逐条差异

| # | 源文档 | 本重写版 | 类型 |
| --- | --- | --- | --- |
| 1 | `allow_model_knowledge` 字段 | 删除 | 删除（与 source_first 契约冲突） |
| 2 | `allow_cross_workspace` 字段 | 由 `mode` + `expansion_ceiling` 表达 | 改写 |
| 3 | 知识点 metadata filter | v1 改为软先验 + 文档映射，v2 再建映射表 | 降级（当前数据结构不支持） |
| 4 | SMART 三级扩展 | SMART 两级扩展 | 降级（无跨库相关性排序能力） |
| 5 | 独立 `learning_sessions` 表 | 复用 `chat_sessions` + 两列 | 保持源文档 MVP 结论 |
| 6 | 迁移默认 `smart` | 迁移默认 `strict`，新会话默认 `smart` | 修正（避免迁移即变行为） |
| 7 | 未定义扩展预算 | 新增轮数 / 延迟 / 空扩熔断 | 补充 |
| 8 | `ResolvedRetrievalScope` 布尔硬过滤位 | 改为「空列表 = 不过滤」 | 改写 |
| 9 | 画像可作为排序 Bonus | 明确 Bonus ≤ 0.1 且**不影响证据分级** | 收紧 |
| 10 | `/api/debug/retrieval` | 改为归属校验的 `/api/chat/retrieval-runs/{run_id}` | 改写 |
| 11 | 未讨论越权 | 新增第 8 章所有权收敛与 fail-closed | 补充 |
| 12 | 未讨论跨库分数可比 | 新增分库归一 + 全局 RRF | 补充 |
| 13 | 前端文案 | 保留范围选择器，去掉 debug 类描述 | 保持 |
| 14 | 开发顺序 A–E | 保留并补验收判定 | 保持 |

---

## 15. 分阶段实施

### Phase A：范围契约（不改行为）

实现：

```text
app/schemas/scope.py                     RetrievalScope / ResolvedRetrievalScope
app/models/chat.py                       ChatSession.scope_mode / scope_config
alembic/versions/0005_learning_scope.py  迁移 + strict 回填
app/services/scope_resolver.py           legacy_scope()（只做兼容映射）
```

验收：

```text
✓ 迁移后所有历史会话 scope_mode = 'strict'
✓ 现有 /api/chat 行为不变（回归测试全绿）
✓ GET /api/chat/sessions/{id} 响应新增 scope 字段且不破坏旧字段
```

### Phase B：前端范围选择

实现：

```text
frontend/src/pages/learningScope.ts（新增）
frontend/src/pages/LearningChat.tsx
frontend/src/services/api.ts
```

此时 `smart` 可以仅等价于「当前知识库」，前端先拿到完整交互。

验收：

```text
✓ 五个选项可切换并持久化到会话
✓ 未选择知识库时不再强制弹设置抽屉（smart/global 可用）
✓ 指定资料开关正确映射 strict / focused
```

### Phase C：ScopeResolver 真实解析 + 多库检索

实现：

```text
app/services/scope_resolver.py          完整 resolve()
app/services/ownership.py               resolve_owned_scope()
app/services/hybrid_retrieval.py        retrieve_scoped / 多库向量 + 多库 FTS + 全局 RRF
app/api/routes/search.py                /api/chat 接入 resolver
```

验收：

```text
✓ smart 起点为当前库，硬过滤正确
✓ global 覆盖全部个人库，且不越权
✓ 关键词召回与向量召回库集合一致
✓ RetrievalRun 写入 scope_snapshot / scope_resolution
```

### Phase D：范围扩展 + 知识点驱动

实现：

```text
扩展阶梯 + 预算熔断（13.3）
知识点 → 文档 / 知识库软先验
retrieval_runs.expansion_rounds / expanded_scope
```

验收：

```text
✓ 当前库 insufficient → 自动扩展并记录理由
✓ strict 永不扩展（含 insufficient 场景）
✓ 达到延迟预算后停止扩展且仍能作答
✓ Dashboard「继续学习知识点」入口无需选文件即可发起学习
```

### Phase E：画像驱动

实现：

```text
画像参与起点排序
画像 Bonus 进入 rerank（≤ 0.10）并落 retrieval_hits.profile_bonus
证据分级与画像解耦
```

验收：

```text
✓ 新手画像下 definition / intuition 排序高于 advanced_derivation
✓ 同一查询在画像变化前后 evidence_status 不变
✓ profile_bonus 可在审计中还原
```

---

## 16. 测试设计

### 16.1 新增测试文件

```text
backend/tests/test_retrieval_scope.py        范围解析与模式语义矩阵
backend/tests/test_scope_security.py         越权与 fail-closed
```

扩展：

```text
backend/tests/test_hybrid_retrieval.py       多库融合、分库归一、profile_bonus 不影响证据
backend/tests/test_chat_architecture.py      /api/chat 缺省 workspace 的新契约
backend/tests/test_phase_one_migrations.py   0005 迁移与回填
```

### 16.2 场景矩阵

| 场景 | 输入 | 期望 |
| --- | --- | --- |
| STRICT 文件 | `strict` + A.pdf，答案只在 B.pdf | 不返回 B；`expansion_rounds=0` |
| STRICT 知识库 | `strict` + Workspace A，A 中证据不足 | 不搜索 B；走模型兜底 |
| FOCUSED | `focused` + A.pdf，A 不足但同库有补充 | 扩展到 A 所在库并返回补充证据 |
| SMART | Workspace A 不足，B 有相关内容 | 扩展到全部个人库，`expanded_scope=true`，理由非空 |
| GLOBAL | 任意查询 | 全部个人库参与，融合后排序 |
| 无知识库 | `smart` + `workspace_id=null` | 退化为全局个人库，不报 400 |
| 越权 workspace | 伪造他人 `workspace_ids` | 剔除并记入 `dropped_ids`，不返回他人内容 |
| 越权 document | 伪造他人 `document_ids` | 同上，且不扩大范围 |
| 空范围 fail-closed | 全部 id 被剔除 | 返回空证据，不退化为「不过滤」 |
| 画像排序 | 新手 vs 进阶画像 | 顺序变化，`evidence_status` 不变 |
| 扩展预算 | 需要 3 轮才可能充分 | 最多 2 轮，随后作答 |
| 审计完整性 | 任意扩展 | `retrieval_runs` 含 scope 四字段且可解释 |

---

## 17. 反模式清单

```text
✗ 继续扩散 selected_document_ids 到新的服务签名
✗ 把 Workspace 当作硬编码的绝对边界
✗ 把 AI Learning 做成检索配置面板（Top-K / filter / collection 暴露给用户）
✗ 把画像写进证据、或让画像影响 evidence_status
✗ 跨库直接拼接 Top-K 而不做分数归一
✗ 一次性全库搜索（不做局部优先）
✗ strict 模式下自动扩展
✗ 迁移时把默认模式设为 smart
✗ 信任客户端传入的 workspace_ids / document_ids
```

---

## 18. 验收清单

```text
[ ] RetrievalScope / ResolvedRetrievalScope 类型落地并覆盖全部调用方
[ ] chat_sessions.scope_mode / scope_config 迁移完成，历史数据回填为 strict
[ ] ScopeResolver 支持四种模式，解析结果带可读理由
[ ] 多库向量 + 多库 FTS 库集合一致，融合前完成分库归一
[ ] 扩展受轮数与延迟预算约束，strict 永不扩展
[ ] 所有权收敛覆盖 workspace / document / knowledge_point，越权 fail-closed
[ ] retrieval_runs 记录 scope_mode / scope_snapshot / scope_resolution / expansion_rounds / expanded_scope
[ ] 画像 Bonus ≤ 0.10 且不影响证据分级
[ ] 前端仅暴露「学习范围」五选项，且无需强制选文件
[ ] DocumentDetail / KnowledgeBase / Dashboard 三个入口语义正确
[ ] 场景矩阵 12 项测试全部通过
[ ] 既有回归测试（chat / hybrid retrieval / profile / migrations）全绿
```

---

## 19. 附录

### 19.1 术语对照

| 用户可见 | 内部符号 | 存储 |
| --- | --- | --- |
| 学习范围 | `RetrievalScope` | `chat_sessions.scope_config` |
| 智能选择 | `mode="smart"` | `chat_sessions.scope_mode` |
| 当前知识库 | `mode="strict"` + `workspace_ids` | `scope_config` |
| 当前文件 | `mode="strict"` + `document_ids` | `scope_config` |
| 指定资料 | `mode="strict"` 或 `"focused"` | `scope_config` |
| 全部知识库 | `mode="global"` | `chat_sessions.scope_mode` |
| 本次实际搜索范围 | `ResolvedRetrievalScope` | `retrieval_runs.scope_resolution` |
| 为什么搜到这里 | `resolution_reason` / `reasons` | `retrieval_runs.scope_snapshot` |

### 19.2 一句话总结

> 让系统根据学习目标、当前知识点、用户画像与查询意图，自动决定**哪些私人知识应当参与这次学习**，同时保证用户一旦划定硬边界，系统绝不越界；并且每一次范围决策都能被解释和复现。

---

## 20. 实现状态（与代码对照）

本设计已按 Phase A–E 落地：

| 设计项 | 实现位置 |
| --- | --- |
| `RetrievalScope` / `ResolvedRetrievalScope` | `backend/app/schemas/scope.py` |
| `ChatSession.scope_mode` / `scope_config` | `backend/app/models/chat.py` + `alembic/versions/0005_learning_scope.py` |
| 检索审计字段 | `retrieval_runs.scope_mode / scope_snapshot / scope_resolution / expansion_rounds / expanded_scope`、`retrieval_hits.profile_bonus` |
| 所有权收敛 | `backend/app/services/ownership.py::resolve_owned_scope` |
| 范围解析与扩展 | `backend/app/services/scope_resolver.py`（`legacy_scope` / `scope_from_session` / `ScopeResolver.resolve` / `ScopeResolver.expand`） |
| 画像驱动软先验 | `ScopeResolver.profile_preferences` + `_with_profile`：薄弱点 → `preferred_knowledge_point_ids` / `preferred_document_ids` / 同集合内知识库排序，永不改动硬过滤 |
| 多库检索 + 分库归一 + 画像 Bonus | `backend/app/services/hybrid_retrieval.py`（`RetrievalRequest` / `retrieve_scoped` / `_normalize_within_collections` / `_profile_hint_bonus`） |
| 扩展策略（limited 只扩一轮、insufficient 扩到上限、轮数与延迟熔断） | `backend/app/services/scoped_retrieval.py::retrieve_with_expansion`，由 `search.py::chat` 调用 |
| 范围接口 | `GET/PATCH /api/chat/sessions/{id}/scope` |
| 审计查询接口 | `GET /api/chat/retrieval-runs/{run_id}` |
| 前端范围选择器 | `frontend/src/pages/learningScope.ts` + `frontend/src/components/learning/LearningModePanel.tsx` |
| 前端范围提示 | `learningScope.ts::scopeNoticeText` + `LearningChat.tsx` 头部标签（扩展/剔除时说明原因） |
| 前端会话与流式接入 | `frontend/src/pages/LearningChat.tsx`、`frontend/src/hooks/useChatSessions.ts`、`frontend/src/hooks/useStreamingChat.ts`、`frontend/src/services/api.ts` |
| 文档精读入口 | `frontend/src/pages/DocumentDetail.tsx`（`/learn?workspace=…&document_id=…&mode=simple` → `strict` + 单文档） |
| 知识库入口 | `frontend/src/pages/KnowledgeBase.tsx`（`/learn?workspace=…` → `smart`，以该库为起点） |

测试覆盖：

```text
backend/tests/test_retrieval_scope.py   模式语义、扩展阶梯、多库召回、画像 Bonus 不影响证据分级
backend/tests/test_scope_security.py    越权剔除、fail-closed、/api/chat 无知识库契约、scope 接口往返
backend/tests/test_scoped_retrieval.py  扩展预算：limited 只扩一轮、insufficient 扩到上限、轮数与延迟熔断
backend/tests/test_hybrid_retrieval.py  既有混合检索契约（回归）
backend/tests/test_chat_architecture.py scope_mode / scope_config / 范围审计列断言
backend/tests/test_phase_one_migrations.py  0005 迁移后的 strict 回填（文档优先、知识库兜底）
frontend/tests/learningScope.test.ts    前端选项 ↔ 范围映射与还原
```
