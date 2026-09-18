"""知识库 CRUD 端点。

数据库与 API 路径继续使用 `workspaces`/`/api/workspaces` 作为内部兼容契约，
但所有查询都以 `Workspace.owner_id == current_user.id` 为服务端约束。
"""

import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_settings
from app.config import Settings
from app.core.media import (
    delete_media,
    public_image_url,
    store_image,
    validate_external_image_url,
)
from app.models.assessment import WeakKnowledgeState
from app.models.document import Document
from app.models.learning import KnowledgePoint, StudyActivity
from app.models.user import LearningDomain, User
from app.models.workspace import Workspace
from app.schemas.schemas import (
    WorkspaceCreate,
    WorkspaceDetailResponse,
    WorkspaceResponse,
    WorkspaceUpdate,
)
from app.services.goal_service import LEARNING_ACTIVITY_TYPES
from app.services.ownership import owned_domain, owned_workspace


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(text: str) -> str:
    """将知识库名称转换为 URL 安全的 slug。"""
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"[-\s]+", "-", text).strip("-_")
    text = text.lower()
    text = re.sub(r"[^\w-]", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "workspace"


async def _ensure_unique_slug(
    db: AsyncSession,
    owner_id: str,
    base_slug: str,
    exclude_id: Optional[str] = None,
) -> str:
    """同一用户内 slug 唯一；不同用户允许同名。"""
    slug = base_slug
    counter = 1
    while True:
        stmt = select(Workspace.id).where(
            Workspace.owner_id == owner_id, Workspace.slug == slug
        )
        if exclude_id:
            stmt = stmt.where(Workspace.id != exclude_id)
        if (await db.execute(stmt)).scalar_one_or_none() is None:
            return slug
        slug = f"{base_slug}-{counter}"
        counter += 1


async def _domain_name(db: AsyncSession, workspace: Workspace) -> str:
    if not workspace.domain_id:
        return "未分类"
    name = await db.scalar(
        select(LearningDomain.name).where(LearningDomain.id == workspace.domain_id)
    )
    return name or "未分类"


async def _stats(
    db: AsyncSession, workspace_ids: list[str]
) -> dict[str, dict]:
    """按知识库聚合文档数、知识点数、平均掌握度与最近学习时间。"""
    if not workspace_ids:
        return {}
    result = {
        workspace_id: {
            "document_count": 0,
            "knowledge_point_count": 0,
            "learning_progress": 0,
            "last_studied_at": None,
        }
        for workspace_id in workspace_ids
    }
    document_rows = (await db.execute(
        select(Document.workspace_id, func.count(Document.id))
        .where(Document.workspace_id.in_(workspace_ids))
        .group_by(Document.workspace_id)
    )).all()
    for workspace_id, count in document_rows:
        result[workspace_id]["document_count"] = int(count or 0)

    point_rows = (await db.execute(
        select(
            KnowledgePoint.workspace_id,
            func.count(KnowledgePoint.id),
            func.avg(KnowledgePoint.mastery),
        )
        .where(KnowledgePoint.workspace_id.in_(workspace_ids))
        .group_by(KnowledgePoint.workspace_id)
    )).all()
    for workspace_id, count, average in point_rows:
        result[workspace_id]["knowledge_point_count"] = int(count or 0)
        result[workspace_id]["learning_progress"] = (
            round(float(average or 0) * 100) if count else 0
        )

    activity_rows = (await db.execute(
        select(StudyActivity.workspace_id, func.max(StudyActivity.occurred_at))
        .where(
            StudyActivity.workspace_id.in_(workspace_ids),
            StudyActivity.activity_type.in_(LEARNING_ACTIVITY_TYPES),
        )
        .group_by(StudyActivity.workspace_id)
    )).all()
    for workspace_id, last_at in activity_rows:
        result[workspace_id]["last_studied_at"] = last_at
    return result


async def _payload(db: AsyncSession, workspace: Workspace, stats: dict | None = None) -> dict:
    values = stats or (await _stats(db, [workspace.id])).get(workspace.id, {})
    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "slug": workspace.slug,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "document_count": values.get("document_count", 0),
        "knowledge_point_count": values.get("knowledge_point_count", 0),
        "learning_progress": values.get("learning_progress", 0),
        "last_studied_at": values.get("last_studied_at"),
        "learning_goal": workspace.learning_goal or "",
        "learning_status": workspace.learning_status or "not_started",
        "domain": await _domain_name(db, workspace),
        "domain_id": workspace.domain_id,
        "cover_kind": workspace.cover_kind or "none",
        "cover_url": public_image_url("cover", workspace.cover_kind, workspace.cover_value),
        "accent_color": workspace.accent_color,
        "archived": workspace.archived,
    }


async def _resolve_domain(
    db: AsyncSession, user: User, domain_id: Optional[str], fallback_name: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """返回 (domain_id, 兼容 domain 名称)。"""
    if domain_id is not None:
        domain = await owned_domain(db, domain_id, user)
        return domain.id, domain.name
    if fallback_name is not None:
        cleaned = fallback_name.strip()
        if cleaned and cleaned != "未分类":
            existing = (await db.execute(
                select(LearningDomain).where(
                    LearningDomain.user_id == user.id, LearningDomain.name == cleaned
                )
            )).scalar_one_or_none()
            if existing is None:
                existing = LearningDomain(user_id=user.id, name=cleaned)
                db.add(existing)
                await db.flush()
            return existing.id, existing.name
        return None, "未分类"
    return None, None


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    include_archived: bool = Query(False, description="包含已归档知识库"),
    archived_only: bool = Query(False, description="仅返回已归档知识库"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    stmt = select(Workspace).where(Workspace.owner_id == current_user.id)
    if archived_only:
        stmt = stmt.where(Workspace.archived.is_(True))
    elif not include_archived:
        stmt = stmt.where(Workspace.archived.is_(False))
    rows = (await db.execute(
        stmt.order_by(Workspace.created_at.desc())
    )).scalars().all()
    stats = await _stats(db, [row.id for row in rows])
    return [await _payload(db, row, stats.get(row.id)) for row in rows]


@router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    domain_id, domain_name = await _resolve_domain(db, current_user, payload.domain_id, payload.domain)
    cover_kind, cover_value = "none", None
    if payload.cover_url:
        cover_kind = "url"
        cover_value = validate_external_image_url(payload.cover_url, settings)
    unique_slug = await _ensure_unique_slug(db, current_user.id, _slugify(payload.name))
    workspace = Workspace(
        owner_id=current_user.id,
        domain_id=domain_id,
        name=payload.name.strip(),
        description=payload.description or "",
        learning_goal=payload.learning_goal or "",
        domain=domain_name or "未分类",
        learning_status=payload.learning_status or "not_started",
        cover_kind=cover_kind,
        cover_value=cover_value,
        accent_color=payload.accent_color or "#1f7a8c",
        slug=unique_slug,
    )
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)
    logger.info("Created knowledge base '{}' for user '{}'", workspace.id, current_user.id)
    return await _payload(db, workspace)


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    workspace = await owned_workspace(db, workspace_id, current_user)
    return await _payload(db, workspace)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    workspace = await owned_workspace(db, workspace_id, current_user)
    previous_upload = workspace.cover_value if workspace.cover_kind == "upload" else None

    if payload.name is not None:
        workspace.name = payload.name.strip()
        workspace.slug = await _ensure_unique_slug(
            db, current_user.id, _slugify(workspace.name), exclude_id=workspace_id
        )
    if payload.domain_id is not None or payload.domain is not None:
        domain_id, domain_name = await _resolve_domain(
            db, current_user, payload.domain_id, payload.domain
        )
        if domain_id is not None:
            workspace.domain_id = domain_id
        elif payload.domain_id is None and payload.domain is not None:
            workspace.domain_id = None
        if domain_name is not None:
            workspace.domain = domain_name
    if payload.clear_cover:
        workspace.cover_kind = "none"
        workspace.cover_value = None
    elif payload.cover_url is not None:
        workspace.cover_kind = "url"
        workspace.cover_value = validate_external_image_url(payload.cover_url, settings)

    for field in ("description", "learning_goal", "accent_color", "archived", "learning_status"):
        value = getattr(payload, field, None)
        if value is not None:
            setattr(workspace, field, value)

    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    if previous_upload and workspace.cover_kind != "upload":
        delete_media(previous_upload, settings)
    await db.refresh(workspace)
    return await _payload(db, workspace)


@router.post("/{workspace_id}/cover", response_model=WorkspaceResponse)
async def upload_cover(
    workspace_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    """先按当前用户加载知识库，再写入受控封面目录。"""
    workspace = await owned_workspace(db, workspace_id, current_user)
    previous_upload = workspace.cover_value if workspace.cover_kind == "upload" else None
    stored = await store_image(file, "cover", settings=settings)
    workspace.cover_kind = "upload"
    workspace.cover_value = stored.relative_path
    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    if previous_upload and previous_upload != stored.relative_path:
        delete_media(previous_upload, settings)
    return await _payload(db, workspace)


@router.delete("/{workspace_id}/cover", response_model=WorkspaceResponse)
async def clear_cover(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> dict:
    workspace = await owned_workspace(db, workspace_id, current_user)
    previous_upload = workspace.cover_value if workspace.cover_kind == "upload" else None
    workspace.cover_kind = "none"
    workspace.cover_value = None
    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    delete_media(previous_upload, settings)
    return await _payload(db, workspace)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    """删除知识库：先验证所有权，再清理受控文件与向量集合。"""
    workspace = await owned_workspace(db, workspace_id, current_user)
    cover_value = workspace.cover_value if workspace.cover_kind == "upload" else None
    docs = (await db.execute(
        select(Document).where(Document.workspace_id == workspace_id)
    )).scalars().all()
    for document in docs:
        if document.file_path and os.path.isfile(document.file_path):
            try:
                os.remove(document.file_path)
            except OSError:
                logger.warning("Could not remove file for document '{}'", document.id)
    try:
        from app.core.chroma import get_chroma_client

        get_chroma_client().delete_collection(
            name=f"ws_{workspace_id}".replace("-", "_")
        )
    except Exception:
        logger.warning("Vector collection cleanup deferred for workspace '{}'", workspace_id)
    await db.delete(workspace)
    await db.flush()
    delete_media(cover_value, settings)
    logger.info("Deleted knowledge base '{}' for user '{}'", workspace_id, current_user.id)
    return Response(status_code=204)
