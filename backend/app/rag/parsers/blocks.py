"""Block 构建工具：把解析出的文本切成标题 / 段落 / 列表 / 代码 / 公式 / 表格。

这些规则刻意保持确定性（正则 + 状态机），因此同一份输入永远产出同样的 Block 序列，
可以被单测与切分层稳定依赖。
"""

from __future__ import annotations

import re

from app.rag.contracts import Block

_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*```([^\s`]*)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
_QUOTE_RE = re.compile(r"^\s*>\s?")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_FORMULA_MARKERS = (
    re.compile(r"\$\$?"),
    re.compile(r"\\\(|\\\)"),
    re.compile(r"\\begin\{"),
    re.compile(r"\\(frac|sum|int|partial|alpha|beta|theta|lambda|sqrt|cdot|times)\b"),
)


def is_formula_line(line: str) -> bool:
    """判断一行是否是公式（$...$ / \\(...\\) / \\begin{...} / 常见 LaTeX 命令）。"""
    text = line.strip()
    if len(text) < 3:
        return False
    return any(marker.search(text) for marker in _FORMULA_MARKERS)


def formula_density(text: str) -> float:
    """公式行占比（0..1）；用于 PDF 的 formula_heavy 判定。"""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return 0.0
    return sum(1 for line in lines if is_formula_line(line)) / len(lines)


def to_latex(line: str) -> str:
    """把公式行归一化成 latex 片段（去掉行内 $ 包裹）。"""
    text = line.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        return text[2:-2].strip()
    if text.startswith("$") and text.endswith("$") and len(text) > 2:
        return text[1:-1].strip()
    if text.startswith(r"\(") and text.endswith(r"\)"):
        return text[2:-2].strip()
    return text


def parse_table_rows(lines: list[str]) -> list[list[str]]:
    """把管道符表格行解析成二维数组。"""
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":", " "} and cell for cell in cells):
            continue  # 分隔行（| --- | --- |）
        rows.append(cells)
    return rows


def table_content(rows: list[list[str]]) -> str:
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def push_heading(stack: list[tuple[int, str]], level: int, title: str) -> list[str]:
    """维护标题栈并返回当前小节路径。"""
    stack[:] = [entry for entry in stack if entry[0] < level]
    stack.append((max(1, level), title))
    return [entry_title for _, entry_title in stack]


def derive_blocks(
    content: str,
    *,
    document_id: str,
    start_order: int = 0,
    page: int | None = None,
    heading: str = "",
    heading_level: int | None = None,
    section_path: list[str] | None = None,
    split_paragraphs: bool = True,
) -> list[Block]:
    """把一段解析文本切成结构化 Block。

    规则：围栏代码、连续管道表格、引用、有序/无序列表、公式行各自成块，
    Markdown 标题更新小节路径，其余按空行分段的正文为 paragraph。
    """
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = [
        (index + 1, title)
        for index, title in enumerate(section_path or ([heading] if heading else []))
        if title
    ]
    current_path = [title for _, title in stack]
    order = start_order

    def emit(block_type: str, text: str, **extra) -> None:
        nonlocal order
        blocks.append(
            Block(
                block_id=f"{document_id}:b{order}",
                type=block_type,  # type: ignore[arg-type]
                content=text.strip(),
                order=order,
                page=page,
                section_path=list(current_path),
                **extra,
            )
        )
        order += 1

    lines = content.splitlines()
    index = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if not paragraph:
            return
        text = "\n".join(paragraph).strip()
        paragraph = []
        if not text:
            return
        if split_paragraphs:
            for part in [piece.strip() for piece in re.split(r"\n\s*\n", text) if piece.strip()]:
                emit("paragraph", part)
        else:
            emit("paragraph", text)

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        fence = _CODE_FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            language = fence.group(1) or None
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not _CODE_FENCE_RE.match(lines[index]):
                code_lines.append(lines[index])
                index += 1
            index += 1  # 跳过闭合围栏
            if code_lines:
                emit("code", "\n".join(code_lines), language=language)
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        markdown_heading = _HEADING_RE.match(line)
        if markdown_heading:
            flush_paragraph()
            level = len(markdown_heading.group(1))
            title = markdown_heading.group(2)
            current_path = push_heading(stack, level, title)
            emit("heading", title, heading_level=level)
            index += 1
            continue

        if _TABLE_ROW_RE.match(line):
            flush_paragraph()
            rows_lines = [line]
            index += 1
            while index < len(lines) and _TABLE_ROW_RE.match(lines[index]):
                rows_lines.append(lines[index])
                index += 1
            rows = parse_table_rows(rows_lines)
            if rows:
                emit("table", table_content(rows), table=rows)
            continue

        if _QUOTE_RE.match(line):
            flush_paragraph()
            quote_lines: list[str] = []
            while index < len(lines) and _QUOTE_RE.match(lines[index]):
                quote_lines.append(_QUOTE_RE.sub("", lines[index]).strip())
                index += 1
            emit("quote", "\n".join(quote_lines))
            continue

        if is_formula_line(line):
            flush_paragraph()
            emit("formula", stripped, latex=to_latex(stripped))
            index += 1
            continue

        if _LIST_RE.match(line):
            flush_paragraph()
            items: list[str] = []
            while index < len(lines) and _LIST_RE.match(lines[index]):
                items.append(lines[index].strip())
                index += 1
            emit("list", "\n".join(items))
            continue

        paragraph.append(line)
        index += 1

    flush_paragraph()
    return blocks
