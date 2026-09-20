"""Document Classifier：规则优先、LLM 兜底、失败降级为 unstructured。

判定顺序与置信度门槛见设计文档 §7.2：规则命中且置信度 ≥ 0.8 直接采用；
否则调用一次 LLM（强制 JSON）；LLM 不可用或解析失败 → `unstructured`，
置信度 0，进入语义切分路径，绝不阻断入库。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal

from loguru import logger

from app.rag.contracts import Block

DocumentType = Literal[
    "textbook", "exam", "paper", "notes", "tutorial",
    "documentation", "slides", "qa", "code_document", "unstructured",
]

RULE_CONFIDENCE_THRESHOLD = 0.8
_TEXT_CAP = 8000

_CHAPTER_RE = re.compile(r"第\s*[0-9一二三四五六七八九十百千]+\s*[章节讲篇]|chapter\s+\d+", re.I)
_EXERCISE_RE = re.compile(r"习题|课后练习|练习题|exercises?\b", re.I)
_EXAM_ANSWER_RE = re.compile(r"参考答案|答案|解答|解析")
_EXAM_ITEM_RE = re.compile(r"大题|小题|选择题|填空题|判断题|简答题|计算题")
_PAPER_SECTIONS = ("abstract", "introduction", "method", "experiment", "conclusion", "references")
_QUESTION_RE = re.compile(r"^\s*(?:第?\s*\d+[.、)）]|例\s*\d+|question\s*\d+)", re.I)
_CODE_TYPES = frozenset({"json", "xml", "yaml", "yml"})


@dataclass
class ClassificationResult:
    document_type: DocumentType
    confidence: float
    reasons: list[str] = field(default_factory=list)
    source: Literal["rules", "llm", "fallback"] = "rules"

    @property
    def meta(self) -> dict:
        return {
            "document_type": self.document_type,
            "confidence": self.confidence,
            "reasons": list(self.reasons),
            "source": self.source,
        }


def _text_of(blocks: Iterable[Block]) -> str:
    parts: list[str] = []
    total = 0
    for block in blocks:
        text = block.text()
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= _TEXT_CAP:
            break
    return "\n".join(parts)


def _shape(blocks: list[Block]) -> dict:
    headings = [block for block in blocks if block.type == "heading"]
    return {
        "count": len(blocks),
        "headings": len(headings),
        "heading_levels": sorted(
            {block.heading_level for block in headings if block.heading_level}
        ),
        "code": sum(1 for block in blocks if block.type == "code"),
        "formula": sum(1 for block in blocks if block.type == "formula"),
        "table": sum(1 for block in blocks if block.type == "table"),
        "question": sum(1 for block in blocks if block.type == "question"),
    }


def classify_document(
    blocks: list[Block],
    *,
    file_type: str | None = None,
    filename: str | None = None,
    llm: Callable[[str], str] | None = None,
) -> ClassificationResult:
    """规则 → LLM → 降级；返回值始终可用。"""
    text = _text_of(blocks)
    shape = _shape(blocks)
    extension = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""

    if file_type == "pptx":
        return ClassificationResult("slides", 0.9, ["PPTX 文件按幻灯片结构处理"], "rules")
    if file_type in {"xlsx", "csv"}:
        return ClassificationResult("documentation", 0.9, ["表格类文件按资料处理"], "rules")
    if extension in _CODE_TYPES:
        return ClassificationResult("code_document", 0.85, [f"{extension} 属于结构化代码/配置文本"], "rules")

    if _EXAM_ANSWER_RE.search(text) and (_EXAM_ITEM_RE.search(text) or shape["question"]):
        return ClassificationResult("exam", 0.92, ["命中答案/解答词", "命中题目类型词"], "rules")
    if _CHAPTER_RE.search(text):
        # 设计文档 §7.2：出现「第X章 / 第X节 / 习题」即判为教材
        reasons = ["命中章节编号"]
        if _EXERCISE_RE.search(text):
            reasons.append("命中习题")
        return ClassificationResult("textbook", 0.9, reasons, "rules")
    paper_hits = [name for name in _PAPER_SECTIONS if re.search(rf"\b{name}\b", text, re.I)]
    if len(paper_hits) >= 2:
        return ClassificationResult("paper", 0.88, [f"命中论文结构词：{', '.join(paper_hits[:3])}"], "rules")
    if shape["headings"] >= 3:
        if shape["code"] >= 1:
            return ClassificationResult("tutorial", 0.82, ["多级标题 + 代码块，判定为教程"], "rules")
        return ClassificationResult("notes", 0.78, ["多级标题，判定为笔记"], "rules")
    if shape["question"] >= 2:
        return ClassificationResult("qa", 0.8, ["题干块数量达到阈值，判定为问答资料"], "rules")

    if llm is not None:
        result = _classify_with_llm(llm, text, shape)
        if result is not None:
            return result

    return ClassificationResult(
        "unstructured",
        0.0,
        ["规则未达到置信度阈值，且未取得可用的 LLM 判定"],
        "fallback",
    )


def _classify_with_llm(llm: Callable[[str], str], text: str, shape: dict) -> ClassificationResult | None:
    prompt = (
        "你是文档分类器。可选类型：textbook, exam, paper, notes, tutorial, documentation, "
        "slides, qa, code_document, unstructured。只输出 JSON："
        '{"document_type": "...", "confidence": 0.0-1.0, "reasons": ["..."]}\n'
        f"结构统计：{json.dumps(shape, ensure_ascii=False)}\n"
        f"正文节选：\n{text[:4000]}"
    )
    try:
        raw = llm(prompt) or ""
    except Exception as exc:
        logger.warning("Document classification LLM call failed: {}", exc)
        return None
    try:
        payload = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        document_type = str(payload.get("document_type") or "").strip()
        confidence = float(payload.get("confidence") or 0.0)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("Document classification LLM response was unusable: {}", exc)
        return None
    allowed = set(DocumentType.__args__)  # type: ignore[attr-defined]
    if document_type not in allowed:
        return None
    reasons = [str(reason) for reason in (payload.get("reasons") or [])][:5]
    return ClassificationResult(document_type, max(0.0, min(1.0, confidence)), reasons, "llm")
