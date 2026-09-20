"""Query Analyzer：确定性规则（零模型调用），输出意图、语言与检索线索。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

Intent = str  # concept | howto | compare | exercise | summary | lookup

_ZH_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_RE = re.compile(r"[A-Za-z]")

_INTENT_RULES: tuple[tuple[Intent, tuple[re.Pattern[str], ...]], ...] = (
    ("exercise", (
        re.compile(r"练习题?|习题|做题|答案|解答|求值|计算(?:题)?|solve|exercise", re.I),
    )),
    ("compare", (
        re.compile(r"区别|对比|差异|相比|vs\.?|difference|compare against", re.I),
    )),
    ("howto", (
        re.compile(r"怎么做|如何|怎么实现|步骤|流程|how\s+to|implement|build", re.I),
    )),
    ("summary", (
        re.compile(r"总结|概括|梳理|大纲|概述|summar(y|ize)|overview", re.I),
    )),
    ("concept", (
        re.compile(r"是什么|什么是|定义|含义|原理|what\s+is|defined?\s+as|meaning", re.I),
    )),
)

_FORMULA_RE = re.compile(r"公式|推导|证明|formula|derive|derivation|equation", re.I)
_CODE_RE = re.compile(r"代码|实现|示例|例子|code|snippet|example", re.I)


@dataclass
class QueryAnalysis:
    query: str
    intent: Intent = "lookup"
    language: str = "zh"           # zh | en | mixed
    entities: list[str] = field(default_factory=list)
    wants_formula: bool = False
    wants_code: bool = False
    reasons: list[str] = field(default_factory=list)


def detect_language(text: str) -> str:
    has_zh = bool(_ZH_RE.search(text))
    has_en = bool(_EN_RE.search(text))
    if has_zh and has_en:
        return "mixed"
    return "en" if has_en else "zh"


def extract_entities(text: str) -> list[str]:
    """轻量实体线索：拉丁术语、书名号 / 引号内短语、定义句主语。"""
    entities: list[str] = []
    for pattern in (
        re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]{1,}"),
        re.compile(r"《([^》]{1,40})》"),
        re.compile(r"[\"\u201c]([^\"\u201d]{1,40})[\"\u201d]"),
        re.compile(r"(?<![\u4e00-\u9fff])[\u4e00-\u9fff]{2,6}(?=是什么|的定义|是指)"),
    ):
        for match in pattern.finditer(text):
            value = (match.group(1) if match.groups() else match.group(0)).strip()
            if len(value) >= 2 and value not in entities:
                entities.append(value)
    return entities[:5]


def analyze_query(text: str) -> QueryAnalysis:
    query = (text or "").strip()
    analysis = QueryAnalysis(query=query, language=detect_language(query))
    for intent, patterns in _INTENT_RULES:
        if any(pattern.search(query) for pattern in patterns):
            analysis.intent = intent
            analysis.reasons.append(f"intent_rule:{intent}")
            break
    else:
        analysis.reasons.append("intent_rule:fallback_lookup")
    analysis.wants_formula = bool(_FORMULA_RE.search(query))
    analysis.wants_code = bool(_CODE_RE.search(query))
    analysis.entities = extract_entities(query)
    return analysis

