"""使用 PyMuPDF (fitz) 的 PDF 解析器，用于 KnowBase 采集器流水线。"""

import os
from typing import Any

from loguru import logger

from .base import BaseParser


class PDFParser(BaseParser):
    """使用 PyMuPDF 逐页解析 PDF 文件。

    功能特性：
    - 将每页文本提取为独立的文档块。
    - 读取 PDF 目录（书签）并将页码映射到标题字符串，
      使每个块携带最近的章节标题。
    - 检测扫描版 PDF（无可提取文本）并在元数据中记录警告，
      以便下游阶段路由到 OCR。
    - 原生支持中文文本（PyMuPDF 返回 UTF-8 字符串）。
    - 始终关闭底层的 ``fitz.Document`` 以释放文件句柄。
    """

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        """解析 PDF 文件并返回每页一个块。

        参数
        ----------
        file_path : str
            ``.pdf`` 文件的路径。

        返回
        -------
        list[dict]
            每个字典：``{"content": str, "metadata": {...}}``。
        """
        import fitz  # PyMuPDF——延迟导入，使该包成为可选依赖

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        source_file = os.path.basename(file_path)
        chunks: list[dict[str, Any]] = []

        doc: fitz.Document | None = None
        try:
            doc = fitz.open(file_path)

            # ------------------------------------------------------------------
            # 从 PDF 目录（书签 / 大纲）构建 页码 -> 标题 查找表。
            # ``get_toc`` 返回 [level, title, page_number] 条目的列表。
            # ------------------------------------------------------------------
            toc_entries: list[tuple[int, int, str]] = []
            try:
                toc = doc.get_toc(simple=True)
                for level, title, page_num in toc:
                    # 目录中的 page_num 从 1 开始
                    title = title.strip()
                    if page_num >= 1 and title and level >= 1:
                        toc_entries.append((page_num, level, title))
                toc_entries.sort(key=lambda entry: entry[0])
            except Exception as exc:
                logger.debug("Could not extract TOC from {}: {}", source_file, exc)

            total_pages = len(doc)
            scanned_page_count = 0  # 无可提取文本的页面数
            toc_index = 0
            heading_stack: list[str] = []
            current_heading = ""
            current_heading_level: int | None = None

            for page_index in range(total_pages):
                page_num = page_index + 1  # 从 1 开始
                while toc_index < len(toc_entries) and toc_entries[toc_index][0] <= page_num:
                    _, level, title = toc_entries[toc_index]
                    heading_stack = heading_stack[:level - 1]
                    heading_stack.append(title)
                    current_heading = title
                    current_heading_level = level
                    toc_index += 1
                try:
                    page = doc.load_page(page_index)
                    text = page.get_text("text")  # UTF-8，支持 CJK
                except Exception as exc:
                    logger.warning(
                        "Failed to extract text from page {} of {}: {}",
                        page_num, source_file, exc,
                    )
                    text = ""

                text = text.strip()

                if not text:
                    scanned_page_count += 1

                metadata: dict[str, Any] = {
                    "page_num": page_num,
                    "heading": current_heading,
                    "heading_level": current_heading_level,
                    "section_path": list(heading_stack),
                    "source_file": source_file,
                }

                # 如果整个文档没有可提取文本，则将其标记为扫描版，
                # 以便下游消费者知道可能需要 OCR。
                if not text:
                    metadata["scanned"] = True
                    metadata["note"] = (
                        "No extractable text on this page — "
                        "the PDF may be scanned or image-based."
                    )

                # 即使是空白页也会被记录，以保持页码编号的完整性
                chunks.append({"content": text, "metadata": metadata})

            # ------------------------------------------------------------------
            # 如果*所有*页面都为空，记录一个汇总警告
            # ------------------------------------------------------------------
            if scanned_page_count == total_pages and total_pages > 0:
                logger.warning(
                    "PDF '{}' appears to be fully scanned ({} pages, no text found).",
                    source_file, total_pages,
                )

        except Exception as exc:
            logger.error("Error parsing PDF '{}': {}", source_file, exc)
            raise ValueError(f"Failed to parse PDF '{source_file}': {exc}") from exc
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass

        return chunks
