"""现有解析器的 Block 化适配 + 解析质量判定。

现有 `collector/parsers/*` 仍产出「章节级 chunk（content + metadata）」；这里把它
无损升级成 `Document`/`Block[]`，让切分、富化、索引共享同一结构。适配层不改变
任何已上线的召回行为，只是把结构与质量显式化。
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from app.rag.contracts import Block, Document, ParseQuality
from app.rag.parsers.blocks import derive_blocks, formula_density, push_heading

_MD_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")


def _leading_heading(content: str) -> tuple[int, str] | None:
    """从章节正文首行识别 Markdown 标题，补上解析器缺失的层级。"""
    for line in (content or "").splitlines():
        if not line.strip():
            continue
        match = _MD_HEADING_RE.match(line)
        if match:
            return len(match.group(1)), match.group(2)
        return None
    return None

# 每页可提取字符数的下限；低于该值时该页按「无文本」处理（扫描件判定）。
MIN_CHARS_PER_PAGE = 20
FORMULA_HEAVY_RATIO = 0.15


def _normalize_section_text(content: str, heading: str, level: int | None) -> str:
    """保证每个章节的首行标题都能成为 heading 块。"""
    text = content or ""
    if not heading:
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == heading:
            lines[index] = f"{'#' * max(1, level or 1)} {heading}"
            return "\n".join(lines)
        if stripped.lstrip("#").strip() == heading:
            return text
        break
    return f"{'#' * max(1, level or 1)} {heading}\n\n{text}"


def blocks_from_chunks(chunks: Sequence[dict[str, Any]], *, document_id: str) -> list[Block]:
    """把章节级 chunk 序列转换成连续编号的 Block 序列。"""
    blocks: list[Block] = []
    order = 0
    # 章节路径在 chunk 之间连续：Markdown 这类解析器只给出 heading，
    # 这里维护跨 chunk 的标题栈，保证子小节仍然带着父节路径。
    stack: list[tuple[int, str]] = []
    for chunk in chunks:
        meta = dict(chunk.get("metadata") or {})
        content = chunk.get("content") or ""
        if not content.strip():
            continue
        heading = str(meta.get("heading") or "").strip()
        level = meta.get("heading_level")
        try:
            level = int(level) if level is not None else None
        except (TypeError, ValueError):
            level = None
        if level is None:
            detected = _leading_heading(content)
            if detected and detected[1] == heading:
                level = detected[0]
        meta_path = [
            str(title) for title in (meta.get("section_path") or []) if str(title).strip()
        ]
        if meta_path:
            stack = [(index + 1, title) for index, title in enumerate(meta_path)]
        elif heading:
            push_heading(stack, level or 1, heading)
        section_path = [title for _, title in stack]
        page = meta.get("page_num")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        section = derive_blocks(
            _normalize_section_text(content, heading, level),
            document_id=document_id,
            start_order=order,
            page=page,
            heading=heading,
            heading_level=level,
            section_path=section_path,
        )
        blocks.extend(section)
        order += len(section)
    return blocks


def compute_quality(
    chunks: Sequence[dict[str, Any]], *, file_type: str, signature: str | None = None
) -> ParseQuality:
    """扫描件 / 公式密集 / 文件头不一致都必须留下可读记录。"""
    pages: set[int] = set()
    empty_pages = 0
    chars = 0
    for index, chunk in enumerate(chunks, 1):
        meta = dict(chunk.get("metadata") or {})
        page = meta.get("page_num") or index
        pages.add(int(page) if str(page).isdigit() else index)
        content = (chunk.get("content") or "").strip()
        chars += len(content)
        if not content:
            empty_pages += 1

    page_count = len(pages)
    text_ratio = (chars / page_count) if page_count else 0.0
    scanned = bool(page_count) and empty_pages == page_count
    quality = ParseQuality(
        scanned=scanned,
        formula_heavy=formula_density("\n".join(chunk.get("content") or "" for chunk in chunks))
        >= FORMULA_HEAVY_RATIO,
        page_count=page_count,
        empty_page_count=empty_pages,
        extractable_chars=chars,
        text_ratio=round(text_ratio, 2),
        signature=signature,
    )
    if scanned and file_type == "pdf":
        quality.degraded = "scanned_pdf"
        quality.notes.append("该文件为扫描件，当前未做 OCR，暂不参与检索。")
    elif scanned:
        quality.degraded = "empty_document"
        quality.notes.append("没有可提取的正文内容，已跳过索引。")
    if quality.formula_heavy:
        quality.notes.append("公式密集：富化阶段不做摘要压缩，避免改写公式语义。")
    if page_count and text_ratio < MIN_CHARS_PER_PAGE and not quality.degraded:
        quality.notes.append(
            f"每页可提取字符仅约 {round(text_ratio)} 个，可能是扫描件或图片型 PDF。"
        )
    return quality


def compute_quality_from_blocks(blocks: Sequence[Block], *, file_type: str) -> ParseQuality:
    """已经 Block 化的解析器（如 DOCX）用它计算质量：页数按 `page` 去重。"""
    pages = {block.page for block in blocks if block.page}
    text = "\n".join(block.text() for block in blocks)
    chars = len(text.strip())
    quality = ParseQuality(
        scanned=False,
        formula_heavy=formula_density(text) >= FORMULA_HEAVY_RATIO,
        page_count=len(pages) or (1 if blocks else 0),
        empty_page_count=0,
        extractable_chars=chars,
        text_ratio=round(chars / (len(pages) or 1), 2),
    )
    if not blocks:
        quality.degraded = "empty_document"
        quality.notes.append("没有可提取的正文内容，已跳过索引。")
    if quality.formula_heavy:
        quality.notes.append("公式密集：富化阶段不做摘要压缩，避免改写公式语义。")
    return quality


def document_from_blocks(
    blocks: Sequence[Block],
    *,
    document_id: str,
    workspace_id: str,
    filename: str,
    file_type: str,
    parser_name: str | None = None,
    signature: str | None = None,
    chunk_count: int = 0,
) -> Document:
    """用解析器直接产出的 Block 构造 `Document`。"""
    title = next(
        (block.content for block in blocks if block.type == "heading" and block.content.strip()),
        None,
    )
    quality = compute_quality_from_blocks(blocks, file_type=file_type)
    quality.signature = signature
    return Document(
        document_id=document_id,
        workspace_id=workspace_id,
        filename=filename,
        file_type=file_type,
        title=title,
        blocks=list(blocks),
        quality=quality,
        metadata={
            "parser": parser_name or "",
            "chunk_count": chunk_count,
            "block_count": len(blocks),
        },
    )


def parse_with_parser(
    parser,
    file_path: str,
    *,
    document_id: str,
    workspace_id: str,
    filename: str,
    file_type: str,
    signature: str | None = None,
) -> Document:
    """优先使用解析器的 Block 化入口，否则退回章节级 chunk 适配。"""
    if hasattr(parser, "parse_blocks"):
        blocks = parser.parse_blocks(file_path, document_id=document_id)
        return document_from_blocks(
            blocks,
            document_id=document_id,
            workspace_id=workspace_id,
            filename=filename,
            file_type=file_type,
            parser_name=type(parser).__name__,
            signature=signature,
        )
    from app.rag.parsers.native import native_blocks

    if file_type in {"txt", "csv", "xlsx", "html", "pptx"}:
        blocks = native_blocks(file_type, file_path, document_id=document_id)
        if blocks:
            return document_from_blocks(
                blocks,
                document_id=document_id,
                workspace_id=workspace_id,
                filename=filename,
                file_type=file_type,
                parser_name=f"{type(parser).__name__}+native",
                signature=signature,
            )
    chunks = parser.parse(file_path)
    return document_from_chunks(
        chunks,
        document_id=document_id,
        workspace_id=workspace_id,
        filename=filename,
        file_type=file_type,
        parser_name=type(parser).__name__,
        signature=signature,
    )


def document_from_chunks(
    chunks: Sequence[dict[str, Any]],
    *,
    document_id: str,
    workspace_id: str,
    filename: str,
    file_type: str,
    parser_name: str | None = None,
    signature: str | None = None,
) -> Document:
    """构造统一 `Document`：Block[] + 质量 + 来源元数据。"""
    blocks = blocks_from_chunks(chunks, document_id=document_id)
    title = next(
        (block.content for block in blocks if block.type == "heading" and block.content.strip()),
        None,
    )
    quality = compute_quality(chunks, file_type=file_type, signature=signature)
    return Document(
        document_id=document_id,
        workspace_id=workspace_id,
        filename=filename,
        file_type=file_type,
        title=title,
        blocks=blocks,
        quality=quality,
        metadata={
            "parser": parser_name or "",
            "chunk_count": len(chunks),
            "block_count": len(blocks),
        },
    )


def parse_document(
    parser,
    file_path: str,
    *,
    document_id: str,
    workspace_id: str,
    file_type: str,
    filename: str | None = None,
) -> Document:
    """直接用一个解析器实例产出 `Document`（测试与离线工具用）。"""
    from app.rag.parsers.factory import detect_signature

    return document_from_chunks(
        parser.parse(file_path),
        document_id=document_id,
        workspace_id=workspace_id,
        filename=filename or "",
        file_type=file_type,
        parser_name=type(parser).__name__,
        signature=detect_signature(file_path),
    )
