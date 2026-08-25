"""
TextSplitter — 中文感知的文本分块器

使用递归字符分割策略，支持中文标点符号作为分割边界，
确保语义完整性，适合 RAG 场景下的文档预处理。
"""

from typing import Optional

from loguru import logger


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

_text_splitter_instance: Optional["TextSplitter"] = None


def get_text_splitter() -> "TextSplitter":
    """返回全局 TextSplitter 单例。"""
    global _text_splitter_instance
    if _text_splitter_instance is not None:
        return _text_splitter_instance

    from app.config import settings

    _text_splitter_instance = TextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
    )
    return _text_splitter_instance


class TextSplitter:
    """中文感知的递归文本分块器"""

    # 默认中文感知分割符序列（按优先级从高到低）
    DEFAULT_SEPARATORS = [
        "\n\n",  # 段落分隔
        "\n",    # 行分隔
        "。",    # 中文句号
        ".",     # 英文句号
        "！",    # 中文感叹号
        "!",     # 英文感叹号
        "？",    # 中文问号
        "?",     # 英文问号
        "；",    # 中文分号
        ";",     # 英文分号
        " ",     # 空格
        "",      # 任意字符（最终兜底）
    ]

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        separators: Optional[list[str]] = None,
    ):
        """
        初始化 TextSplitter。

        Args:
            chunk_size: 每个块的最大字符数
            chunk_overlap: 相邻块之间的重叠字符数
            separators: 自定义分割符列表（可选）
        """
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or self.DEFAULT_SEPARATORS

        logger.debug(
            f"TextSplitter 初始化: chunk_size={chunk_size}, "
            f"chunk_overlap={chunk_overlap}"
        )

    def split_text(
        self, text: str, metadata: Optional[dict] = None
    ) -> list[dict]:
        """
        将文本分割为多个带元数据的块。

        Args:
            text: 待分割的文本
            metadata: 附加到每个块的元数据（可选），常见字段：
                      source_file, page_num, heading 等

        Returns:
            块列表，每项包含 {content, metadata}
        """
        if not text or not text.strip():
            return []

        base_metadata = metadata or {}
        chunks = self._recursive_split(text, self.separators)
        result = []

        for idx, chunk_text in enumerate(chunks):
            chunk_meta = {
                **base_metadata,
                "chunk_index": idx,
                "total_chunks": len(chunks),
            }
            result.append({
                "content": chunk_text,
                "metadata": chunk_meta,
            })

        logger.debug(
            f"文本分割完成: 原始长度={len(text)}, 块数={len(result)}"
        )
        return result

    def split_documents(self, documents: list[dict]) -> list[dict]:
        """
        批量处理多个文档的分块。

        Args:
            documents: 文档列表，每项需包含 {content, metadata} 或 {text, metadata}

        Returns:
            所有文档的块列表
        """
        all_chunks = []

        for doc in documents:
            text = doc.get("content") or doc.get("text", "")
            metadata = doc.get("metadata", {})
            chunks = self.split_text(text, metadata)
            all_chunks.extend(chunks)

        logger.info(
            f"批量分块完成: {len(documents)} 个文档 -> {len(all_chunks)} 个块"
        )
        return all_chunks

    def _recursive_split(
        self, text: str, separators: list[str]
    ) -> list[str]:
        """
        递归字符分割核心算法。

        依次尝试每个分割符，选择能将文本合理分割的分割符，
        确保每个块不超过 chunk_size，相邻块之间有 chunk_overlap 重叠。
        """
        final_chunks: list[str] = []

        # 选择当前层级的分割符
        separator = separators[-1]  # 默认用最后一个（空字符串 = 字符级）
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = sep
                new_separators = []
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1:]
                break

        # 按分割符切分
        if separator:
            splits = text.split(separator)
        else:
            splits = list(text)

        # 合并过短的片段，构建符合 chunk_size 的块
        current_chunk = ""
        good_splits = []

        for split in splits:
            # 加上分割符的预估长度
            test_chunk = current_chunk + separator + split if current_chunk else split

            if len(test_chunk) <= self.chunk_size:
                current_chunk = test_chunk
            else:
                # 当前块已满，保存并开始新块
                if current_chunk:
                    good_splits.append(current_chunk)

                # 如果单个 split 就超过 chunk_size，递归分割
                if len(split) > self.chunk_size:
                    if new_separators:
                        sub_chunks = self._recursive_split(split, new_separators)
                        good_splits.extend(sub_chunks)
                        current_chunk = ""
                    else:
                        # 字符级强制截断
                        forced_chunks = self._force_split(split)
                        good_splits.extend(forced_chunks)
                        current_chunk = ""
                else:
                    current_chunk = split

        # 保存最后一个块
        if current_chunk:
            good_splits.append(current_chunk)

        # 添加重叠区域
        if self.chunk_overlap > 0 and len(good_splits) > 1:
            final_chunks = self._add_overlap(good_splits)
        else:
            final_chunks = good_splits

        # 过滤空块
        return [c.strip() for c in final_chunks if c.strip()]

    def _force_split(self, text: str) -> list[str]:
        """对超长文本进行强制按字符数截断"""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - self.chunk_overlap if self.chunk_overlap > 0 else end
        return chunks

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        """为相邻块添加重叠文本，增强上下文连续性"""
        result = [chunks[0]]

        for i in range(1, len(chunks)):
            # 从前一个块的末尾取 overlap 长度的文本
            prev_chunk = chunks[i - 1]
            overlap_text = prev_chunk[-self.chunk_overlap:] if len(prev_chunk) > self.chunk_overlap else prev_chunk
            # 将重叠文本拼到当前块的开头
            overlapped = overlap_text + chunks[i]
            # 确保不超过 chunk_size
            if len(overlapped) > self.chunk_size:
                overlapped = overlapped[:self.chunk_size]
            result.append(overlapped)

        return result
