"""RAG 检索端点（设计文档 §22.1）。

`POST /api/rag/practice` 给练习页提供「资料原题」：按知识点与难度检索
`content_type="question"` 的 chunk，解答（solution）与纯答案（answer）不进入结果集。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.chat import DocumentChunk
from app.models.learning import KnowledgePoint
from app.models.user import User
from app.schemas.rag import (
    PracticeQuestionItem,
    PracticeQuestionsRequest,
    PracticeQuestionsResponse,
)
from app.services.ownership import owned_workspace


router = APIRouter(tags=["rag"])

PRACTICE_QUESTION_TYPES = ("question",)
PRACTICE_EXCLUDED_TYPES = ("solution", "answer")
PRACTICE_QUESTION_CHUNK_LEVEL = "child"


async def _unit_ids_for_points(
    db: AsyncSession,
    workspace_id: str,
    knowledge_point_ids: list[str],
) -> list[str]:
    """把知识点收敛成它所属的知识单元；未知或跨库的 id 自然落空（fail-closed）。"""
    rows = (await db.execute(
        select(KnowledgePoint.unit_id).where(
            KnowledgePoint.workspace_id == workspace_id,
            KnowledgePoint.id.in_(knowledge_point_ids),
            KnowledgePoint.unit_id.is_not(None),
        )
    )).scalars().all()
    return [unit_id for unit_id in rows if unit_id]


def _serialize(chunk: DocumentChunk) -> PracticeQuestionItem:
    return PracticeQuestionItem(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        source_file=chunk.source_file or "",
        page_num=chunk.page_num,
        heading=chunk.heading,
        content=chunk.content,
        content_type=chunk.content_type or "question",
        difficulty=chunk.difficulty,
        parent_id=chunk.parent_id,
        unit_id=chunk.unit_id,
    )


@router.post("/rag/practice", response_model=PracticeQuestionsResponse)
async def practice_questions(
    payload: PracticeQuestionsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PracticeQuestionsResponse:
    """检索资料原题；练习语境下不返回答案与解答。"""
    await owned_workspace(db, payload.workspace_id, current_user)

    clauses = [
        DocumentChunk.workspace_id == payload.workspace_id,
        DocumentChunk.chunk_level == PRACTICE_QUESTION_CHUNK_LEVEL,
        DocumentChunk.content_type.in_(PRACTICE_QUESTION_TYPES),
    ]
    if payload.document_ids:
        clauses.append(DocumentChunk.document_id.in_(payload.document_ids))
    if payload.knowledge_point_ids:
        unit_ids = await _unit_ids_for_points(db, payload.workspace_id, payload.knowledge_point_ids)
        if not unit_ids:
            return PracticeQuestionsResponse(
                items=[],
                total=0,
                excluded_content_types=list(PRACTICE_EXCLUDED_TYPES),
                reasons=["knowledge_points_have_no_question_units"],
            )
        clauses.append(DocumentChunk.unit_id.in_(unit_ids))
    if payload.difficulty_min is not None:
        clauses.append(DocumentChunk.difficulty >= payload.difficulty_min)
    if payload.difficulty_max is not None:
        clauses.append(DocumentChunk.difficulty <= payload.difficulty_max)

    total = await db.scalar(select(func.count()).select_from(DocumentChunk).where(*clauses))
    rows = (await db.execute(
        select(DocumentChunk)
        .where(*clauses)
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index, DocumentChunk.id)
        .limit(payload.limit)
    )).scalars().all()

    return PracticeQuestionsResponse(
        items=[_serialize(chunk) for chunk in rows],
        total=int(total or 0),
        excluded_content_types=list(PRACTICE_EXCLUDED_TYPES),
        reasons=["practice_mode_excludes_answers"],
    )
