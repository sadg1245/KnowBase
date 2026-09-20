"""证据阈值重标定（§18.4）：用标注集把 supported / second / limited 拉回真实分布。

口径：对每个已标注查询，取检索 top-1 的 rerank 分数与「是否命中期望片段」，
在候选阈值上扫描，选 F1 最高者作为 `supported`；后两档沿用既有相对偏移
（-0.13 / -0.16），并夹在 [0, 1] 内。
"""

from __future__ import annotations

from dataclasses import dataclass, field

SECOND_OFFSET = 0.13
LIMITED_OFFSET = 0.16


@dataclass
class ThresholdSuggestion:
    supported: float
    second: float
    limited: float
    precision: float
    recall: float
    f1: float
    cases: int
    reasons: list[str] = field(default_factory=list)


def _scores(cases: list[dict]) -> list[float]:
    return sorted({float(case.get("top_score") or 0.0) for case in cases})


def suggest_thresholds(
    cases: list[dict],
    *,
    current_supported: float = 0.58,
    minimum_cases: int = 8,
) -> ThresholdSuggestion | None:
    """返回建议阈值；样本不足或全是单一标签时返回 None（不编造阈值）。"""
    labelled = [case for case in cases if "has_relevant" in case]
    positives = sum(1 for case in labelled if case.get("has_relevant"))
    if len(labelled) < minimum_cases:
        return None
    if positives == 0 or positives == len(labelled):
        return None

    best: tuple[float, float, float, float, float] | None = None
    for threshold in _scores(labelled):
        true_positive = false_positive = false_negative = 0
        for case in labelled:
            predicted = float(case.get("top_score") or 0.0) >= threshold
            actual = bool(case.get("has_relevant"))
            if predicted and actual:
                true_positive += 1
            elif predicted and not actual:
                false_positive += 1
            elif not predicted and actual:
                false_negative += 1
        precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
        recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        # 同分时选更接近当前默认值的阈值，避免无意义的抖动
        key = (round(f1, 6), -abs(threshold - current_supported))
        if best is None or key > (round(best[1], 6), -abs(best[0] - current_supported)):
            best = (threshold, f1, precision, recall, threshold)

    assert best is not None
    supported, f1, precision, recall = best[0], best[1], best[2], best[3]
    return ThresholdSuggestion(
        supported=round(supported, 4),
        second=round(max(0.0, supported - SECOND_OFFSET), 4),
        limited=round(max(0.0, supported - LIMITED_OFFSET), 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        cases=len(labelled),
        reasons=[
            f"标注用例 {len(labelled)} 条（正例 {positives}）",
            f"当前默认阈值 {current_supported}，F1 最优阈值 {round(supported, 4)}",
        ],
    )


def cases_from_retrieval(cases: list[dict], retrieve) -> list[dict]:
    """把标注用例跑成 `[(top_score, has_relevant)]` 形式，供 `suggest_thresholds` 使用。"""
    samples: list[dict] = []
    for case in cases:
        expected = set(case.get("expected_chunk_ids") or [])
        if not expected:
            continue
        hits = retrieve(case)
        top_score = float(hits[0]["score"]) if hits else 0.0
        samples.append({
            "query": case.get("query"),
            "top_score": top_score,
            "has_relevant": any(hit["chunk_id"] in expected for hit in hits[:5]),
        })
    return samples
