"""采集真实检索基线（RAG 重构阶段 0 的验收项）。

用法（仓库根目录）：

    .venv\\Scripts\\python.exe backend/scripts/collect_rag_baseline.py --reset

流程与约束：

1. 使用隔离的 `DATA_ROOT`（默认 `tmp/rag_baseline_home`）与内嵌 Chroma，不动真实数据库与向量库。
2. 语料来自 `backend/tests/rag_eval/corpus`，走真实链路：解析 → 分类 → 结构 → 切分 → 嵌入 → 索引。
   不 mock embedding；富化默认关闭，文档分类只走规则，全程不调用外部模型。
3. 每条用例用一个唯一的「答案短语」定位它实际落入的 chunk，写入 `cases.jsonl` 的
   `expected_chunk_ids`。短语命中 0 个或 1 个以上 chunk 都会直接报错，避免写进错误的标注。
4. 用生产混合召回计算 Recall@k / MRR / NDCG 并写入 `baseline.json`；阈值重标定在样本不足时
   由 `app.rag.eval.calibration` 自己拒绝，不产出建议值。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 两种布局都要能用：仓库里脚本在 <repo>/backend/scripts，容器里（Dockerfile 以 backend 为上下文）
# 脚本在 /app/scripts，因此后端根目录取父目录，仓库根目录再按目录名判断。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent if BACKEND_ROOT.name == "backend" else BACKEND_ROOT
CORPUS_DIR = BACKEND_ROOT / "tests" / "rag_eval" / "corpus"
EVAL_DIR = BACKEND_ROOT / "tests" / "rag_eval"

# 每条用例的答案短语必须唯一命中一个 child chunk；短语本身就是标注依据。
CASES: list[dict[str, str]] = [
    {"query": "什么是条件概率", "phrase": "为在事件 B 已经发生的条件下事件 A 发生的条件概率"},
    {"query": "全概率公式有什么用", "phrase": "按原因分解成若干互斥的情形"},
    {"query": "先验概率和后验概率是什么关系", "phrase": "从先验更新到后验"},
    {"query": "P(A|B) 和 P(B|A) 一样吗", "phrase": "混为一谈是最典型的错误"},
    {"query": "导数是怎么定义的", "phrase": "导数的定义是差商的极限"},
    {"query": "链式法则什么时候用", "phrase": "链式法则用于复合函数的求导"},
    {"query": "隐函数求导怎么做", "phrase": "方程两端同时对 x 求导"},
    {"query": "圆的方程怎么求导", "phrase": "x² + y² = r²"},
    {"query": "矩阵的秩怎么算", "phrase": "等于它的行阶梯形中非零行的个数"},
    {"query": "特征值怎么求", "phrase": "特征方程 det(A - λI) = 0"},
    {"query": "怎么判断向量组线性无关", "phrase": "全为零时"},
]


def configure_environment(data_root: Path) -> None:
    """必须在导入 app.* 之前调用：环境变量优先于仓库根目录的 .env。"""
    os.environ["DATA_ROOT"] = str(data_root)
    # .env 里是容器路径（/app/...），这里全部清空，让它按 DATA_ROOT 派生到隔离目录
    for key in ("DATABASE_URL", "UPLOAD_DIR", "MEDIA_DIR", "CHROMA_DIR"):
        os.environ[key] = ""
    os.environ["CHROMA_HOST"] = "local"  # 内嵌 Chroma，不连 docker 服务
    os.environ["RAG_ENRICH_ENABLED"] = "false"  # 富化会调用外部模型
    os.environ["RAG_DEBUG_ENDPOINT_ENABLED"] = "false"
    # 采集过程不调用任何外部模型：分类只走规则，其余节点没有模型可用时按设计降级。
    os.environ["DEFAULT_LLM_PROVIDER"] = "ollama"
    os.environ["DEFAULT_LLM_MODEL"] = "baseline-offline"
    os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"
    for key in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "ZHIPU_API_KEY"):
        os.environ[key] = ""
    # 本地模型已缓存时不再联网做版本探测：离线环境里那几次 HEAD 重试要等两分钟。
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    if cache.exists() and any(cache.glob("models--BAAI--bge-small-zh-v1.5*")):
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))


def reset_data_root(data_root: Path) -> None:
    resolved = data_root.resolve()
    if REPO_ROOT.resolve() not in resolved.parents:
        raise SystemExit(f"拒绝清理仓库之外的目录：{resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def ensure_data_dirs(settings) -> None:
    """RAG 主目录下的 sqlite / uploads / media / chroma 必须先建好。"""
    database_path = settings.DATABASE_URL.split("///", 1)[-1]
    for directory in (
        Path(database_path).parent,
        Path(settings.UPLOAD_DIR),
        Path(settings.MEDIA_DIR),
        Path(settings.CHROMA_DIR),
    ):
        directory.mkdir(parents=True, exist_ok=True)


async def ingest_corpus() -> str:
    """真实入库三份语料，返回 workspace_id。"""
    from app.collector.tasks import _build_pipeline
    from app.config import settings
    from app.models.base import Base, async_session_factory, engine
    from app.models.document import Document
    from app.models.user import User
    from app.models.workspace import Workspace

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    async with async_session_factory() as db:
        user = User(username="baseline", display_name="Baseline", password_hash=None, is_active=True)
        db.add(user)
        await db.flush()
        workspace = Workspace(owner_id=user.id, name="检索评测语料", slug="rag-eval-corpus")
        db.add(workspace)
        await db.commit()

        for path in sorted(CORPUS_DIR.glob("*.md")):
            target = upload_dir / f"{workspace.id}_{path.name}"
            shutil.copyfile(path, target)
            document = Document(
                workspace_id=workspace.id,
                filename=path.name,
                file_path=str(target),
                file_type="md",
                file_size=target.stat().st_size,
                status="pending",
            )
            db.add(document)
            await db.commit()
            summary = await _build_pipeline().process_document(
                document.id, str(target), "md", workspace.id, db,
            )
            print(f"  ingested {path.name}: {summary}")

    await engine.dispose()
    return workspace.id


async def load_child_chunks(workspace_id: str) -> list[dict[str, str]]:
    """读出真正进入向量的 child chunk，用于把答案短语解析成 chunk_id。"""
    from sqlalchemy import select

    from app.models.base import async_session_factory, engine
    from app.models.chat import DocumentChunk

    async with async_session_factory() as db:
        rows = (await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.workspace_id == workspace_id)
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )).scalars().all()
    await engine.dispose()
    return [
        {"chunk_id": row.id, "content": row.content or "", "content_type": row.content_type}
        for row in rows
        if row.chunk_level == "child"
    ]


def build_cases(workspace_id: str, chunks: list[dict[str, str]]) -> list[dict]:
    cases: list[dict] = []
    for entry in CASES:
        matches = [chunk for chunk in chunks if entry["phrase"] in chunk["content"]]
        if len(matches) != 1:
            raise SystemExit(
                f"短语未唯一命中 chunk（{len(matches)} 个）：{entry['query']} / {entry['phrase']}"
            )
        cases.append({
            "query": entry["query"],
            "workspace_id": workspace_id,
            "document_ids": [],
            "expected_chunk_ids": [matches[0]["chunk_id"]],
            "label_phrase": entry["phrase"],
        })
    return cases


async def collect_hits(cases: list[dict]) -> dict[str, list[dict]]:
    """用生产混合召回跑每条用例；单事件循环内完成，避免跨 loop 复用连接。"""
    from app.models.base import engine
    from app.rag.eval.runner import retrieve_for_case

    hits: dict[str, list[dict]] = {}
    for case in cases:
        hits[case["query"]] = await retrieve_for_case(case)
    await engine.dispose()
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集真实检索基线")
    parser.add_argument("--data-root", default=str(REPO_ROOT / "tmp" / "rag_baseline_home"))
    parser.add_argument("--reset", action="store_true", help="采集前清空隔离数据目录")
    parser.add_argument("--cases-out", default=str(EVAL_DIR / "cases.jsonl"))
    parser.add_argument("--baseline-out", default=str(EVAL_DIR / "baseline.json"))
    parser.add_argument("--thresholds-out", default=str(EVAL_DIR / "thresholds.json"))
    args = parser.parse_args(argv)

    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = REPO_ROOT / data_root
    if args.reset:
        reset_data_root(data_root)
    data_root.mkdir(parents=True, exist_ok=True)
    configure_environment(data_root)

    from app.config import settings
    from app.core.embedding import EmbeddingService, get_embedding_service
    from app.rag.chunking.base import MAX_CHUNK_TOKENS, MIN_CHUNK_TOKENS, TARGET_CHUNK_TOKENS
    from app.rag.eval.calibration import cases_from_retrieval, suggest_thresholds
    from app.rag.eval.metrics import evaluate

    print(f"DATA_ROOT={settings.DATA_ROOT}  chroma={settings.CHROMA_DIR}")
    ensure_data_dirs(settings)
    service = get_embedding_service()
    print(f"embedding provider={service.provider} model={service.model_name} window={service.max_input_tokens}")

    workspace_id = asyncio.run(ingest_corpus())
    chunks = asyncio.run(load_child_chunks(workspace_id))
    print(f"indexed child chunks: {len(chunks)}")
    cases = build_cases(workspace_id, chunks)
    hits = asyncio.run(collect_hits(cases))

    def retrieve(case: dict) -> list[dict]:
        return hits[case["query"]]

    report = evaluate(cases, retrieve)
    record = {
        "status": "recorded",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "corpus": "backend/tests/rag_eval/corpus/*.md（3 份为评测编写的中文笔记）",
            "cases": Path(args.cases_out).name,
            "labeling": "每条用例由唯一 answer phrase 定位到实际入库的 child chunk",
            "pipeline": "真实解析/分类/切分/嵌入/索引；富化关闭、分类只走规则、不调用外部模型",
            "embedding": {
                "provider": service.provider,
                "model": service.model_name,
                "window": service.max_input_tokens,
            },
            "chunking": {
                "min_tokens": MIN_CHUNK_TOKENS,
                "target_tokens": TARGET_CHUNK_TOKENS,
                "max_tokens": MAX_CHUNK_TOKENS,
            },
            "child_chunk_count": len(chunks),
        },
        "limitations": (
            "语料是为评测专门编写的 3 份中文笔记，检索难度低于真实资料；"
            "本轮数字只用于回归对比与机制验证，不代表生产检索质量。"
        ),
        **report,
    }

    cases_path = Path(args.cases_out)
    cases_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    Path(args.baseline_out).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"已写入 {cases_path} 与 {args.baseline_out}")

    suggestion = suggest_thresholds(cases_from_retrieval(cases, retrieve))
    if suggestion is None:
        print("阈值重标定：样本不足或标签单一，本轮不产出建议值（按设计拒绝）。")
    else:
        Path(args.thresholds_out).write_text(
            json.dumps({
                "supported": suggestion.supported,
                "second": suggestion.second,
                "limited": suggestion.limited,
                "precision": suggestion.precision,
                "recall": suggestion.recall,
                "f1": suggestion.f1,
                "cases": suggestion.cases,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"阈值建议已写入 {args.thresholds_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
