"""用于 KnowBase 采集器流水线的 Markdown 解析器。"""

import os
import re
from typing import Any

from loguru import logger

from .base import BaseParser

# 匹配行首 ATX 风格标题（# … ######）的正则表达式。
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# 用于剥离内联/片段 HTML 标签同时保留内容的正则表达式。
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class MarkdownParser(BaseParser):
    """解析 Markdown 文件，按标题拆分为文档块。

    行为说明
    ---------
    * 每个顶级章节（一个标题行及其后直到下一个**同级或更高级**标题
      或文件末尾的所有内容）成为一个块。
    * 代码块（用三个反引号包裹的部分）会原样保留为所在章节内容的一部分。
    * 如果文件不包含标题，则整个文件作为单个块返回。
    * Markdown 中嵌入的任何原始 HTML 标签会被剥离。
    """

    # --------------------------------------------------------------------- #
    # 辅助方法
    # --------------------------------------------------------------------- #

    @staticmethod
    def _strip_html(text: str) -> str:
        """从 *text* 中移除 HTML 标签，同时保留内部内容。"""
        return _HTML_TAG_RE.sub("", text)

    @staticmethod
    def _split_into_sections(raw_text: str) -> list[tuple[str, str, int]]:
        """按 ATX 标题拆分 *raw_text*。

        返回 ``(heading_text, section_body, level)`` 元组的列表。
        第一个标题之前的内容返回时 ``heading_text=""`` 且 ``level=0``。
        """
        sections: list[tuple[str, str, int]] = []
        matches = list(_HEADING_RE.finditer(raw_text))

        if not matches:
            # 没有任何标题
            return [("", raw_text.strip(), 0)]

        # 第一个标题之前的内容（前导部分）
        preamble = raw_text[: matches[0].start()].strip()
        if preamble:
            sections.append(("", preamble, 0))

        for idx, match in enumerate(matches):
            level = len(match.group(1))  # '#' 字符的数量
            heading_text = match.group(2).strip()

            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)

            body = raw_text[start:end].strip()
            sections.append((heading_text, body, level))

        return sections

    # --------------------------------------------------------------------- #
    # 公共接口
    # --------------------------------------------------------------------- #

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        """解析 Markdown 文件并返回基于章节的块。

        参数
        ----------
        file_path : str
            ``.md`` 文件的路径。

        返回
        -------
        list[dict]
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        source_file = os.path.basename(file_path)

        # 以 UTF-8 编码读取（Markdown 绝大多数使用 UTF-8，
        # 这样可以正确处理中文字符）。
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                raw_text = fh.read()
        except UnicodeDecodeError:
            logger.warning(
                "UTF-8 decode failed for '{}'; falling back to latin-1.", source_file,
            )
            with open(file_path, "r", encoding="latin-1") as fh:
                raw_text = fh.read()
        except Exception as exc:
            logger.error("Could not read Markdown file '{}': {}", source_file, exc)
            raise ValueError(
                f"Cannot read Markdown file '{source_file}': {exc}"
            ) from exc

        # 剥离原始 HTML 标签
        raw_text = self._strip_html(raw_text)

        sections = self._split_into_sections(raw_text)

        chunks: list[dict[str, Any]] = []
        section_counter = 0

        for heading_text, body, level in sections:
            # 构建完整内容：标题行 + 正文
            parts: list[str] = []
            if heading_text:
                prefix = "#" * level + " " if level else ""
                parts.append(f"{prefix}{heading_text}")
            if body:
                parts.append(body)

            content = "\n\n".join(parts).strip()
            if not content:
                continue

            section_counter += 1
            chunks.append({
                "content": content,
                "metadata": {
                    "page_num": section_counter,
                    "heading": heading_text,
                    "source_file": source_file,
                },
            })

        if not chunks:
            logger.warning(
                "Markdown '{}' produced no chunks (empty file?).", source_file,
            )

        return chunks
