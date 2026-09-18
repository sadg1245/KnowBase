# RAG 重构阶段 0：基线与安全网实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在改动 RAG 主链路之前建立可复现的检索质量基线，修掉已确认的缺陷，并给入库流水线装上阶段可观测性。

**Architecture:** 本阶段不动切分与检索算法，只做五件事：新增 `app.rag.eval` 评测包（指标 + 用例装载 + 离线运行器 + 基线记录）；把查询侧 embedding 统一到 `EmbeddingService`；把 Chroma collection 的距离度量固定为 cosine；让上传白名单与解析器工厂共用一份真相并删除遗留内联处理死代码；为入库增加 `document_pipeline_events` 阶段事件与 `documents.pipeline_stage`。

**Tech Stack:** Python 3.12、FastAPI 0.115、SQLAlchemy 2.0 async、Alembic、SQLite（aiosqlite）、ChromaDB、jieba、pytest + `unittest.IsolatedAsyncioTestCase`。

**Spec:** `docs/superpowers/specs/2026-09-18-rag-redesign-design.md`

## Global Constraints

- `POST /api/chat` 的 SSE 事件序列（`session → evidence → token* → sources → suggestions → done`）与 `sources` 字段（`content / source_file / page_num / score / document_id / heading / chunk_id`）不得改变（spec §2.3）。
- `documents.status` 取值必须保持 `pending | processing | ready | failed`；新阶段信息只写入新列 `pipeline_stage`（spec §2.3、§23.1）。
- 不引入任何新依赖：不引入 Qdrant、LangGraph、FlagEmbedding、OCR（spec §2.2）。
- 本阶段只允许修改一个预先存在的测试文件：`backend/tests/test_document_jobs.py`（删除对已删除函数的 patch）。其余预先存在的测试文件一律不得改动；本计划新建的测试文件可以自由迭代。
- 迁移必须可重复执行，`downgrade()` 只能删除本 revision 新增的结构（spec §25.1）。
- 不编造任何指标数字：评测基线必须由真实运行产生；没有可用数据时按 Task 1 Step 6 的规则如实标记。
- 测试命令（仓库根目录执行）：

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/<file> -q -p no:cacheprovider
```

`-p no:cacheprovider` 用于避开受限环境下 `.pytest_cache` 的写入警告。

## 阶段与计划映射

spec §27 把重构分为 6 个阶段，每个阶段独立可交付，因此每阶段一份计划：

| 计划文件 | 阶段 | 状态 |
|---|---|---|
| `docs/superpowers/plans/2026-09-18-rag-redesign-phase0.md` | 阶段 0 基线与安全网 | 本文件 |
| `docs/superpowers/plans/2026-09-18-rag-redesign-phase1.md` | 阶段 1 统一文档模型与解析层 | 阶段 0 完成后编写 |
| 阶段 2–5 | 结构/知识单元/切分、富化与多向量、查询理解与重排、学习场景与个性化 | 依次编写 |

---

## Task 1: 检索评测指标与用例装载

**Files:**
- Create: `backend/app/rag/__init__.py`
- Create: `backend/app/rag/eval/__init__.py`
- Create: `backend/app/rag/eval/metrics.py`
- Create: `backend/app/rag/eval/runner.py`
- Create: `backend/tests/rag_eval/cases.jsonl`
- Test: `backend/tests/test_rag_eval_metrics.py`

**Interfaces:**
- Consumes: 无（本任务是后续任务的基线依赖）
- Produces:
  - `recall_at_k(ranked_ids: Sequence[str], expected_ids: Iterable[str], k: int) -> float`
  - `reciprocal_rank(ranked_ids: Sequence[str], expected_ids: Iterable[str]) -> float`
  - `ndcg_at_k(ranked_ids: Sequence[str], expected_ids: Iterable[str], k: int) -> float`
  - `load_cases(path: str | Path) -> list[dict]`，每条用例为 `{"query": str, "workspace_id": str, "document_ids": list[str], "expected_chunk_ids": list[str]}`
  - `evaluate(cases: list[dict], retrieve: Callable[[dict], list[dict]], k_values: tuple[int, ...] = (5, 10)) -> dict`，返回 `{"cases": [...], "summary": {...}}`，其中 `retrieve(case)` 必须返回 `[{"chunk_id": str, ...}]`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_rag_eval_metrics.py`:

```python
"""Retrieval evaluation metrics, case loading, and aggregation."""

import json
import tempfile
import unittest
from pathlib import Path

from app.rag.eval.metrics import (
    evaluate,
    load_cases,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


class RetrievalMetricTests(unittest.TestCase):
    def test_recall_at_k_counts_expected_hits_inside_the_window(self):
        ranked = ["a", "b", "c", "d"]
        self.assertEqual(recall_at_k(ranked, ["b", "d"], 2), 0.5)
        self.assertEqual(recall_at_k(ranked, ["b", "d"], 4), 1.0)

    def test_recall_at_k_is_zero_without_expected_ids(self):
        self.assertEqual(recall_at_k(["a"], [], 5), 0.0)

    def test_reciprocal_rank_uses_the_first_relevant_position(self):
        self.assertEqual(reciprocal_rank(["x", "b", "y"], ["b"]), 0.5)
        self.assertEqual(reciprocal_rank(["x", "y"], ["b"]), 0.0)

    def test_ndcg_at_k_rewards_early_hits_and_normalizes_to_one(self):
        expected = ["a", "b"]
        self.assertAlmostEqual(ndcg_at_k(["a", "b"], expected, 10), 1.0)
        self.assertLess(ndcg_at_k(["c", "a", "b"], expected, 10), 1.0)
        self.assertGreater(ndcg_at_k(["a", "c"], expected, 10), 0.0)


class RetrievalEvaluationTests(unittest.TestCase):
    def test_evaluate_aggregates_per_case_rows_and_a_summary(self):
        cases = [
            {"query": "q1", "workspace_id": "w", "expected_chunk_ids": ["a"]},
            {"query": "q2", "workspace_id": "w", "expected_chunk_ids": ["z"]},
        ]
        rankings = {"q1": ["a", "b"], "q2": ["x", "y"]}

        def retrieve(case):
            return [{"chunk_id": chunk_id} for chunk_id in rankings[case["query"]]]

        report = evaluate(cases, retrieve)

        self.assertEqual([row["query"] for row in report["cases"]], ["q1", "q2"])
        self.assertEqual(report["cases"][0]["recall@5"], 1.0)
        self.assertEqual(report["cases"][1]["recall@5"], 0.0)
        self.assertAlmostEqual(report["summary"]["mrr"], 0.5)
        self.assertEqual(report["summary"]["case_count"], 2)

    def test_load_cases_reads_jsonl_and_defaults_document_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "query": "什么是条件概率",
                        "workspace_id": "ws-1",
                        "expected_chunk_ids": ["doc_1_chunk_0"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            cases = load_cases(path)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["query"], "什么是条件概率")
        self.assertEqual(cases[0]["document_ids"], [])

    def test_load_cases_reports_the_offending_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            path.write_text('{"query": "缺少 workspace"}\n', encoding="utf-8")

            with self.assertRaises(ValueError) as caught:
                load_cases(path)

        self.assertIn("line 1", str(caught.exception))
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_rag_eval_metrics.py -q -p no:cacheprovider
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.rag'`

- [ ] **Step 3: 写最小实现**

Create `backend/app/rag/__init__.py`:

```python
"""RAG 重构包：统一文档模型、结构分析、切分、检索与评测。"""
```

Create `backend/app/rag/eval/__init__.py`:

```python
"""检索质量评测：指标、用例装载与离线运行器。"""
```

Create `backend/app/rag/eval/metrics.py`:

```python
"""Retrieval quality metrics used by the RAG evaluation harness."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

REQUIRED_CASE_FIELDS = ("query", "workspace_id", "expected_chunk_ids")


def recall_at_k(ranked_ids: Sequence[str], expected_ids: Iterable[str], k: int) -> float:
    """Return the share of expected chunks that appear in the first *k* ranks."""
    expected = set(expected_ids)
    if not expected:
        return 0.0
    return len(expected.intersection(ranked_ids[:k])) / len(expected)


def reciprocal_rank(ranked_ids: Sequence[str], expected_ids: Iterable[str]) -> float:
    """Return 1/rank of the first relevant chunk, or 0.0 when nothing matches."""
    expected = set(expected_ids)
    for rank, chunk_id in enumerate(ranked_ids, 1):
        if chunk_id in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[str], expected_ids: Iterable[str], k: int) -> float:
    """Binary-gain NDCG@k over one ranking."""
    expected = set(expected_ids)
    if not expected:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked_ids[:k], 1)
        if chunk_id in expected
    )
    ideal_hits = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def load_cases(path: str | Path) -> list[dict]:
    """Load a JSONL evaluation set, validating required fields per line."""
    cases: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {number}: invalid JSON ({exc})") from exc
            missing = [field for field in REQUIRED_CASE_FIELDS if not case.get(field)]
            if missing:
                raise ValueError(f"line {number}: missing fields {', '.join(missing)}")
            case.setdefault("document_ids", [])
            cases.append(case)
    return cases


def evaluate(
    cases: list[dict],
    retrieve: Callable[[dict], list[dict]],
    k_values: tuple[int, ...] = (5, 10),
) -> dict:
    """Score every case and aggregate the metrics into a summary block."""
    rows: list[dict] = []
    for case in cases:
        ranked = [item["chunk_id"] for item in retrieve(case)]
        row: dict = {
            "query": case["query"],
            "workspace_id": case["workspace_id"],
            "expected_chunk_ids": list(case["expected_chunk_ids"]),
            "ranked_chunk_ids": ranked,
        }
        for k in k_values:
            row[f"recall@{k}"] = recall_at_k(ranked, case["expected_chunk_ids"], k)
        row["mrr"] = reciprocal_rank(ranked, case["expected_chunk_ids"])
        row["ndcg@10"] = ndcg_at_k(ranked, case["expected_chunk_ids"], 10)
        rows.append(row)

    divisor = len(rows) or 1
    summary = {
        "case_count": len(rows),
        "mrr": sum(row["mrr"] for row in rows) / divisor,
        "ndcg@10": sum(row["ndcg@10"] for row in rows) / divisor,
    }
    for k in k_values:
        summary[f"recall@{k}"] = sum(row[f"recall@{k}"] for row in rows) / divisor
    return {"cases": rows, "summary": summary}
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_rag_eval_metrics.py -q -p no:cacheprovider
```

Expected: PASS（6 passed）

- [ ] **Step 5: 写离线运行器**

Create `backend/app/rag/eval/runner.py`:

```python
"""Offline retrieval evaluation: label new cases and record the baseline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.rag.eval.metrics import evaluate, load_cases


async def retrieve_for_case(case: dict) -> list[dict]:
    """Run the production hybrid retrieval stack for one evaluation case."""
    from app.api.routes.search import _vector_recall
    from app.models.base import async_session_factory
    from app.services.hybrid_retrieval import HybridRetrievalService

    async with async_session_factory() as db:
        result = await HybridRetrievalService(db, _vector_recall).retrieve(
            query=case["query"],
            workspace_id=case["workspace_id"],
            document_ids=case.get("document_ids") or [],
            selected_top_k=20,
        )
        await db.commit()
    return [
        {
            "chunk_id": item.chunk_id,
            "score": round(item.rerank_score, 4),
            "source_file": item.source_file,
            "heading": item.heading,
        }
        for item in result.items
    ]


def run_sync(case: dict) -> list[dict]:
    return asyncio.run(retrieve_for_case(case))


def _command_label(args: argparse.Namespace) -> int:
    case = {
        "query": args.query,
        "workspace_id": args.workspace,
        "document_ids": args.document or [],
    }
    for rank, item in enumerate(run_sync(case), 1):
        print(
            f"{rank:>3}. {item['chunk_id']}  score={item['score']}  "
            f"{item['source_file']} / {item['heading']}"
        )
    print("把确认相关的 chunk_id 写进 cases.jsonl 的 expected_chunk_ids 字段。")
    return 0


def _command_run(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    if not cases:
        print("cases.jsonl 为空：先用 label 子命令标注用例。")
        return 2
    report = evaluate(cases, run_sync)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写入 {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.rag.eval.runner")
    sub = parser.add_subparsers(dest="command", required=True)

    label = sub.add_parser("label", help="打印某个查询的检索候选，便于人工标注")
    label.add_argument("--query", required=True)
    label.add_argument("--workspace", required=True)
    label.add_argument("--document", action="append")
    label.set_defaults(func=_command_label)

    run = sub.add_parser("run", help="对用例集计算 Recall@k / MRR / NDCG")
    run.add_argument("--cases", required=True)
    run.add_argument("--out")
    run.set_defaults(func=_command_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
```

Create `backend/tests/rag_eval/cases.jsonl`（`expected_chunk_ids` 在 Step 6 用 `label` 子命令补全）:

```jsonl
{"query": "什么是条件概率", "workspace_id": "REPLACE_WITH_WORKSPACE_ID", "document_ids": [], "expected_chunk_ids": []}
{"query": "隐函数求导怎么做", "workspace_id": "REPLACE_WITH_WORKSPACE_ID", "document_ids": [], "expected_chunk_ids": []}
```

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_rag_eval_metrics.py -q -p no:cacheprovider
```

Expected: PASS（runner 不影响单测结果）

- [ ] **Step 6: 采集并提交真实基线**

前提：本地存在一个含 `status=ready` 文档的知识库。用 `GET /api/workspaces` 或 sqlite 客户端取到真实 `workspace_id`，替换 `cases.jsonl` 里的 `REPLACE_WITH_WORKSPACE_ID`，然后逐条标注：

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m app.rag.eval.runner label --query "什么是条件概率" --workspace <真实知识库ID>
```

把返回列表里确实回答该问题的 `chunk_id` 写进 `expected_chunk_ids`（每条 1–2 个），再运行：

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m app.rag.eval.runner run --cases backend/tests/rag_eval/cases.jsonl --out backend/tests/rag_eval/baseline.json
```

提交生成的 `baseline.json`，它就是阶段 3/4 的对照基线。

若当前没有任何 `ready` 文档：**不要编造数字**。此时把 `baseline.json` 写成 `{"status": "no_ready_documents", "recorded_at": "<ISO8601>"}`，在提交信息里注明「基线待补」，并把这一状态报告给用户。

建议用 8–15 条覆盖不同意图的用例（概念解释、公式查询、题目检索、笔记检索），否则基线不具代表性。用例越少，阶段 4 的阈值重标定就越不可靠。

- [ ] **Step 7: 提交**

```bash
git add backend/app/rag/__init__.py backend/app/rag/eval backend/tests/test_rag_eval_metrics.py backend/tests/rag_eval
git commit -m "feat: add offline retrieval evaluation harness and record the baseline"
```

---

## Task 2: 统一查询与入库的 embedding 调用路径

**Files:**
- Modify: `backend/app/api/routes/search.py`
- Modify: `backend/app/core/embedding.py`
- Test: `backend/tests/test_embedding_path.py`

**Interfaces:**
- Consumes: `app.core.embedding.get_embedding_service() -> EmbeddingService`、`EmbeddingService.embed_query(text: str) -> list[float]`（已存在）
- Produces: `app.core.embedding.reset_embedding_service() -> None`；`app.api.routes.search` 不再导出 `_get_embedding_function`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_embedding_path.py`:

```python
"""The query path must use the same embedding service as ingestion."""

import unittest
from unittest.mock import patch

from app.core.embedding import get_embedding_service, reset_embedding_service


class EmbeddingSingletonTests(unittest.TestCase):
    def tearDown(self):
        reset_embedding_service()

    def test_get_embedding_service_returns_one_shared_instance(self):
        reset_embedding_service()
        self.assertIs(get_embedding_service(), get_embedding_service())

    def test_reset_embedding_service_forces_a_fresh_instance(self):
        reset_embedding_service()
        first = get_embedding_service()
        reset_embedding_service()
        self.assertIsNot(first, get_embedding_service())


class QueryEmbeddingPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_vector_recall_uses_the_shared_embedding_service(self):
        from app.api.routes import search as search_module

        self.assertFalse(
            hasattr(search_module, "_get_embedding_function"),
            "查询侧不应再自带一套 embedding 加载路径",
        )

        seen: list[str] = []

        class _Recorder:
            async def embed_query(self, text: str) -> list[float]:
                seen.append(text)
                return [0.1, 0.2, 0.3]

        class _Collection:
            def __init__(self) -> None:
                self.kwargs: dict = {}

            def query(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "ids": [["doc-1_chunk_0"]],
                    "documents": [["条件概率的定义"]],
                    "metadatas": [[{"doc_id": "doc-1", "source_file": "概率论.pdf"}]],
                    "distances": [[0.2]],
                }

        class _Client:
            def __init__(self) -> None:
                self.collection = _Collection()

            def get_collection(self, name: str):
                return self.collection

        client = _Client()
        with patch.object(search_module, "get_embedding_service", lambda: _Recorder()), patch.object(
            search_module, "_get_chroma_client", lambda: client
        ):
            rows = await search_module._vector_recall(
                query="条件概率", workspace_id="ws-1", document_ids=[], top_k=5
            )

        self.assertEqual(seen, ["条件概率"])
        self.assertEqual(client.collection.kwargs["query_embeddings"], [[0.1, 0.2, 0.3]])
        self.assertEqual(rows[0]["chunk_id"], "doc-1_chunk_0")
        self.assertEqual(rows[0]["score"], 0.8)
        self.assertEqual(rows[0]["document_id"], "doc-1")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_embedding_path.py -q -p no:cacheprovider
```

Expected: FAIL — `ImportError: cannot import name 'reset_embedding_service'`，且 `hasattr(search_module, "_get_embedding_function")` 仍为 True

- [ ] **Step 3: 写最小实现**

在 `backend/app/core/embedding.py` 的 `get_embedding_service()` 之后追加：

```python
def reset_embedding_service() -> None:
    """Drop the cached service so tests and settings changes can rebuild it."""
    global _embedding_service_instance
    _embedding_service_instance = None
```

修改 `backend/app/api/routes/search.py`：

1. 顶部导入区加入 `from app.core.embedding import get_embedding_service`。
2. 删除整个 `@lru_cache(maxsize=1) def _get_embedding_function():` 函数。
3. `from functools import lru_cache, partial` 改为 `from functools import partial`。
4. 把 `_vector_recall` 内的两行：

```python
    embed_fn = _get_embedding_function()
    query_embedding = embed_fn([query])[0]
```

替换为：

```python
    query_embedding = await get_embedding_service().embed_query(query)
```

`_vector_recall` 已是 `async def`，签名不变。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_embedding_path.py backend/tests/test_hybrid_retrieval.py backend/tests/test_source_navigation.py backend/tests/test_chat_policy.py -q -p no:cacheprovider
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/routes/search.py backend/app/core/embedding.py backend/tests/test_embedding_path.py
git commit -m "refactor: route query embedding through the shared embedding service"
```

---

## Task 3: Chroma collection 距离度量固定为 cosine

**Files:**
- Modify: `backend/app/core/vector_store.py`
- Test: `backend/tests/test_vector_store_space.py`

**Interfaces:**
- Consumes: `VectorStore(host: str = "local", port: int = 8000)`（已存在）
- Produces:
  - `COSINE_SPACE: str`（模块常量，值 `"cosine"`）
  - `describe_collection_space(collection) -> str | None`
  - `VectorStore(host="local", port=8000, client=None)`（新增可选注入口）
  - `VectorStore.describe_space(workspace_id: str) -> str | None`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_vector_store_space.py`:

```python
"""The vector collection must use cosine distance, matching the score math."""

import unittest

from app.core.vector_store import COSINE_SPACE, VectorStore, describe_collection_space


class _FakeCollection:
    def __init__(self, metadata=None) -> None:
        self.metadata = metadata or {}


class _FakeClient:
    def __init__(self) -> None:
        self.created: dict = {}
        self.collections: dict[str, _FakeCollection] = {}

    def get_or_create_collection(self, *, name, metadata=None):
        self.created[name] = metadata or {}
        collection = _FakeCollection(metadata or {})
        self.collections[name] = collection
        return collection

    def get_collection(self, *, name):
        return self.collections[name]


class VectorStoreSpaceTests(unittest.TestCase):
    def test_new_collections_declare_cosine_space(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        store.get_or_create_collection("ws-123")

        metadata = client.created["ws_ws_123"]
        self.assertEqual(metadata["hnsw:space"], COSINE_SPACE)
        self.assertEqual(metadata["workspace_id"], "ws-123")

    def test_describe_collection_space_reports_missing_configuration(self):
        self.assertIsNone(describe_collection_space(_FakeCollection()))
        self.assertEqual(
            describe_collection_space(_FakeCollection({"hnsw:space": "cosine"})),
            "cosine",
        )

    def test_describe_space_reads_the_live_collection(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        store.get_or_create_collection("ws-123")

        self.assertEqual(store.describe_space("ws-123"), "cosine")

    def test_injected_client_skips_chromadb_connection(self):
        client = _FakeClient()
        store = VectorStore(client=client)

        self.assertIs(store._client, client)
```

> `_FakeClient.get_or_create_collection` 只接受关键字参数，因此实现里必须用 `name=` / `metadata=` 关键字调用。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_vector_store_space.py -q -p no:cacheprovider
```

Expected: FAIL — `ImportError: cannot import name 'COSINE_SPACE'`

- [ ] **Step 3: 写最小实现**

在 `backend/app/core/vector_store.py` 的 `logger` 导入之后加：

```python
COSINE_SPACE = "cosine"


def describe_collection_space(collection) -> str | None:
    """Return the collection's HNSW space, or None when ChromaDB would default to l2."""
    metadata = getattr(collection, "metadata", None) or {}
    return metadata.get("hnsw:space")
```

把 `VectorStore.__init__` 改成：

```python
    def __init__(self, host: str = "local", port: int = 8000, client=None):
        self.host = host
        self.port = port
        self._client = client
        if self._client is None:
            self._connect()
```

`get_or_create_collection` 里的 metadata 改成：

```python
            collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={
                    "hnsw:space": COSINE_SPACE,
                    "workspace_id": workspace_id,
                    "created_at": time.time(),
                },
            )
```

在 `get_or_create_collection` 之后新增：

```python
    def describe_space(self, workspace_id: str) -> str | None:
        """Report the live HNSW space so legacy L2 collections can be detected."""
        collection = self._client.get_collection(name=self._get_collection_name(workspace_id))
        return describe_collection_space(collection)
```

**不要误以为存量数据会被修好**：已存在的 collection 不会因为这段改动变成 cosine，存量向量仍在 L2 下建立，要等阶段 3 的全量重建才切换。本任务只保证「新建即正确」并提供检测手段，请在提交信息里写明。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_vector_store_space.py backend/tests/test_content_filter.py backend/tests/test_local_app_mode.py -q -p no:cacheprovider
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/core/vector_store.py backend/tests/test_vector_store_space.py
git commit -m "fix: create chroma collections with cosine distance and expose space detection"
```

---

## Task 4: 上传白名单与解析器工厂共用一份真相

**Files:**
- Modify: `backend/app/collector/pipeline.py`
- Modify: `backend/app/api/routes/documents.py:28-55`
- Modify: `README.md`
- Test: `backend/tests/test_upload_extension_contract.py`

**Interfaces:**
- Consumes: `_FILE_TYPE_MAP: dict[str, str]`、`DocumentPipeline._get_parser(file_type: str) -> BaseParser`（已存在）
- Produces: `app.collector.pipeline.supported_file_types() -> set[str]`；`app.api.routes.documents.ALLOWED_EXTENSIONS` 改为派生值

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_upload_extension_contract.py`:

```python
"""Upload whitelist and parser factory must agree on supported file types."""

import unittest

from fastapi import HTTPException

from app.api.routes.documents import ALLOWED_EXTENSIONS, _validate_extension
from app.collector.pipeline import DocumentPipeline, supported_file_types
from app.collector.parsers.base import BaseParser


class UploadExtensionContractTests(unittest.TestCase):
    def test_whitelist_is_derived_from_the_parser_factory(self):
        self.assertEqual(
            ALLOWED_EXTENSIONS, {f".{name}" for name in supported_file_types()}
        )

    def test_every_allowed_extension_builds_a_parser(self):
        pipeline = DocumentPipeline(None, None, None)
        DocumentPipeline._PARSER_CACHE.clear()
        for extension in sorted(ALLOWED_EXTENSIONS):
            with self.subTest(extension=extension):
                parser = pipeline._get_parser(extension.lstrip("."))
                self.assertIsInstance(parser, BaseParser)

    def test_textual_markup_formats_reuse_text_parsers(self):
        pipeline = DocumentPipeline(None, None, None)
        DocumentPipeline._PARSER_CACHE.clear()
        for extension, expected in (
            (".rst", "MarkdownParser"),
            (".json", "_TxtParser"),
            (".xml", "_TxtParser"),
            (".yaml", "_TxtParser"),
            (".yml", "_TxtParser"),
        ):
            with self.subTest(extension=extension):
                parser = pipeline._get_parser(extension.lstrip("."))
                self.assertEqual(type(parser).__name__, expected)

    def test_doc_files_are_rejected_until_a_parser_exists(self):
        with self.assertRaises(HTTPException) as caught:
            _validate_extension("legacy.doc")
        self.assertEqual(caught.exception.status_code, 400)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_upload_extension_contract.py -q -p no:cacheprovider
```

Expected: FAIL — `ImportError: cannot import name 'supported_file_types'`

- [ ] **Step 3: 写最小实现**

在 `backend/app/collector/pipeline.py` 的 `_FILE_TYPE_MAP` 中，于 `"html": "html", "htm": "html",` 之后补：

```python
    "rst": "md",
    "json": "txt",
    "xml": "txt",
    "yaml": "txt",
    "yml": "txt",
```

在 `_FILE_TYPE_MAP` 之后新增：

```python
def supported_file_types() -> set[str]:
    """Return every file type the parser factory can handle.

    This is the single source of truth for the upload whitelist, so an
    extension can never be accepted for upload and then fail to parse.
    """
    return set(_FILE_TYPE_MAP)
```

在 `backend/app/api/routes/documents.py` 中，把硬编码的 `ALLOWED_EXTENSIONS` 集合（含上方注释）整体替换为：

```python
from app.collector.pipeline import supported_file_types

# 允许上传的文件扩展名：唯一来源是解析器工厂，避免"上传成功但解析必然失败"
ALLOWED_EXTENSIONS: set[str] = {f".{name}" for name in supported_file_types()}
```

在 `README.md` 中把「- 支持 9 种文档格式导入（PDF、DOCX、PPTX、Markdown、TXT、XLSX、CSV、HTML、DOC）」改成：

```markdown
- 支持 9 类文档格式导入（PDF、DOCX、PPTX、Markdown/RST、TXT、XLSX、CSV、HTML、JSON/XML/YAML）
```

`.doc` 的支持在阶段 1 引入 `DocParser` 后恢复；本阶段保持 400 拒绝，并在阶段 1 同步删除 `test_doc_files_are_rejected_until_a_parser_exists` 这条断言（届时改为断言 `.doc` 能构造出解析器）。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_upload_extension_contract.py backend/tests/test_phase_two_parsers.py backend/tests/test_document_management.py backend/tests/test_document_jobs.py -q -p no:cacheprovider
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/collector/pipeline.py backend/app/api/routes/documents.py README.md backend/tests/test_upload_extension_contract.py
git commit -m "fix: derive the upload whitelist from the parser factory"
```

---

## Task 5: 删除遗留内联处理死代码

**Files:**
- Modify: `backend/app/api/routes/documents.py`
- Modify: `backend/tests/test_document_jobs.py`
- Test: `backend/tests/test_upload_extension_contract.py`（追加用例）

**Interfaces:**
- Consumes: 无
- Produces: `app.api.routes.documents` 不再定义 `_process_document` / `_chunk_text`；`_extract_text(file_path: str, file_type: str) -> str` 继续存在

- [ ] **Step 1: 写失败的测试**

在 `backend/tests/test_upload_extension_contract.py` 末尾追加：

```python
class LegacyInlineProcessingTests(unittest.TestCase):
    def test_inline_processing_helpers_are_removed(self):
        from app.api.routes import documents

        self.assertFalse(hasattr(documents, "_process_document"))
        self.assertFalse(hasattr(documents, "_chunk_text"))

    def test_text_extraction_helper_is_kept_for_content_filtering(self):
        from app.api.routes import documents

        self.assertTrue(callable(documents._extract_text))
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_upload_extension_contract.py -q -p no:cacheprovider
```

Expected: FAIL on `test_inline_processing_helpers_are_removed`

- [ ] **Step 3: 删除死代码并修好既有测试**

1. 删除 `backend/app/api/routes/documents.py` 中的 `async def _process_document(...)` 整个函数（约 83–160 行）与 `def _chunk_text(...)` 整个函数（约 230–243 行），保留 `_extract_text`。
2. 删除后确认 `Settings`、`datetime`、`timezone` 等导入仍被其它函数使用；若有未使用导入一并清理。
3. 修改 `backend/tests/test_document_jobs.py`：
   - 第一处 `with patch(...), patch("app.api.routes.documents._process_document", new=AsyncMock()), patch(...)`（约 74–77 行）：删掉 `_process_document` 那一项，保留 `enqueue_document_processing` 与 `process_document_task.delay` 两个 patch。
   - 第二处（约 101–106 行）：删掉 `patch("app.api.routes.documents._process_document", new=AsyncMock(side_effect=AssertionError("inline processing is forbidden"))) as inline_processing,` 整项，以及后续对 `inline_processing` 的引用（若有）。
   - 该测试的 `response[0]["status"] == "failed"` 与错误信息含 `queue` 两条断言保持不变。
4. 不要改动其它断言。

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_upload_extension_contract.py backend/tests/test_document_jobs.py backend/tests/test_content_filter.py backend/tests/test_document_management.py -q -p no:cacheprovider
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/routes/documents.py backend/tests/test_document_jobs.py backend/tests/test_upload_extension_contract.py
git commit -m "chore: drop the unused inline document processing path"
```

---

## Task 6: 入库阶段事件与 pipeline_stage

**Files:**
- Create: `backend/app/models/pipeline.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/models/document.py`
- Create: `backend/alembic/versions/0004_rag_pipeline_events.py`
- Modify: `backend/app/collector/pipeline.py`
- Test: `backend/tests/test_pipeline_events.py`

**Interfaces:**
- Consumes: `DocumentPipeline.process_document(document_id, file_path, file_type, workspace_id, db_session) -> dict`（签名不变）
- Produces:
  - `DocumentPipelineEvent`（表 `document_pipeline_events`）：`id / document_id / node / status / detail / started_at / finished_at / duration_ms`
  - `Document.pipeline_stage: str | None`，取值 `parsing | chunking | embedding | indexing | ready | failed`
  - `process_document()` 在四个节点各写一条事件；成功把 `pipeline_stage` 置 `ready`，失败置 `failed`

- [ ] **Step 1: 写失败的测试**

Create `backend/tests/test_pipeline_events.py`:

```python
"""Every ingestion stage must leave a durable, ordered audit row."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.collector.pipeline import DocumentPipeline
from app.core.migrations import run_compat_migrations
from app.models.base import Base
from app.models.document import Document
from app.models.pipeline import DocumentPipelineEvent
from tests.support import create_user, create_workspace


class _FakeEmbedding:
    async def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FailingEmbedding:
    async def embed_texts(self, texts):
        raise RuntimeError("embedding offline")


class _FakeVectorStore:
    def __init__(self) -> None:
        self.calls = 0

    async def replace_document(self, **_kwargs):
        self.calls += 1


class _PassThroughSplitter:
    def split_documents(self, documents):
        return [
            {"content": doc["content"], "metadata": dict(doc.get("metadata") or {})}
            for doc in documents
        ]


class PipelineEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await run_compat_migrations(conn)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.tmp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        self.tmp.cleanup()
        await self.engine.dispose()

    async def _seed_document(self, path: str) -> tuple[str, str]:
        async with self.sessions() as db:
            user = await create_user(db)
            workspace = await create_workspace(db, user, name="流水线", slug="pipeline-events")
            document = Document(
                workspace_id=workspace.id,
                filename="notes.txt",
                file_path=path,
                file_type="txt",
                status="pending",
            )
            db.add(document)
            await db.commit()
            return document.id, workspace.id

    async def _events(self, document_id: str):
        async with self.sessions() as db:
            return (
                await db.execute(
                    select(DocumentPipelineEvent)
                    .where(DocumentPipelineEvent.document_id == document_id)
                    .order_by(DocumentPipelineEvent.started_at)
                )
            ).scalars().all()

    async def _document(self, document_id: str) -> Document:
        async with self.sessions() as db:
            return (
                await db.execute(select(Document).where(Document.id == document_id))
            ).scalar_one()

    async def test_successful_run_records_four_ordered_nodes_and_stage(self):
        path = str(Path(self.tmp.name) / "notes.txt")
        Path(path).write_text("条件概率的定义与公式。\n\n贝叶斯定理。", encoding="utf-8")
        document_id, workspace_id = await self._seed_document(path)
        vector_store = _FakeVectorStore()
        pipeline = DocumentPipeline(_FakeEmbedding(), vector_store, _PassThroughSplitter())

        async with self.sessions() as db:
            result = await pipeline.process_document(document_id, path, "txt", workspace_id, db)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(vector_store.calls, 1)

        events = await self._events(document_id)
        document = await self._document(document_id)

        self.assertEqual(
            [event.node for event in events],
            ["parsing", "chunking", "embedding", "indexing"],
        )
        self.assertTrue(all(event.status == "succeeded" for event in events))
        self.assertTrue(all(event.finished_at is not None for event in events))
        self.assertTrue(all((event.duration_ms or 0) >= 0 for event in events))
        self.assertEqual(document.pipeline_stage, "ready")

    async def test_embedding_failure_records_a_failed_event_and_stage(self):
        path = str(Path(self.tmp.name) / "broken.txt")
        Path(path).write_text("任意内容", encoding="utf-8")
        document_id, workspace_id = await self._seed_document(path)
        pipeline = DocumentPipeline(
            _FailingEmbedding(), _FakeVectorStore(), _PassThroughSplitter()
        )

        async with self.sessions() as db:
            result = await pipeline.process_document(document_id, path, "txt", workspace_id, db)

        self.assertEqual(result["status"], "failed")

        events = await self._events(document_id)
        document = await self._document(document_id)

        self.assertEqual([event.node for event in events], ["parsing", "chunking", "embedding"])
        self.assertEqual(events[-1].status, "failed")
        self.assertIn("embedding offline", events[-1].detail)
        self.assertEqual(document.pipeline_stage, "failed")
        self.assertEqual(document.status, "failed")
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_pipeline_events.py -q -p no:cacheprovider
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.pipeline'`

- [ ] **Step 3: 新增模型**

Create `backend/app/models/pipeline.py`:

```python
"""Per-stage ingestion audit rows."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentPipelineEvent(Base):
    __tablename__ = "document_pipeline_events"

    id = Column(String(36), primary_key=True, default=_uuid)
    document_id = Column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    detail = Column(Text, nullable=True)
    started_at = Column(
        DateTime(timezone=True), nullable=False, default=_now, server_default=func.now()
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_document_pipeline_events_document_node", "document_id", "node"),
    )
```

在 `backend/app/models/__init__.py` 增加导入与 `__all__` 条目：

```python
from app.models.pipeline import DocumentPipelineEvent
```

```python
    "DocumentPipelineEvent",
```

在 `backend/app/models/document.py` 的 `status` 列之后新增：

```python
    pipeline_stage = Column(String(20), nullable=True)
```

- [ ] **Step 4: 写迁移**

Create `backend/alembic/versions/0004_rag_pipeline_events.py`:

```python
"""入库阶段事件与文档阶段列。

Revision ID: 0004_rag_pipeline_events
Revises: 0003_ai_tutor_memory
Create Date: 2026-09-18

迁移内容：
1. `documents` 增加可空 `pipeline_stage`。
2. 新建 `document_pipeline_events` 表与索引。

降级删除本 revision 新增的结构；不触碰既有数据。
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_rag_pipeline_events"
down_revision = "0003_ai_tutor_memory"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    document_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")
    }
    if "pipeline_stage" not in document_columns:
        op.add_column("documents", sa.Column("pipeline_stage", sa.String(20), nullable=True))

    if "document_pipeline_events" not in _table_names():
        op.create_table(
            "document_pipeline_events",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("document_id", sa.String(36), nullable=False),
            sa.Column("node", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_document_pipeline_events_document_id",
            "document_pipeline_events",
            ["document_id"],
        )
        op.create_index(
            "ix_document_pipeline_events_document_node",
            "document_pipeline_events",
            ["document_id", "node"],
        )


def downgrade() -> None:
    if "document_pipeline_events" in _table_names():
        op.drop_table("document_pipeline_events")
    document_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("documents")
    }
    if "pipeline_stage" in document_columns:
        op.drop_column("documents", "pipeline_stage")
```

- [ ] **Step 5: 在流水线里记录阶段**

在 `backend/app/collector/pipeline.py` 顶部补充导入（`datetime` / `timezone` 若已存在则不要重复）：

```python
import time
from contextlib import asynccontextmanager
```

在 `DocumentPipeline` 类内新增：

```python
    @asynccontextmanager
    async def _stage(self, db_session: Any, document_id: str, node: str):
        """Record one ingestion node as a durable audit row."""
        from app.models.pipeline import DocumentPipelineEvent

        started = time.perf_counter()
        event = DocumentPipelineEvent(
            document_id=document_id, node=node, status="started"
        )
        db_session.add(event)
        await db_session.flush()
        try:
            yield
        except Exception as exc:
            event.status = "failed"
            event.detail = str(exc)[:1000]
            raise
        else:
            event.status = "succeeded"
        finally:
            event.finished_at = datetime.now(timezone.utc)
            event.duration_ms = int((time.perf_counter() - started) * 1000)
            await db_session.flush()
```

把 `process_document` 的四个步骤用 `_stage` 包起来，每步同时把阶段写入文档：

```python
            async with self._stage(db_session, document_id, "parsing"):
                await self._update_document_status(
                    db_session, document_id, pipeline_stage="parsing"
                )
                parser = self._get_parser(file_type)
                raw_chunks = parser.parse(file_path)
                parsed_count = len(raw_chunks)
                raw_chunks = filter_learning_content(raw_chunks)

            async with self._stage(db_session, document_id, "chunking"):
                await self._update_document_status(
                    db_session, document_id, pipeline_stage="chunking"
                )
                split_chunks = self.text_splitter.split_documents(raw_chunks)

            async with self._stage(db_session, document_id, "embedding"):
                await self._update_document_status(
                    db_session, document_id, pipeline_stage="embedding"
                )
                texts = [chunk["content"] for chunk in split_chunks]
                embeddings = await self.embedding_service.embed_texts(texts)

            async with self._stage(db_session, document_id, "indexing"):
                await self._update_document_status(
                    db_session, document_id, pipeline_stage="indexing"
                )
                await self.vector_store.replace_document(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    doc_ids=doc_ids,
                    texts=texts,
                    embeddings=embeddings,
                    metadatas=metadatas,
                )
                await upsert_document_chunks(
                    db_session, workspace_id, document_id, original_filename, split_chunks
                )
```

保留原有的 `logger` 调用、`metadatas` / `doc_ids` 构造与空 chunk 提前返回分支（空 chunk 返回也必须在 `parsing` 阶段内完成）。

两条出口分别写入终态：

```python
            await self._update_document_status(
                db_session,
                document_id,
                status="ready",
                pipeline_stage="ready",
                chunk_count=len(split_chunks),
                error_message=None,
                processed_at=datetime.now(timezone.utc),
            )
```

```python
            await self._update_document_status(
                db_session,
                document_id,
                status="failed",
                pipeline_stage="failed",
                error_message=str(exc),
            )
```

**关键约束**：`_stage` 只用 `flush()`，不 `commit()`；因为 `_update_document_status` 内部会 `commit()`。同一 session 才能保证事件与阶段状态一起落库。

- [ ] **Step 6: 运行相关测试**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests/test_pipeline_events.py backend/tests/test_document_jobs.py backend/tests/test_content_filter.py backend/tests/test_phase_two_parsers.py backend/tests/test_regressions.py backend/tests/test_phase_one_migrations.py -q -p no:cacheprovider
```

Expected: PASS

- [ ] **Step 7: 跑全量后端测试**

Run:

```powershell
$env:PYTHONPATH="backend"; & ".\.venv\Scripts\python.exe" -m pytest backend/tests -q -p no:cacheprovider
```

Expected: PASS（通过数不少于阶段 0 开始前的数量）

- [ ] **Step 8: 提交**

```bash
git add backend/app/models/pipeline.py backend/app/models/__init__.py backend/app/models/document.py backend/alembic/versions/0004_rag_pipeline_events.py backend/app/collector/pipeline.py backend/tests/test_pipeline_events.py
git commit -m "feat: record per-stage ingestion events and document pipeline stage"
```

---

## 阶段 0 完成判据

- [ ] `backend/tests/rag_eval/baseline.json` 存在，数字来自真实运行（或如实标记 `no_ready_documents`），用例数 ≥ 8。
- [ ] 查询侧只有一条 embedding 路径，`_get_embedding_function` 已删除并有测试断言其不存在。
- [ ] 新建 Chroma collection 声明 `hnsw:space=cosine`，并提供存量 collection 检测能力。
- [ ] `ALLOWED_EXTENSIONS` 与解析器工厂严格相等，且每个允许扩展名都能构造出解析器。
- [ ] `_process_document` / `_chunk_text` 已删除，`_extract_text` 保留。
- [ ] 每次入库写满四个阶段事件，`documents.pipeline_stage` 落到 `ready` / `failed`。
- [ ] 全量后端测试通过。
- [ ] 阶段 0 完成后编写 `2026-09-18-rag-redesign-phase1.md`（spec §27 阶段 1）。
