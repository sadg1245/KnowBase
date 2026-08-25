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
            toc_headings: dict[int, str] = {}
            try:
                toc = doc.get_toc(simple=True)
                for _level, title, page_num in toc:
                    # 目录中的 page_num 从 1 开始
                    if page_num >= 1 and title:
                        toc_headings[page_num] = title.strip()
            except Exception as exc:
                logger.debug("Could not extract TOC from {}: {}", source_file, exc)

            total_pages = len(doc)
            scanned_page_count = 0  # 无可提取文本的页面数

            for page_index in range(total_pages):
                page_num = page_index + 1  # 从 1 开始
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

                # 确定标题：优先使用目录条目，否则留空
                heading = toc_headings.get(page_num, "")

                metadata: dict[str, Any] = {
                    "page_num": page_num,
                    "heading": heading,
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
