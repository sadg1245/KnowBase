"""KnowBase 采集器的主要文档处理流水线。"""

import csv
import io
import json
import os
from typing import Any

from loguru import logger

from .parsers.base import BaseParser
from .parsers.docx_parser import DocxParser
from .parsers.markdown_parser import MarkdownParser
from .parsers.pdf_parser import PDFParser
from .parsers.pptx_parser import PptxParser
from .content_filter import filter_learning_content

# ---------------------------------------------------------------------------
# 支持的文件扩展名 → 规范名称映射
# ---------------------------------------------------------------------------
_FILE_TYPE_MAP: dict[str, str] = {
    "pdf": "pdf",
    "docx": "docx",
    "pptx": "pptx",
    "md": "md",
    "markdown": "md",
    "txt": "txt",
    "xlsx": "xlsx",
    "csv": "csv",
    "html": "html",
    "htm": "html",
}


# =========================================================================
# txt / xlsx / csv / html 的轻量级内联解析器
# =========================================================================

class _TxtParser(BaseParser):
    """通过 chardet 自动检测编码来读取纯文本文件。"""

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Text file not found: {file_path}")

        source_file = os.path.basename(file_path)
        raw_bytes = open(file_path, "rb").read()

        # 检测编码
        encoding = "utf-8"
        try:
            import chardet
            detected = chardet.detect(raw_bytes)
            if detected and detected.get("encoding"):
                encoding = detected["encoding"]
                logger.debug(
                    "Detected encoding for '{}': {} (confidence {:.0%})",
                    source_file, encoding, detected.get("confidence", 0),
                )
        except ImportError:
            logger.debug("chardet not installed; defaulting to UTF-8 for '{}'.", source_file)

        try:
            text = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            logger.warning(
                "Failed to decode '{}' with {}; falling back to UTF-8.",
                source_file, encoding,
            )
            text = raw_bytes.decode("utf-8", errors="replace")

        text = text.strip()
        if not text:
            return []

        return [{
            "content": text,
            "metadata": {
                "page_num": 1,
                "heading": "",
                "source_file": source_file,
            },
        }]


class _XlsxParser(BaseParser):
    """解析 Excel 工作簿——每行转换为一行文本。"""

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Excel file not found: {file_path}")

        source_file = os.path.basename(file_path)
        chunks: list[dict[str, Any]] = []

        try:
            import openpyxl
        except ImportError:
            raise ValueError(
                "openpyxl is required to parse .xlsx files but is not installed."
            )

        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        except Exception as exc:
            raise ValueError(
                f"Corrupt or unreadable XLSX '{source_file}': {exc}"
            ) from exc

        try:
            for sheet_index, sheet_name in enumerate(wb.sheetnames, start=1):
                ws = wb[sheet_name]
                lines: list[str] = []

                try:
                    # 提取表头行
                    header_row: list[str] = []
                    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
                        header_row = [
                            str(cell) if cell is not None else "" for cell in row
                        ]
                        break
                    if any(cell.strip() for cell in header_row):
                        lines.append(" | ".join(header_row))

                    # 将每个数据行转换为文本
                    for row in ws.iter_rows(min_row=2, values_only=True):
                        cells = [str(cell) if cell is not None else "" for cell in row]
                        if any(c.strip() for c in cells):
                            if header_row and len(header_row) == len(cells):
                                pairs = [
                                    f"{h}: {v}"
                                    for h, v in zip(header_row, cells)
                                    if v.strip()
                                ]
                                lines.append(" | ".join(pairs))
                            else:
                                lines.append(" | ".join(cells))
                except Exception as exc:
                    logger.warning(
                        "Error reading sheet '{}' in '{}': {}",
                        sheet_name, source_file, exc,
                    )
                    continue

                content = "\n".join(lines).strip()
                if content:
                    chunks.append({
                        "content": content,
                        "metadata": {
                            "page_num": sheet_index,
                            "heading": sheet_name,
                            "heading_level": 1,
                            "section_path": [sheet_name],
                            "source_file": source_file,
                        },
                    })
        finally:
            try:
                wb.close()
            except Exception:
                pass

        return chunks


class _CsvParser(BaseParser):
    """解析 CSV 文件——将每行转换为文本行。"""

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        source_file = os.path.basename(file_path)

        # 读取原始字节并检测编码
        raw_bytes = open(file_path, "rb").read()
        encoding = "utf-8"
        try:
            import chardet
            detected = chardet.detect(raw_bytes)
            if detected and detected.get("encoding"):
                encoding = detected["encoding"]
        except ImportError:
            pass

        try:
            text_data = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text_data = raw_bytes.decode("utf-8", errors="replace")

        lines: list[str] = []
        try:
            reader = csv.reader(io.StringIO(text_data))
            rows = list(reader)
        except Exception as exc:
            raise ValueError(f"Failed to parse CSV '{source_file}': {exc}") from exc

        if not rows:
            return []

        header = rows[0]
        for row in rows[1:]:
            if not any(cell.strip() for cell in row):
                continue
            if len(header) == len(row):
                pairs = [
                    f"{h}: {v}" for h, v in zip(header, row) if v.strip()
                ]
                lines.append(" | ".join(pairs))
            else:
                lines.append(" | ".join(row))

        content = "\n".join(lines).strip()
        if not content:
            return []

        return [{
            "content": content,
            "metadata": {
                "page_num": 1,
                "heading": "",
                "source_file": source_file,
            },
        }]


class _HtmlParser(BaseParser):
    """使用 BeautifulSoup 解析 HTML 文件以提取可见文本。"""

    def parse(self, file_path: str) -> list[dict[str, Any]]:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"HTML file not found: {file_path}")

        source_file = os.path.basename(file_path)

        # 读取原始字节并检测编码
        raw_bytes = open(file_path, "rb").read()
        encoding = "utf-8"
        try:
            import chardet
            detected = chardet.detect(raw_bytes)
            if detected and detected.get("encoding"):
                encoding = detected["encoding"]
        except ImportError:
            pass

        try:
            html_text = raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            html_text = raw_bytes.decode("utf-8", errors="replace")

        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ValueError(
                "beautifulsoup4 is required to parse HTML files but is not installed."
            )

        try:
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception as exc:
            raise ValueError(
                f"Failed to parse HTML '{source_file}': {exc}"
            ) from exc

        # 完全移除 <script> 和 <style> 元素
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # 提取可见文本
        text = soup.get_text(separator="\n", strip=True)

        # 尝试提取 <title> 标签作为标题元数据
        heading = ""
        title_tag = soup.find("title")
        if title_tag:
            heading = title_tag.get_text(strip=True)

        if not text.strip():
            return []

        return [{
            "content": text.strip(),
            "metadata": {
                "page_num": 1,
                "heading": heading,
                "source_file": source_file,
            },
        }]


# =========================================================================
# 主流水线
# =========================================================================

class DocumentPipeline:
    """编排完整的文档摄取流程。

    参数
    ----------
    embedding_service : object
        必须暴露 ``async embed_texts(texts: list[str]) -> list[list[float]]`` 方法。
    vector_store : object
        必须暴露 ``async add(doc_id, texts, embeddings, metadatas)`` 方法。
    text_splitter : object
        必须暴露 ``split_documents(chunks: list[dict]) -> list[dict]`` 方法，
        其中每个 dict 包含 ``content`` 和 ``metadata`` 键。
    """

    # 解析器实例是无状态的，因此可以安全地共享它们。
    _PARSER_CACHE: dict[str, BaseParser] = {}

    def __init__(
        self,
        embedding_service: Any,
        vector_store: Any,
        text_splitter: Any,
    ):
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.text_splitter = text_splitter

    # ------------------------------------------------------------------ #
    # 解析器工厂
    # ------------------------------------------------------------------ #

    def _get_parser(self, file_type: str) -> BaseParser:
        """返回与 *file_type* 对应的解析器。

        参数
        ----------
        file_type : str
            文件扩展名（不含点号），例如 ``"pdf"``、``"docx"``。

        抛出
        ------
        ValueError
            如果文件类型不受支持。
        """
        normalized_type = file_type.lower().strip().lstrip(".")
        canonical = _FILE_TYPE_MAP.get(normalized_type)
        if canonical is None:
            raise ValueError(
                f"Unsupported file type: '{file_type}'. "
                f"Supported types: {', '.join(sorted(_FILE_TYPE_MAP.keys()))}"
            )

        # 延迟实例化并缓存解析器
        if canonical not in self._PARSER_CACHE:
            parser: BaseParser
            if canonical == "pdf":
                parser = PDFParser()
            elif canonical == "docx":
                parser = DocxParser()
            elif canonical == "pptx":
                parser = PptxParser()
            elif canonical == "md":
                parser = MarkdownParser()
            elif canonical == "txt":
                parser = _TxtParser()
            elif canonical == "xlsx":
                parser = _XlsxParser()
            elif canonical == "csv":
                parser = _CsvParser()
            elif canonical == "html":
                parser = _HtmlParser()
            else:
                raise ValueError(f"No parser implemented for type: {canonical}")
            self._PARSER_CACHE[canonical] = parser

        return self._PARSER_CACHE[canonical]

    # ------------------------------------------------------------------ #
    # 数据库辅助方法（薄封装——请适配你的 ORM / 会话接口）
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _update_document_status(
        db_session: Any,
        document_id: str,
        **kwargs: Any,
    ) -> None:
        """更新由 *document_id* 标识的 Document 记录的字段。

        这里使用通用的 SQLAlchemy 2.x 异步模式。请调整 ``Document`` 的导入
        路径以匹配你项目中的模型位置。
        """
        from app.models.document import Document

        try:
            from sqlalchemy import update
            stmt = (
                update(Document)
                .where(Document.id == document_id)
                .values(**kwargs)
            )
            await db_session.execute(stmt)
            await db_session.commit()
        except Exception as exc:
            logger.error(
                "Failed to update document {} status: {}", document_id, exc,
            )
            try:
                await db_session.rollback()
            except Exception as rollback_exc:
                logger.error(
                    "Failed to roll back document {} status update: {}",
                    document_id,
                    rollback_exc,
                )
            raise

    # ------------------------------------------------------------------ #
    # 主入口
    # ------------------------------------------------------------------ #

    async def process_document(
        self,
        document_id: str,
        file_path: str,
        file_type: str,
        workspace_id: str,
        db_session: Any,
    ) -> dict[str, Any]:
        """对单个文档运行完整的摄取流水线。

        步骤
        -----
        1. 在数据库中将文档标记为 ``processing``。
        2. 使用对应的解析器将文件解析为原始块。
        3. 通过 ``text_splitter`` 将原始块拆分为最优大小。
        4. 通过 ``embedding_service`` 批量嵌入所有块。
        5. 将嵌入向量和元数据存储到 ``vector_store``。
        6. 将文档标记为 ``ready``（出错时标记为 ``failed``）。

        返回
        -------
        dict
            ``{"chunks_count": int, "embedding_count": int, "status": str}``
        """
        logger.info(
            "Starting pipeline for document {} (type={}, file={}).",
            document_id, file_type, file_path,
        )

        # 1. 标记为处理中
        await self._update_document_status(
            db_session, document_id, status="processing",
        )

        try:
            original_filename = os.path.basename(file_path)
            try:
                from sqlalchemy import select
                from app.models.document import Document
                row = await db_session.execute(select(Document).where(Document.id == document_id))
                document_record = row.scalar_one_or_none()
                if document_record is not None:
                    original_filename = document_record.filename
            except Exception as exc:
                logger.warning("Could not resolve original filename for {}: {}", document_id, exc)

            # 2. 解析
            parser = self._get_parser(file_type)
            raw_chunks = parser.parse(file_path)
            logger.info(
                "Parsed {} raw chunks from document {}.", len(raw_chunks), document_id,
            )

            parsed_count = len(raw_chunks)
            raw_chunks = filter_learning_content(raw_chunks)
            if len(raw_chunks) != parsed_count:
                logger.info(
                    "Body boundary filter kept {} of {} parsed chunks for document {}.",
                    len(raw_chunks), parsed_count, document_id,
                )

            if not raw_chunks:
                await self.vector_store.replace_document(
                    workspace_id=workspace_id,
                    document_id=document_id,
                    doc_ids=[],
                    texts=[],
                    embeddings=[],
                    metadatas=[],
                )
                from app.services.hybrid_retrieval import upsert_document_chunks
                await upsert_document_chunks(
                    db_session,
                    workspace_id,
                    document_id,
                    original_filename,
                    [],
                )
                await self._update_document_status(
                    db_session, document_id,
                    status="ready", chunk_count=0, error_message=None,
                )
                return {
                    "chunks_count": 0,
                    "embedding_count": 0,
                    "status": "ready",
                }

            # 3. 拆分为最优大小
            split_chunks: list[dict[str, Any]] = self.text_splitter.split_documents(
                raw_chunks,
            )
            logger.info(
                "Text splitter produced {} chunks from document {}.",
                len(split_chunks), document_id,
            )

            # 4. 批量嵌入
            texts = [chunk["content"] for chunk in split_chunks]
            embeddings = await self.embedding_service.embed_texts(texts)
            logger.info(
                "Generated {} embeddings for document {}.", len(embeddings), document_id,
            )

            # 5. 存储到向量存储
            metadatas: list[dict[str, Any]] = []
            for idx, chunk in enumerate(split_chunks):
                meta = dict(chunk.get("metadata", {}))
                meta["source_file"] = original_filename
                meta["doc_id"] = document_id
                meta["workspace_id"] = workspace_id
                meta["chunk_index"] = idx
                meta["section_path"] = json.dumps(
                    meta.get("section_path") or [],
                    ensure_ascii=False,
                )
                metadatas.append(meta)

            doc_ids = [f"{document_id}_chunk_{idx}" for idx in range(len(texts))]
            await self.vector_store.replace_document(
                workspace_id=workspace_id,
                document_id=document_id,
                doc_ids=doc_ids,
                texts=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "Stored {} vectors for document {}.", len(embeddings), document_id,
            )

            from app.services.hybrid_retrieval import upsert_document_chunks
            await upsert_document_chunks(
                db_session,
                workspace_id,
                document_id,
                original_filename,
                split_chunks,
            )
            logger.info("Stored {} keyword chunks for document {}.", len(split_chunks), document_id)

            # 6. 标记为就绪
            await self._update_document_status(
                db_session, document_id,
                status="ready",
                chunk_count=len(split_chunks),
                error_message=None,
            )

            summary = {
                "chunks_count": len(split_chunks),
                "embedding_count": len(embeddings),
                "status": "ready",
            }
            logger.info("Pipeline complete for document {}: {}", document_id, summary)
            return summary

        except Exception as exc:
            logger.error(
                "Pipeline failed for document {}: {}", document_id, exc,
            )
            await self._update_document_status(
                db_session, document_id,
                status="failed",
                error_message=str(exc),
            )
            return {
                "chunks_count": 0,
                "embedding_count": 0,
                "status": "failed",
                "error": str(exc),
            }
