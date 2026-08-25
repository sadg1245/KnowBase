"""使用 python-pptx 的 PPTX 解析器，用于 KnowBase 采集器流水线。"""

import os
from typing import Any

from loguru import logger

from .base import BaseParser


class PptxParser(BaseParser):
    """解析 .pptx 文件——每张幻灯片成为一个文档块。

    功能特性
    --------
    * 从每张幻灯片上的所有形状中提取文本：文本框、表格和
      组合形状。
    * 幻灯片备注（演讲者备注）在存在时会追加到幻灯片内容中。
    * 幻灯片标题（第一个具有 ``title`` 用途的占位符，或第一个
      看起来像标题的形状）存储在 ``metadata["heading"]`` 中。
    * 无可提取文本的幻灯片会被静默跳过。
    """

    # --------------------------------------------------------------------- #
    # 辅助方法
    # --------------------------------------------------------------------- #

    @staticmethod
    def _extract_text_from_shape(shape) -> list[str]:
        """递归地从形状中提取文本行。"""
        lines: list[str] = []

        # 组合形状（例如 SmartArt）
        if shape.shape_type is not None and hasattr(shape, "shapes"):
            try:
                for child in shape.shapes:
                    lines.extend(PptxParser._extract_text_from_shape(child))
            except Exception:
                pass
            return lines

        # 表格
        if shape.has_table:
            try:
                table = shape.table
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    lines.append("| " + " | ".join(cells) + " |")
            except Exception:
                pass
            return lines

        # 文本框
        if shape.has_text_frame:
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if text:
                    lines.append(text)

        return lines

    @staticmethod
    def _get_slide_title(slide) -> str:
        """返回幻灯片的标题文本，如无则返回空字符串。"""
        # 优先尝试基于占位符的标题
        try:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    ph = shape.placeholder_format
                    if ph is not None and ph.type is not None:
                        # MSO_PLACEHOLDER.TITLE == 0，SUBTITLE == 1，
                        # CENTER_TITLE == 3
                        if ph.type in (0, 1, 3):
                            title = shape.text_frame.text.strip()
                            if title:
                                return title
        except Exception:
            pass

        # 回退方案：第一个包含文本的形状
        try:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text = shape.text_frame.text.strip()
                    if text:
                        return text
        except Exception:
            pass

        return ""

    @staticmethod
    def _get_slide_notes(slide) -> str:
        """返回幻灯片的演讲者备注文本，如无则返回空字符串。"""
        try:
            if slide.has_notes_slide:
                notes_slide = slide.notes_slide
                notes_frame = notes_slide.notes_text_frame
                if notes_frame:
                    text = notes_frame.text.strip()
                    return text
        except Exception:
            pass
        return ""

    # --------------------------------------------------------------------- #
    # 公共接口
    # --------------------------------------------------------------------- #

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        """解析 .pptx 文件并返回每张非空幻灯片一个块。

        参数
        ----------
        file_path : str
            ``.pptx`` 文件的路径。

        返回
        -------
        list[dict]
        """
        from pptx import Presentation  # 延迟导入——可选依赖

        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"PPTX file not found: {file_path}")

        source_file = os.path.basename(file_path)

        try:
            prs = Presentation(file_path)
        except Exception as exc:
            logger.error("Failed to open PPTX '{}': {}", source_file, exc)
            raise ValueError(
                f"Corrupt or unreadable PPTX '{source_file}': {exc}"
            ) from exc

        chunks: list[dict[str, Any]] = []

        for slide_index, slide in enumerate(prs.slides, start=1):
            try:
                slide_title = self._get_slide_title(slide)

                # 从所有形状中收集文本
                all_lines: list[str] = []
                for shape in slide.shapes:
                    try:
                        lines = self._extract_text_from_shape(shape)
                        all_lines.extend(lines)
                    except Exception as exc:
                        logger.debug(
                            "Could not extract text from shape on slide {} of '{}': {}",
                            slide_index, source_file, exc,
                        )

                # 追加演讲者备注
                notes_text = self._get_slide_notes(slide)
                if notes_text:
                    all_lines.append("")
                    all_lines.append(f"[Notes] {notes_text}")

                content = "\n".join(all_lines).strip()

                # 跳过完全无文本的幻灯片
                if not content:
                    continue

                chunks.append({
                    "content": content,
                    "metadata": {
                        "page_num": slide_index,
                        "heading": slide_title,
                        "source_file": source_file,
                    },
                })

            except Exception as exc:
                logger.warning(
                    "Error processing slide {} of '{}': {}",
                    slide_index, source_file, exc,
                )
                # 一张幻灯片出错不应导致整个文件失败
                continue

        if not chunks:
            logger.warning(
                "PPTX '{}' produced no chunks (empty presentation?).", source_file,
            )

        return chunks
