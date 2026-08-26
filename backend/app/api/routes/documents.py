"""文档上传与管理端点。"""

import os
import uuid
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models.document import Document
from app.models.workspace import Workspace
from app.models.learning import KnowledgePoint
from app.services.document_jobs import enqueue_document_processing
from app.schemas.schemas import (
    DocumentResponse,
    DocumentStatusResponse,
    UploadResponse,
)


router = APIRouter(tags=["documents"])

# 允许上传的文件扩展名
ALLOWED_EXTENSIONS: set[str] = {
    # 文档
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".csv",
    ".txt",
    ".md",
    ".rst",
    # 标记语言 / 代码
    ".html",
    ".htm",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
}


def _validate_extension(filename: str) -> str:
    """返回小写扩展名，不支持则抛出 HTTPException。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type '{ext}' is not allowed. "
                f"Accepted types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )
    return ext


async def _validate_workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    """确保工作区存在并返回该工作区。"""
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _process_document(db: AsyncSession, document: Document, settings: Settings) -> None:
    """执行文档处理流水线（Celery 不可用时的同步回退方案）。

    读取文件、分块文本并将向量嵌入存储到 ChromaDB。
    当前为尽力而为的内联实现；后续可由 Celery 任务替代。
    """
    try:
        document.status = "processing"
        await db.flush()

        # ------------------------------------------------------------------
        # 第 1 步 — 从文件中提取文本
        # ------------------------------------------------------------------
        text = await _extract_text(document.file_path, document.file_type)
        if not text or not text.strip():
            document.status = "failed"
            document.error_message = "Extracted text is empty."
            await db.flush()
            return

        # ------------------------------------------------------------------
        # 第 2 步 — 文本分块
        # ------------------------------------------------------------------
        chunks = _chunk_text(text, settings.CHUNK_SIZE, settings.CHUNK_OVERLAP)
        document.chunk_count = len(chunks)

        # ------------------------------------------------------------------
        # 第 3 步 — 将向量存储到 ChromaDB
        # ------------------------------------------------------------------
        try:
            import chromadb
            from app.core.embedding import get_embedding_service

            chroma_client = chromadb.HttpClient(
                host=settings.CHROMA_HOST, port=settings.CHROMA_PORT
            )
            collection_name = f"ws_{document.workspace_id}".replace("-", "_")
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )

            ids = [f"{document.id}_chunk_{i}" for i in range(len(chunks))]
            embeddings = await get_embedding_service().embed_texts(chunks)
            metadatas = [
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "source_file": document.filename,
                    "chunk_index": i,
                    "page_num": 1,
                }
                for i in range(len(chunks))
            ]

            collection.add(
                ids=ids,
                documents=chunks,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "Stored {} chunks for document '{}' in ChromaDB collection '{}'",
                len(chunks),
                document.id,
                collection_name,
            )
        except Exception as chroma_exc:
            raise RuntimeError(f"ChromaDB storage failed: {chroma_exc}") from chroma_exc

        document.status = "ready"
        document.error_message = None
        await db.flush()
        logger.info("Document '{}' processed successfully ({} chunks)", document.id, len(chunks))

    except Exception as exc:
        logger.error("Document processing failed for '{}': {}", document.id, exc)
        document.status = "failed"
        document.error_message = str(exc)
        await db.flush()


async def _extract_text(file_path: str, file_type: str) -> str:
    """根据文件类型提取纯文本内容。"""
    import asyncio

    if file_type in (".txt", ".md", ".rst", ".csv", ".json", ".xml", ".yaml", ".yml"):
        import chardet

        async with aiofiles.open(file_path, "rb") as f:
            raw = await f.read()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        return raw.decode(encoding, errors="replace")

    if file_type in (".html", ".htm"):
        from bs4 import BeautifulSoup

        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="replace") as f:
            html = await f.read()
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n")

    if file_type == ".pdf":
        from app.collector.content_filter import filter_learning_content
        from app.collector.parsers.pdf_parser import PDFParser

        def _read_pdf() -> str:
            pages = filter_learning_content(PDFParser().parse(file_path))
            return "\n".join(str(page.get("content") or "") for page in pages)

        return await asyncio.to_thread(_read_pdf)

    if file_type == ".docx":
        import docx

        def _read_docx() -> str:
            doc = docx.Document(file_path)
            return "\n".join(para.text for para in doc.paragraphs)

        return await asyncio.to_thread(_read_docx)

    if file_type == ".pptx":
        from pptx import Presentation

        def _read_pptx() -> str:
            prs = Presentation(file_path)
            texts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame:
                        texts.append(shape.text_frame.text)
            return "\n".join(texts)

        return await asyncio.to_thread(_read_pptx)

    if file_type == ".xlsx":
        import pandas as pd

        def _read_xlsx() -> str:
            df = pd.read_excel(file_path, engine="openpyxl")
            return df.to_string(index=False)

        return await asyncio.to_thread(_read_xlsx)

    logger.warning("No text extractor for file type '{}'", file_type)
    return ""


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """将文本拆分为大小约 chunk_size 字符、带有 chunk_overlap 重叠的分块。"""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - chunk_overlap
    return chunks


# ---------------------------------------------------------------------------
# 上传文档
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=list[UploadResponse],
    status_code=201,
)
async def upload_documents(
    workspace_id: str,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    """上传一个或多个文件到工作区。

    每个文件会经过校验、保存到磁盘并排队处理。
    """
    workspace = await _validate_workspace(db, workspace_id)

    upload_dir = os.path.join(settings.UPLOAD_DIR, workspace_id)
    os.makedirs(upload_dir, exist_ok=True)

    max_bytes = settings.UPLOAD_MAX_SIZE_MB * 1024 * 1024
    responses: list[dict] = []

    for upload_file in files:
        # 校验文件类型
        ext = _validate_extension(upload_file.filename or "unknown")

        # 生成基于 UUID 的文件名并保存
        unique_name = f"{uuid.uuid4().hex}{ext}"
        save_path = os.path.join(upload_dir, unique_name)
        file_size = 0
        try:
            async with aiofiles.open(save_path, "wb") as f:
                while chunk := await upload_file.read(1024 * 1024):
                    file_size += len(chunk)
                    if file_size > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File '{upload_file.filename}' exceeds maximum size of {settings.UPLOAD_MAX_SIZE_MB} MB",
                        )
                    await f.write(chunk)
            if file_size == 0:
                raise HTTPException(status_code=400, detail=f"File '{upload_file.filename}' is empty")
        except Exception:
            if os.path.exists(save_path):
                os.remove(save_path)
            raise

        # 创建数据库记录
        document = Document(
            workspace_id=workspace_id,
            filename=upload_file.filename or unique_name,
            file_path=save_path,
            file_type=ext,
            file_size=file_size,
            chunk_count=0,
            status="pending",
        )
        db.add(document)
        await db.flush()
        await db.refresh(document)

        document.status = "processing"
        await db.flush()
        await db.commit()

        # Dispatch only after another worker session can see the processing state.
        try:
            enqueue_document_processing(document)
            logger.info("Dispatched document '{}' to Celery worker", document.id)
        except Exception as celery_exc:
            document.status = "failed"
            document.error_message = f"Queue dispatch failed: {celery_exc}"[:1000]
            await db.commit()
            logger.warning("Celery dispatch failed for '{}': {}", document.id, celery_exc)
        await db.refresh(document)

        responses.append(
            {
                "document": DocumentResponse.model_validate(document),
                "status": document.status,
            }
        )

        logger.info(
            "Uploaded '{}' -> '{}' for workspace '{}'",
            upload_file.filename,
            unique_name,
            workspace_id,
        )

    return responses


# ---------------------------------------------------------------------------
# 列出工作区中的文档
# ---------------------------------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(
    workspace_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    file_type: Optional[str] = Query(None, description="Filter by file type"),
    db: AsyncSession = Depends(get_db),
) -> list[Document]:
    """列出工作区中的所有文档，可按条件筛选。"""
    await _validate_workspace(db, workspace_id)

    stmt = (
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
    )
    if status:
        stmt = stmt.where(Document.status == status)
    if file_type:
        stmt = stmt.where(Document.file_type == file_type)

    result = await db.execute(stmt)
    documents = result.scalars().all()
    return list(documents)


# ---------------------------------------------------------------------------
# 获取文档详情
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> Document:
    """根据 ID 返回单个文档。"""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/documents/{document_id}/content")
async def preview_document(
    document_id: str,
    download: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Serve an owned document through the API instead of a public static folder."""
    document = (await db.execute(select(Document).where(Document.id == document_id))).scalar_one_or_none()
    if document is None or not os.path.isfile(document.file_path):
        raise HTTPException(status_code=404, detail="Document not found")
    safe_name = document.filename.replace('"', "")
    disposition = "attachment" if download else "inline"
    return FileResponse(
        document.file_path,
        filename=safe_name,
        content_disposition_type=disposition,
    )


# ---------------------------------------------------------------------------
# 获取文档处理状态
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """仅返回文档的处理状态字段。"""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": document.id,
        "status": document.status,
        "chunk_count": document.chunk_count,
        "error_message": document.error_message,
    }


# ---------------------------------------------------------------------------
# 删除文档
# ---------------------------------------------------------------------------


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """删除文档：从磁盘移除文件、删除数据库记录以及清除 ChromaDB 中的向量。"""
    stmt = select(Document).where(Document.id == document_id)
    result = await db.execute(stmt)
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # 从磁盘删除文件
    if os.path.exists(document.file_path):
        os.remove(document.file_path)
        logger.info("Removed file '{}'", document.file_path)

    # 从 ChromaDB 中删除向量
    try:
        import chromadb

        chroma_client = chromadb.HttpClient(
            host=settings.CHROMA_HOST, port=settings.CHROMA_PORT
        )
        collection_name = f"ws_{document.workspace_id}".replace("-", "_")
        collection = chroma_client.get_collection(name=collection_name)
        # 兼容新旧摄取流水线的元数据字段。
        for metadata_key in ("doc_id", "document_id"):
            try:
                collection.delete(where={metadata_key: document.id})
            except Exception:
                pass
        logger.info(
            "Removed vectors for document '{}' from ChromaDB", document_id
        )
    except Exception as exc:
        logger.warning("Failed to remove vectors from ChromaDB: {}", exc)

    # 删除数据库记录
    await db.execute(delete(KnowledgePoint).where(KnowledgePoint.document_id == document_id))
    await db.delete(document)
    await db.flush()
    logger.info("Deleted document '{}'", document_id)
    return None
