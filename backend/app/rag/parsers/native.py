"""原生 Block 提取：CSV / XLSX / HTML / PPTX / TXT 的结构化入口。

这些格式的表格与标题在源文件里本来就是结构化的，直接从原文件读取可以避免
「先拍平成文本、再靠正则猜列」的信息损失。旧解析器的 `parse()` 保持不变，
由 `adapters.parse_with_parser()` 优先调用这里的实现。
"""

from __future__ import annotations

import csv
import os
from html.parser import HTMLParser
from typing import Any

from loguru import logger

from app.rag.contracts import Block
from app.rag.parsers.blocks import derive_blocks


class _BlockBuilder:
    """统一维护 block_id / order / section_path 的小工具。"""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        self.blocks: list[Block] = []
        self.headings: list[tuple[int, str]] = []

    def emit(self, block_type: str, content: str, *, page: int | None = None, **extra) -> None:
        text = (content or "").strip()
        if not text:
            return
        order = len(self.blocks)
        self.blocks.append(Block(
            block_id=f"{self.document_id}:b{order}",
            type=block_type,  # type: ignore[arg-type]
            content=text,
            order=order,
            page=page,
            section_path=[title for _, title in self.headings],
            **extra,
        ))

    def heading(self, level: int, title: str, *, page: int | None = None) -> None:
        self.headings[:] = [entry for entry in self.headings if entry[0] < level]
        self.headings.append((max(1, level), title))
        self.emit("heading", title, page=page, heading_level=max(1, level))


def _read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def text_blocks(file_path: str, *, document_id: str) -> list[Block]:
    source = _read_text(file_path)
    return derive_blocks(source, document_id=document_id)


def csv_blocks(file_path: str, *, document_id: str) -> list[Block]:
    """CSV：整表按单元格建模，空行与全空列被丢弃。"""
    builder = _BlockBuilder(document_id)
    source = _read_text(file_path)
    rows = [
        [cell.strip() for cell in row]
        for row in csv.reader(source.splitlines())
    ]
    rows = [row for row in rows if any(cell for cell in row)]
    if rows:
        builder.emit("table", "\n".join("| " + " | ".join(row) + " |" for row in rows), table=rows)
    return builder.blocks


def xlsx_blocks(file_path: str, *, document_id: str) -> list[Block]:
    """XLSX：每个工作表一个 heading + 一个 table 块。"""
    import openpyxl

    builder = _BlockBuilder(document_id)
    workbook = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        for sheet_index, sheet_name in enumerate(workbook.sheetnames, start=1):
            sheet = workbook[sheet_name]
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if cell is None else str(cell).strip() for cell in row]
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            builder.heading(1, str(sheet_name), page=sheet_index)
            builder.emit(
                "table",
                "\n".join("| " + " | ".join(row) + " |" for row in rows),
                page=sheet_index,
                table=rows,
            )
    finally:
        try:
            workbook.close()
        except Exception:  # pragma: no cover - 关闭失败不影响结果
            pass
    return builder.blocks


class _HtmlBlockParser(HTMLParser):
    _HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _SKIP = {"script", "style"}

    def __init__(self, builder: _BlockBuilder) -> None:
        super().__init__(convert_charrefs=True)
        self.builder = builder
        self._stack: list[str] = []
        self._buffer: list[str] = []
        self._table: list[list[str]] = []
        self._row: list[str] = []

    # ---- HTMLParser 接口 ------------------------------------------------
    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            self._stack.append("skip")
            return
        if tag == "tr" and self._table is not None:
            self._row = []
        self._stack.append(tag)
        if tag in self._HEADINGS or tag in {"p", "li", "pre", "blockquote", "td", "th"}:
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP:
            if self._stack:
                self._stack.pop()
            return
        text = " ".join("".join(self._buffer).split())
        if tag in self._HEADINGS:
            self.builder.heading(self._HEADINGS[tag], text)
        elif tag in {"p", "blockquote"}:
            self.builder.emit("quote" if tag == "blockquote" else "paragraph", text)
        elif tag == "li":
            self.builder.emit("list", text)
        elif tag == "pre":
            self.builder.emit("code", "".join(self._buffer).strip())
        elif tag in {"td", "th"} and text:
            self._row.append(text)
        elif tag == "tr" and self._row:
            self._table.append(self._row)
            self._row = []
        elif tag == "table":
            rows = [row for row in self._table if row]
            if rows:
                self.builder.emit(
                    "table",
                    "\n".join("| " + " | ".join(row) + " |" for row in rows),
                    table=rows,
                )
            self._table = []
        self._buffer = []
        if tag in self._stack:
            self._stack.remove(tag)

    def handle_data(self, data: str) -> None:
        if "skip" in self._stack:
            return
        self._buffer.append(data)


def html_blocks(file_path: str, *, document_id: str) -> list[Block]:
    builder = _BlockBuilder(document_id)
    parser = _HtmlBlockParser(builder)
    parser.feed(_read_text(file_path))
    parser.close()
    return builder.blocks


def pptx_blocks(file_path: str, *, document_id: str) -> list[Block]:
    """PPTX：幻灯片标题为 heading，正文段落与表格各自成块。"""
    from pptx import Presentation

    builder = _BlockBuilder(document_id)
    presentation = Presentation(file_path)
    for slide_index, slide in enumerate(presentation.slides, start=1):
        title_shape = slide.shapes.title
        if title_shape is not None and title_shape.has_text_frame:
            title = title_shape.text_frame.text.strip()
            if title:
                builder.heading(1, title, page=slide_index)
        for shape in slide.shapes:
            if shape is title_shape:
                continue
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [
                    [cell.text.strip() for cell in row.cells]
                    for row in shape.table.rows
                ]
                rows = [row for row in rows if any(row)]
                if rows:
                    builder.emit(
                        "table",
                        "\n".join("| " + " | ".join(row) + " |" for row in rows),
                        page=slide_index,
                        table=rows,
                    )
                continue
            if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                text = "".join(run.text for run in paragraph.runs).strip()
                if text:
                    builder.emit("paragraph", text, page=slide_index)
    return builder.blocks


NATIVE_BLOCK_PARSERS: dict[str, Any] = {
    "txt": text_blocks,
    "csv": csv_blocks,
    "xlsx": xlsx_blocks,
    "html": html_blocks,
    "pptx": pptx_blocks,
}


def native_blocks(file_type: str, file_path: str, *, document_id: str) -> list[Block] | None:
    """按类型返回原生 Block；没有专用实现时返回 None，由适配层回退。"""
    handler = NATIVE_BLOCK_PARSERS.get(file_type)
    if handler is None or not os.path.isfile(file_path):
        return None
    try:
        return handler(file_path, document_id=document_id)
    except Exception as exc:  # 解析失败不改变既有降级行为
        logger.warning("Native block parsing failed for '{}': {}", file_path, exc)
        return None
