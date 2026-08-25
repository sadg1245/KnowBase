"""工作区 CRUD 端点。"""

import re
import unicodedata
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models.workspace import Workspace
from app.models.document import Document
from app.schemas.schemas import (
    WorkspaceCreate,
    WorkspaceUpdate,
    WorkspaceResponse,
    WorkspaceDetailResponse,
)


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(text: str) -> str:
    """将工作区名称转换为 URL 安全的 slug。"""
    # 标准化 unicode
    text = unicodedata.normalize("NFKD", text)
    # 将非字母数字字符替换为连字符
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"[-\s]+", "-", text).strip("-_")
    text = text.lower()
    # 同时处理中文/CJK 字符 — 保持原样
    text = re.sub(r"[^\w-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "workspace"


async def _ensure_unique_slug(
    db: AsyncSession, base_slug: str, exclude_id: str | None = None
) -> str:
    """确保 slug 唯一性；如有冲突则追加计数器。"""
    slug = base_slug
    counter = 1
    while True:
        stmt = select(Workspace).where(Workspace.slug == slug)
        if exclude_id:
            stmt = stmt.where(Workspace.id != exclude_id)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is None:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


# ---------------------------------------------------------------------------
# 列出所有工作区
# ---------------------------------------------------------------------------


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """返回所有工作区，按创建时间降序排列（最新的在前）。"""
    stmt = (
        select(Workspace, func.count(Document.id).label("document_count"))
        .outerjoin(Document, Document.workspace_id == Workspace.id)
        .group_by(Workspace.id)
        .order_by(Workspace.created_at.desc())
    )
    result = await db.execute(stmt)
    return [
        {
            "id": workspace.id,
            "name": workspace.name,
            "description": workspace.description,
            "slug": workspace.slug,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "document_count": document_count,
            "learning_goal": workspace.learning_goal or "",
            "domain": workspace.domain or "未分类",
            "accent_color": workspace.accent_color,
            "archived": workspace.archived,
        }
        for workspace, document_count in result.all()
    ]


# ---------------------------------------------------------------------------
# 创建工作区
# ---------------------------------------------------------------------------


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """创建新工作区，自动生成 slug。"""
    base_slug = _slugify(payload.name)
    unique_slug = await _ensure_unique_slug(db, base_slug)

    workspace = Workspace(
        name=payload.name,
        description=payload.description or "",
        learning_goal=payload.learning_goal or "",
        domain=payload.domain or "未分类",
        accent_color=payload.accent_color or "#1f7a8c",
        slug=unique_slug,
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    logger.info("Created workspace '{}' with slug '{}'", workspace.name, workspace.slug)
    return workspace


# ---------------------------------------------------------------------------
# 获取工作区详情
# ---------------------------------------------------------------------------


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回单个工作区及其文档数量。"""
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 统计文档数量
    count_stmt = (
        select(func.count(Document.id))
        .where(Document.workspace_id == workspace_id)
    )
    count_result = await db.execute(count_stmt)
    doc_count = count_result.scalar() or 0

    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "slug": workspace.slug,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "document_count": doc_count,
        "learning_goal": workspace.learning_goal or "",
        "domain": workspace.domain or "未分类",
        "accent_color": workspace.accent_color,
        "archived": workspace.archived,
    }


# ---------------------------------------------------------------------------
# 更新工作区
# ---------------------------------------------------------------------------


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """更新工作区名称和/或描述。"""
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if payload.name is not None:
        workspace.name = payload.name
        base_slug = _slugify(payload.name)
        workspace.slug = await _ensure_unique_slug(db, base_slug, exclude_id=workspace_id)

    for field in ("description", "learning_goal", "domain", "accent_color", "archived"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(workspace, field, value)

    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(workspace)
    logger.info("Updated workspace '{}'", workspace.id)
    return workspace


# ---------------------------------------------------------------------------
# 删除工作区
# ---------------------------------------------------------------------------


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> None:
    """删除工作区并级联删除其所有文档。"""
    stmt = select(Workspace).where(Workspace.id == workspace_id)
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")

    docs = (await db.execute(select(Document).where(Document.workspace_id == workspace_id))).scalars().all()
    for document in docs:
        if os.path.isfile(document.file_path):
            try:
                os.remove(document.file_path)
            except OSError:
                logger.warning("Could not remove file for document '{}'", document.id)
    try:
        import chromadb
        chromadb.HttpClient(host=settings.CHROMA_HOST, port=settings.CHROMA_PORT).delete_collection(
            name=f"ws_{workspace_id}".replace("-", "_")
        )
    except Exception:
        logger.warning("Vector collection cleanup deferred for workspace '{}'", workspace_id)
    await db.delete(workspace)
    await db.flush()
    logger.info("Deleted workspace '{}' (and cascaded documents)", workspace_id)
    return None
