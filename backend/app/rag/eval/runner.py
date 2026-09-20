"""Offline retrieval evaluation: label new cases and record the baseline."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.rag.eval.metrics import evaluate, load_cases
from app.rag.eval.calibration import cases_from_retrieval, suggest_thresholds


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


def _command_calibrate(args: argparse.Namespace) -> int:
    """用标注集给出 supported / second / limited 的建议值（样本不足则明确拒绝）。"""
    cases = load_cases(args.cases)
    if not cases:
        print("cases.jsonl 为空：先用 label 子命令标注用例。")
        return 2
    samples = cases_from_retrieval(cases, run_sync)
    suggestion = suggest_thresholds(samples)
    if suggestion is None:
        print(
            "样本不足或标签单一：重标定需要 >= 8 条同时包含正例与负例的用例，"
            "本轮不做任何阈值建议。"
        )
        return 2
    print(json.dumps({
        "supported": suggestion.supported,
        "second": suggestion.second,
        "limited": suggestion.limited,
        "precision": suggestion.precision,
        "recall": suggestion.recall,
        "f1": suggestion.f1,
        "cases": suggestion.cases,
        "reasons": suggestion.reasons,
    }, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(
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

    calibrate = sub.add_parser("calibrate", help="用标注集给出证据阈值建议")
    calibrate.add_argument("--cases", required=True)
    calibrate.add_argument("--out")
    calibrate.set_defaults(func=_command_calibrate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
