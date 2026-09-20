"""Context Builder（§19）：统一 [资料N] 编号、预算与去重。

输出格式与既有提示词完全一致，避免改动已验证的引用解析与来源导航。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.chunking.base import estimate_tokens

DEFAULT_CONTEXT_TOKEN_BUDGET = 6000


def _field(item, name: str, default=None):
    """同时支持 dict 与对象两种候选项（既有来源快照是 dict）。"""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


@dataclass
class ContextBlock:
    index: int
    chunk_id: str
    content: str
    source_file: str = ""
    page_num: int | None = None
    heading: str | None = None
    expanded_from: str | None = None
    tokens: int = 0
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        label = f"[资料{self.index}] 来源：{self.source_file or 'unknown'}"
        if self.page_num:
            label += f"，第 {self.page_num} 页"
        if self.heading:
            label += f"，章节：{self.heading}"
        return f"{label}\n{self.content}"


def build_context_blocks(
    items,
    *,
    token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> tuple[list[ContextBlock], list[str]]:
    """按顺序编号并裁剪到预算内；同一 chunk 只出现一次。"""
    blocks: list[ContextBlock] = []
    notes: list[str] = []
    used = 0
    seen: set[str] = set()
    for item in items:
        chunk_id = str(_field(item, "chunk_id", "") or "")
        if chunk_id and chunk_id in seen:
            notes.append(f"duplicate_chunk:{chunk_id}")
            continue
        content = str(_field(item, "content", "") or "").strip()
        if not content:
            continue
        tokens = estimate_tokens(content)
        if blocks and used + tokens > token_budget:
            notes.append(f"context_budget_exceeded:dropped:{chunk_id}")
            continue
        seen.add(chunk_id)
        used += tokens
        blocks.append(ContextBlock(
            index=int(_field(item, "citation_index", 0) or 0) or (len(blocks) + 1),
            chunk_id=chunk_id,
            content=content,
            source_file=str(_field(item, "source_file", "") or ""),
            page_num=_field(item, "page_num", None),
            heading=_field(item, "heading", None),
            expanded_from=_field(item, "expanded_from", None),
            tokens=tokens,
        ))
    return blocks, notes


def render_context(blocks: list[ContextBlock]) -> list[str]:
    return [block.render() for block in blocks]
