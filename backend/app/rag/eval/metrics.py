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
