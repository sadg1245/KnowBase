"""用户自有的学习领域 CRUD。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import LearningDomain, User
from app.models.workspace import Workspace
from app.schemas.account import (
    LearningDomainCreate,
    LearningDomainResponse,
    LearningDomainUpdate,
)
from app.services.ownership import owned_domain


router = APIRouter(prefix="/learning-domains", tags=["learning domains"])


def _payload(row: LearningDomain, workspace_count: int = 0) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "color": row.color,
        "workspace_count": workspace_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("", response_model=list[LearningDomainResponse])
async def list_domains(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    counts = dict((await db.execute(
        select(Workspace.domain_id, func.count(Workspace.id))
        .where(Workspace.owner_id == current_user.id, Workspace.domain_id.is_not(None))
        .group_by(Workspace.domain_id)
    )).all())
    rows = (await db.execute(
        select(LearningDomain)
        .where(LearningDomain.user_id == current_user.id)
        .order_by(LearningDomain.name.asc())
    )).scalars().all()
    return [_payload(row, int(counts.get(row.id, 0))) for row in rows]


@router.post("", response_model=LearningDomainResponse, status_code=201)
async def create_domain(
    payload: LearningDomainCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "领域名称不能为空")
    row = LearningDomain(
        user_id=current_user.id,
        name=name,
        description=(payload.description or "").strip(),
        color=payload.color or "#1f7a8c",
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "同一用户内领域名称必须唯一") from exc
    await db.refresh(row)
    return _payload(row)


@router.patch("/{domain_id}", response_model=LearningDomainResponse)
async def update_domain(
    domain_id: str,
    payload: LearningDomainUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    row = await owned_domain(db, domain_id, current_user)
    values = payload.model_dump(exclude_none=True)
    if "name" in values:
        values["name"] = str(values["name"]).strip()
        if not values["name"]:
            raise HTTPException(422, "领域名称不能为空")
    if "description" in values:
        values["description"] = (values["description"] or "").strip()
    for key, value in values.items():
        setattr(row, key, value)
    row.updated_at = datetime.now(timezone.utc)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "同一用户内领域名称必须唯一") from exc
    await db.refresh(row)
    return _payload(row)


@router.delete("/{domain_id}", status_code=204)
async def delete_domain(
    domain_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """删除领域只把所属知识库的 domain_id 置空，不删除知识库。"""
    row = await owned_domain(db, domain_id, current_user)
    await db.execute(
        update(Workspace)
        .where(Workspace.domain_id == row.id, Workspace.owner_id == current_user.id)
        .values(domain_id=None, updated_at=datetime.now(timezone.utc))
    )
    await db.delete(row)
    await db.flush()
    return Response(status_code=204)
