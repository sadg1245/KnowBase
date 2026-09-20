"""检索路由计划：意图 / 模式 → 向量种类、内容类型与重排策略。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.query.analyzer import QueryAnalysis

EXPLAIN_MODE = "explain"
PRACTICE_MODE = "practice"


@dataclass
class QueryPlan:
    analysis: QueryAnalysis
    mode: str = EXPLAIN_MODE
    vector_kinds: list[str] = field(default_factory=lambda: ["content"])
    exclude_content_types: list[str] = field(default_factory=list)
    prefer_content_types: list[str] = field(default_factory=list)
    rerank_mode: str = "local"
    expand_parents: bool = True
    reasons: list[str] = field(default_factory=list)


def plan_query(
    analysis: QueryAnalysis,
    *,
    mode: str = EXPLAIN_MODE,
    vector_kinds: list[str] | None = None,
    rerank_mode: str | None = None,
    expand_parents: bool = True,
) -> QueryPlan:
    plan = QueryPlan(
        analysis=analysis,
        mode=mode,
        vector_kinds=list(vector_kinds or ["content"]),
        rerank_mode=rerank_mode or "local",
        expand_parents=expand_parents,
    )
    if mode == PRACTICE_MODE:
        # §16：练习模式不返回答案与题解
        plan.exclude_content_types = ["answer", "solution"]
        plan.prefer_content_types = ["question", "definition", "formula"]
        plan.reasons.append("practice_mode_excludes_answers")
    if analysis.intent == "exercise":
        plan.prefer_content_types = list(dict.fromkeys([*plan.prefer_content_types, "question"]))
        plan.reasons.append("exercise_intent_prefers_question_chunks")
    if analysis.wants_formula:
        plan.prefer_content_types = list(dict.fromkeys([*plan.prefer_content_types, "formula"]))
        plan.reasons.append("formula_intent_prefers_formula_chunks")
    if analysis.wants_code:
        plan.prefer_content_types = list(dict.fromkeys([*plan.prefer_content_types, "code"]))
        plan.reasons.append("code_intent_prefers_code_chunks")
    if analysis.intent in {"concept", "summary", "compare"}:
        plan.vector_kinds = list(dict.fromkeys([*plan.vector_kinds, "summary", "question"]))
        plan.reasons.append("concept_intent_uses_multivector")
    return plan
