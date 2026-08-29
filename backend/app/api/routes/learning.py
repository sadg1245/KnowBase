"""APIs for the personal learning loop: organise, practise, review and reflect."""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_settings
from app.config import Settings
from app.models.document import Document
from app.models.chat import DocumentChunk
from app.models.learning import Flashcard, KnowledgePoint, QuizQuestion, ReviewLog, StudyActivity, UserProfile
from app.models.workspace import Workspace
from app.services.learning_content import LearningGenerationError, generate_document_learning_content
from app.services.review_service import apply_card_review, schedule_review
from app.schemas.learning import (
    ActivityCreate, AnalyzeRequest, FlashcardCreate, KnowledgePointCreate,
    KnowledgePointMerge, KnowledgePointUpdate, ProfileUpdate, QuizGenerateRequest, QuizSubmitRequest,
    ReviewRequest, WorkspaceLearningUpdate,
)

router = APIRouter(prefix="/learning", tags=["learning"])


def _iso(value):
    return value.isoformat() if value else None


def _point(row: KnowledgePoint) -> dict:
    return {
        "id": row.id, "workspace_id": row.workspace_id, "document_id": row.document_id,
        "title": row.title, "summary": row.summary, "explanation": row.explanation,
        "source_page": row.source_page, "source_heading": row.source_heading,
        "importance": row.importance, "difficulty": row.difficulty,
        "mastery": row.mastery, "tags": row.tags or [], "is_key": row.is_key,
        "mastery_status": row.mastery_status, "created_at": _iso(row.created_at),
    }


def _card(row: Flashcard) -> dict:
    return {
        "id": row.id, "workspace_id": row.workspace_id,
        "knowledge_point_id": row.knowledge_point_id, "front": row.front,
        "back": row.back, "source_label": row.source_label,
        "due_at": _iso(row.due_at), "interval_days": row.interval_days,
        "ease": row.ease, "review_count": row.review_count,
    }


def _quiz(row: QuizQuestion, reveal: bool = False) -> dict:
    data = {
        "id": row.id, "workspace_id": row.workspace_id,
        "knowledge_point_id": row.knowledge_point_id, "question_type": row.question_type,
        "prompt": row.prompt, "options": row.options,
        "explanation": row.explanation, "source_label": row.source_label,
        "attempts": row.attempts, "correct_attempts": row.correct_attempts,
        "last_answer": row.last_answer, "last_correct": row.last_correct,
    }
    if reveal:
        data["answer"] = row.answer
    return data


async def _profile(db: AsyncSession) -> UserProfile:
    result = await db.execute(select(UserProfile).limit(1))
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(display_name="学习者")
        db.add(profile)
        await db.flush()
        await db.refresh(profile)
    return profile


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)) -> dict:
    profile = await _profile(db)
    return {key: getattr(profile, key) for key in (
        "id", "display_name", "daily_goal_minutes", "daily_review_target",
        "preferred_mode", "reminder_time",
    )}


@router.put("/profile")
async def update_profile(payload: ProfileUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    profile = await _profile(db)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, key, value)
    profile.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return await get_profile(db)


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = start_today - timedelta(days=start_today.weekday())
    profile = await _profile(db)

    async def scalar(stmt):
        return (await db.execute(stmt)).scalar() or 0

    workspace_count = await scalar(select(func.count(Workspace.id)).where(Workspace.archived.is_(False)))
    document_count = await scalar(select(func.count(Document.id)))
    point_count = await scalar(select(func.count(KnowledgePoint.id)))
    due_count = await scalar(select(func.count(Flashcard.id)).where(Flashcard.due_at <= now))
    wrong_count = await scalar(select(func.count(QuizQuestion.id)).where(QuizQuestion.last_correct.is_(False)))
    today_seconds = await scalar(select(func.coalesce(func.sum(StudyActivity.duration_seconds), 0)).where(StudyActivity.created_at >= start_today))
    week_seconds = await scalar(select(func.coalesce(func.sum(StudyActivity.duration_seconds), 0)).where(StudyActivity.created_at >= week_start))

    activity_rows = (await db.execute(select(StudyActivity).order_by(StudyActivity.created_at.desc()).limit(8))).scalars().all()
    weak_rows = (await db.execute(select(KnowledgePoint).order_by(KnowledgePoint.mastery.asc(), KnowledgePoint.importance.desc()).limit(5))).scalars().all()
    recent_workspaces = (await db.execute(select(Workspace).where(Workspace.archived.is_(False)).order_by(Workspace.updated_at.desc()).limit(4))).scalars().all()

    # Streak is based on distinct activity dates and intentionally timezone-neutral for now.
    dates = (await db.execute(select(func.date(StudyActivity.created_at)).distinct().order_by(func.date(StudyActivity.created_at).desc()).limit(60))).scalars().all()
    streak = 0
    cursor = start_today.date()
    date_set = {datetime.fromisoformat(str(d)).date() if not hasattr(d, "year") else d for d in dates}
    if cursor not in date_set:
        cursor -= timedelta(days=1)
    while cursor in date_set:
        streak += 1
        cursor -= timedelta(days=1)

    return {
        "profile": {"display_name": profile.display_name, "daily_goal_minutes": profile.daily_goal_minutes, "daily_review_target": profile.daily_review_target},
        "stats": {"workspace_count": workspace_count, "document_count": document_count, "knowledge_point_count": point_count, "due_cards": due_count, "wrong_questions": wrong_count, "today_minutes": round(today_seconds / 60), "week_minutes": round(week_seconds / 60), "streak_days": streak},
        "today_tasks": [
            {"type": "review", "title": "完成今日复习", "count": due_count, "path": "/review"},
            {"type": "mistake", "title": "重做薄弱题目", "count": wrong_count, "path": "/practice?wrong=1"},
        ],
        "weak_points": [_point(row) for row in weak_rows],
        "recent_activities": [{"id": row.id, "type": row.activity_type, "title": row.title, "duration_seconds": row.duration_seconds, "created_at": _iso(row.created_at)} for row in activity_rows],
        "recent_workspaces": [{"id": row.id, "name": row.name, "description": row.description or "", "domain": row.domain, "accent_color": row.accent_color, "learning_goal": row.learning_goal or ""} for row in recent_workspaces],
    }


@router.get("/workspaces/{workspace_id}")
async def workspace_learning_detail(workspace_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Knowledge base not found")
    documents = (await db.execute(select(Document).where(Document.workspace_id == workspace_id).order_by(Document.created_at.desc()))).scalars().all()
    points = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.workspace_id == workspace_id).order_by(KnowledgePoint.importance.desc(), KnowledgePoint.created_at.desc()))).scalars().all()
    activities = (await db.execute(
        select(StudyActivity)
        .where(StudyActivity.workspace_id == workspace_id)
        .order_by(StudyActivity.created_at.desc())
        .limit(8)
    )).scalars().all()
    chunk_rows = (await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.workspace_id == workspace_id)
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )).scalars().all()
    outlines: dict[str, list[dict]] = {}
    outline_seen: dict[str, set[tuple]] = {}
    for chunk in chunk_rows:
        key = (tuple(chunk.section_path or []), chunk.heading, chunk.page_num)
        if key in outline_seen.setdefault(chunk.document_id, set()):
            continue
        outline_seen[chunk.document_id].add(key)
        outlines.setdefault(chunk.document_id, []).append({
            "chunk_id": chunk.id,
            "heading": chunk.heading,
            "heading_level": chunk.heading_level,
            "section_path": list(chunk.section_path or []),
            "page_num": chunk.page_num,
        })
    card_count = (await db.execute(select(func.count(Flashcard.id)).where(Flashcard.workspace_id == workspace_id))).scalar() or 0
    quiz_count = (await db.execute(select(func.count(QuizQuestion.id)).where(QuizQuestion.workspace_id == workspace_id))).scalar() or 0
    mastery = sum(p.mastery for p in points) / len(points) if points else 0
    recommendations: list[dict] = []
    for document in documents:
        if document.status == "failed":
            recommendations.append({"type": "retry_document", "document_id": document.id, "title": f"重新解析 {document.filename}"})
    for document in documents:
        if document.learning_status == "failed":
            recommendations.append({"type": "retry_learning", "document_id": document.id, "title": f"重新生成 {document.filename} 的学习内容"})
    for document in documents:
        if document.status == "ready" and document.learning_status == "not_started":
            recommendations.append({"type": "generate_learning", "document_id": document.id, "title": f"生成 {document.filename} 的学习内容"})
    for point in points:
        if point.is_key and point.mastery_status != "mastered":
            recommendations.append({"type": "review_point", "knowledge_point_id": point.id, "title": f"复习重点：{point.title}"})
    recommendations.append({"type": "continue_chat", "title": "继续学习对话"})
    recommendations = recommendations[:5]

    return {
        "id": workspace.id, "name": workspace.name, "description": workspace.description or "",
        "learning_goal": workspace.learning_goal or "", "domain": workspace.domain,
        "accent_color": workspace.accent_color, "archived": workspace.archived,
        "progress": round(mastery * 100), "card_count": card_count, "quiz_count": quiz_count,
        "documents": [{
            "id": d.id, "filename": d.filename, "file_type": d.file_type,
            "status": d.status, "error_message": d.error_message,
            "chunk_count": d.chunk_count, "summary": d.summary, "outline": d.outline,
            "learning_status": d.learning_status, "learning_error_message": d.learning_error_message,
            "tags": d.tags or [], "chapter_summaries": d.chapter_summaries or [],
            "core_concepts": d.core_concepts or [], "important_terms": d.important_terms or [],
            "common_mistakes": d.common_mistakes or [], "prerequisites": d.prerequisites or [],
            "learning_order": d.learning_order or [], "review_points": d.review_points or [],
            "processed_at": _iso(d.processed_at), "learning_generated_at": _iso(d.learning_generated_at),
            "created_at": _iso(d.created_at), "outline_items": outlines.get(d.id, []),
        } for d in documents],
        "knowledge_points": [_point(row) for row in points],
        "recent_activities": [{
            "id": row.id, "type": row.activity_type, "title": row.title,
            "duration_seconds": row.duration_seconds, "payload": row.payload,
            "created_at": _iso(row.created_at),
        } for row in activities],
        "recommendations": recommendations,
    }


@router.put("/workspaces/{workspace_id}")
async def update_workspace_learning(workspace_id: str, payload: WorkspaceLearningUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Knowledge base not found")
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(workspace, key, value)
    workspace.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return await workspace_learning_detail(workspace_id, db)


def _short_answer_matches(actual: str, expected: str) -> bool:
    """Lenient local check for paraphrased Chinese short answers."""
    if not actual:
        return False
    if actual in expected or expected[:20] in actual:
        return True
    def grams(value: str) -> set[str]:
        clean = re.sub(r"[^\w\u4e00-\u9fff]", "", value.lower())
        return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}
    left, right = grams(actual), grams(expected)
    return len(actual) >= 12 and bool(left) and len(left & right) / len(left) >= .28


@router.post("/workspaces/{workspace_id}/analyze")
async def analyze_workspace(workspace_id: str, payload: AnalyzeRequest, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    workspace = (await db.execute(select(Workspace).where(Workspace.id == workspace_id))).scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Knowledge base not found")
    stmt = select(Document).where(Document.workspace_id == workspace_id, Document.status == "ready")
    if payload.document_id:
        stmt = stmt.where(Document.id == payload.document_id)
    documents = (await db.execute(stmt)).scalars().all()
    if not documents:
        raise HTTPException(400, "没有可整理的已解析资料")

    created = 0
    for document in documents:
        existing = (await db.execute(select(func.count(KnowledgePoint.id)).where(
            KnowledgePoint.document_id == document.id,
        ))).scalar() or 0
        if existing and not payload.regenerate:
            continue
        try:
            material = await generate_document_learning_content(db, document.id, settings)
        except LearningGenerationError as exc:
            document.learning_status = "failed"
            document.learning_error_message = str(exc)
            await db.flush()
            continue
        created += len(material.knowledge_points)

    db.add(StudyActivity(workspace_id=workspace_id, activity_type="organize", title=f"整理了《{workspace.name}》的学习内容", payload={"created_points": created}))
    await db.flush()
    return {"created_points": created, "detail": await workspace_learning_detail(workspace_id, db)}


@router.get("/knowledge-points")
async def list_points(workspace_id: str = Query(...), db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.workspace_id == workspace_id).order_by(KnowledgePoint.importance.desc()))).scalars().all()
    return [_point(row) for row in rows]


@router.post("/knowledge-points", status_code=201)
async def create_point(payload: KnowledgePointCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = KnowledgePoint(**payload.model_dump())
    db.add(row); await db.flush(); await db.refresh(row)
    return _point(row)


@router.put("/knowledge-points/{point_id}")
async def update_point(point_id: str, payload: KnowledgePointUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))).scalar_one_or_none()
    if not row: raise HTTPException(404, "Knowledge point not found")
    values = payload.model_dump(exclude_none=True)
    explicit_status = "mastery_status" in payload.model_fields_set
    for key, value in values.items(): setattr(row, key, value)
    if explicit_status and payload.mastery_status == "mastered":
        row.mastery = 1.0
    elif payload.mastery is not None and not explicit_status:
        row.mastery_status = "mastered" if payload.mastery >= 1 else ("learning" if payload.mastery > 0 else "not_started")
    await db.flush(); return _point(row)


@router.post("/knowledge-points/merge")
async def merge_points(payload: KnowledgePointMerge, db: AsyncSession = Depends(get_db)) -> dict:
    ids = list(dict.fromkeys([payload.target_id, *payload.source_ids]))
    rows = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))).scalars().all()
    by_id = {row.id: row for row in rows}
    target = by_id.get(payload.target_id)
    sources = [by_id.get(point_id) for point_id in payload.source_ids if point_id != payload.target_id]
    if target is None or any(row is None for row in sources):
        raise HTTPException(404, "Knowledge point not found")
    typed_sources = [row for row in sources if row is not None]
    if any(row.workspace_id != target.workspace_id for row in typed_sources):
        raise HTTPException(400, "Knowledge points must belong to the same workspace")

    def unique_text(values: list[str]) -> str:
        return "\n\n".join(dict.fromkeys(value.strip() for value in values if value and value.strip()))

    target.tags = list(dict.fromkeys([*(target.tags or []), *(tag for row in typed_sources for tag in (row.tags or []))]))
    target.summary = unique_text([target.summary, *(row.summary for row in typed_sources)])
    target.explanation = unique_text([target.explanation, *(row.explanation for row in typed_sources)])
    target.importance = max([target.importance, *(row.importance for row in typed_sources)])
    target.difficulty = max([target.difficulty, *(row.difficulty for row in typed_sources)])
    target.mastery = max([target.mastery, *(row.mastery for row in typed_sources)])
    target.is_key = target.is_key or any(row.is_key for row in typed_sources)
    target.mastery_status = "mastered" if target.mastery >= 1 else ("learning" if target.mastery > 0 else target.mastery_status)
    for row in typed_sources:
        await db.delete(row)
    await db.flush()
    return _point(target)


@router.post("/knowledge-points/{point_id}/quiz", status_code=201)
async def point_to_quiz(point_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    point = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))).scalar_one_or_none()
    if not point:
        raise HTTPException(404, "Knowledge point not found")
    label = point.source_heading or (f"第 {point.source_page} 页" if point.source_page else None)
    quiz = QuizQuestion(
        workspace_id=point.workspace_id,
        knowledge_point_id=point.id,
        question_type="short",
        prompt=f"请解释：{point.title}",
        answer=point.explanation or point.summary,
        explanation=point.explanation or point.summary,
        source_label=label,
    )
    db.add(quiz)
    await db.flush()
    await db.refresh(quiz)
    return _quiz(quiz)


@router.delete("/knowledge-points/{point_id}", status_code=200)
async def delete_point(point_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))).scalar_one_or_none()
    if not row: raise HTTPException(404, "Knowledge point not found")
    await db.delete(row)


@router.post("/knowledge-points/{point_id}/card", status_code=201)
async def point_to_card(point_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    point = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))).scalar_one_or_none()
    if not point: raise HTTPException(404, "Knowledge point not found")
    label = point.source_heading or (f"第 {point.source_page} 页" if point.source_page else None)
    card = Flashcard(workspace_id=point.workspace_id, knowledge_point_id=point.id, front=f"什么是“{point.title}”？", back=point.explanation or point.summary, source_label=label)
    db.add(card); await db.flush(); await db.refresh(card)
    return _card(card)


@router.get("/cards")
async def list_cards(workspace_id: str | None = None, due_only: bool = False, db: AsyncSession = Depends(get_db)) -> list[dict]:
    stmt = select(Flashcard)
    if workspace_id: stmt = stmt.where(Flashcard.workspace_id == workspace_id)
    if due_only: stmt = stmt.where(Flashcard.due_at <= datetime.now(timezone.utc))
    rows = (await db.execute(stmt.order_by(Flashcard.due_at.asc()))).scalars().all()
    return [_card(row) for row in rows]


@router.post("/cards", status_code=201)
async def create_card(payload: FlashcardCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = Flashcard(**payload.model_dump()); db.add(row); await db.flush(); await db.refresh(row); return _card(row)


@router.delete("/cards/{card_id}", status_code=200)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = (await db.execute(select(Flashcard).where(Flashcard.id == card_id))).scalar_one_or_none()
    if not row: raise HTTPException(404, "Card not found")
    await db.delete(row)


@router.post("/cards/{card_id}/review")
async def review_card(card_id: str, payload: ReviewRequest, db: AsyncSession = Depends(get_db)) -> dict:
    card = (await db.execute(select(Flashcard).where(Flashcard.id == card_id))).scalar_one_or_none()
    if not card: raise HTTPException(404, "Card not found")
    change = await apply_card_review(db, card, payload.rating, payload.duration_seconds)
    return {"card": _card(card), "change": change}


@router.post("/quizzes/generate")
async def generate_quiz(payload: QuizGenerateRequest, db: AsyncSession = Depends(get_db)) -> list[dict]:
    point_query = select(KnowledgePoint).where(KnowledgePoint.workspace_id == payload.workspace_id)
    if payload.document_ids:
        point_query = point_query.where(KnowledgePoint.document_id.in_(payload.document_ids))
    point_query = point_query.order_by(KnowledgePoint.mastery.asc(), KnowledgePoint.importance.desc()).limit(payload.count)
    points = (await db.execute(point_query)).scalars().all()
    if not points:
        detail = "选中的文件还没有可用于练习的知识点" if payload.document_ids else "请先为知识库生成知识点"
        raise HTTPException(400, detail)
    rows = []
    for idx, point in enumerate(points):
        kind = payload.question_type if payload.question_type != "mixed" else ("true_false" if idx % 3 == 1 else "short")
        if kind == "choice":
            distractors = [p.title for p in points if p.id != point.id][:3]
            options = [point.title] + distractors
            random.shuffle(options)
            prompt, answer = f"下面哪一项最符合这个解释？\n{point.summary}", point.title
        elif kind == "true_false":
            options = ["正确", "错误"]
            prompt, answer = f"判断：{point.summary}", "正确"
        else:
            options = None
            prompt, answer = f"请用自己的话解释：{point.title}", point.explanation or point.summary
        row = QuizQuestion(workspace_id=payload.workspace_id, knowledge_point_id=point.id, question_type=kind, prompt=prompt, options=options, answer=answer, explanation=point.summary, source_label=point.source_heading or (f"第 {point.source_page} 页" if point.source_page else None))
        db.add(row); rows.append(row)
    await db.flush()
    return [_quiz(row) for row in rows]


@router.get("/quizzes")
async def list_quizzes(workspace_id: str | None = None, wrong_only: bool = False, document_ids: list[str] | None = Query(None), db: AsyncSession = Depends(get_db)) -> list[dict]:
    stmt = select(QuizQuestion)
    if workspace_id: stmt = stmt.where(QuizQuestion.workspace_id == workspace_id)
    if document_ids:
        stmt = stmt.join(KnowledgePoint, QuizQuestion.knowledge_point_id == KnowledgePoint.id).where(KnowledgePoint.document_id.in_(document_ids))
    if wrong_only: stmt = stmt.where(QuizQuestion.last_correct.is_(False))
    rows = (await db.execute(stmt.order_by(QuizQuestion.created_at.desc()))).scalars().all()
    return [_quiz(row) for row in rows]


@router.post("/quizzes/{quiz_id}/submit")
async def submit_quiz(quiz_id: str, payload: QuizSubmitRequest, db: AsyncSession = Depends(get_db)) -> dict:
    row = (await db.execute(select(QuizQuestion).where(QuizQuestion.id == quiz_id))).scalar_one_or_none()
    if not row: raise HTTPException(404, "Question not found")
    expected = re.sub(r"\s", "", row.answer.lower())
    actual = re.sub(r"\s", "", payload.answer.lower())
    correct = actual == expected if row.question_type in {"choice", "true_false"} else _short_answer_matches(actual, expected)
    row.attempts += 1; row.correct_attempts += int(correct); row.last_answer = payload.answer; row.last_correct = correct
    if row.knowledge_point_id:
        point = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == row.knowledge_point_id))).scalar_one_or_none()
        if point: point.mastery = max(0, min(1, point.mastery + (.12 if correct else -.08)))
    db.add(StudyActivity(workspace_id=row.workspace_id, activity_type="quiz", title="完成了一道练习", duration_seconds=60, payload={"correct": correct}))
    await db.flush()
    return {"correct": correct, "reference_answer": row.answer, "explanation": row.explanation, "source_label": row.source_label, "question": _quiz(row, reveal=True)}


@router.post("/activities", status_code=201)
async def create_activity(payload: ActivityCreate, db: AsyncSession = Depends(get_db)) -> dict:
    row = StudyActivity(**payload.model_dump()); db.add(row); await db.flush(); await db.refresh(row)
    return {"id": row.id, "created_at": _iso(row.created_at)}


@router.get("/report")
async def learning_report(days: int = Query(7, ge=1, le=365), db: AsyncSession = Depends(get_db)) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    activities = (await db.execute(select(StudyActivity).where(StudyActivity.created_at >= since).order_by(StudyActivity.created_at.asc()))).scalars().all()
    reviews = (await db.execute(select(ReviewLog).where(ReviewLog.reviewed_at >= since))).scalars().all()
    quizzes = (await db.execute(select(QuizQuestion).where(QuizQuestion.attempts > 0))).scalars().all()
    points = (await db.execute(select(KnowledgePoint))).scalars().all()
    daily: dict[str, dict] = {}
    for row in activities:
        key = row.created_at.date().isoformat()
        daily.setdefault(key, {"date": key, "minutes": 0, "activities": 0})
        daily[key]["minutes"] += round(row.duration_seconds / 60, 1); daily[key]["activities"] += 1
    accuracy = sum(q.correct_attempts for q in quizzes) / sum(q.attempts for q in quizzes) if sum(q.attempts for q in quizzes) else 0
    mastered = sum(1 for p in points if p.mastery >= .8)
    return {"days": days, "total_minutes": round(sum(a.duration_seconds for a in activities) / 60), "activity_count": len(activities), "review_count": len(reviews), "quiz_accuracy": round(accuracy * 100), "mastered_points": mastered, "total_points": len(points), "daily": list(daily.values()), "suggestion": "优先复习掌握度较低的知识点，并在复习后用自己的话复述一次。" if points else "先导入一份资料并生成知识点，开始第一轮学习。"}


@router.get("/export")
async def export_learning_data(db: AsyncSession = Depends(get_db)) -> dict:
    """Portable JSON export of learning metadata; original files remain downloadable separately."""
    profile = await _profile(db)
    workspaces = (await db.execute(select(Workspace))).scalars().all()
    documents = (await db.execute(select(Document))).scalars().all()
    points = (await db.execute(select(KnowledgePoint))).scalars().all()
    cards = (await db.execute(select(Flashcard))).scalars().all()
    quizzes = (await db.execute(select(QuizQuestion))).scalars().all()
    activities = (await db.execute(select(StudyActivity))).scalars().all()
    return {
        "exported_at": _iso(datetime.now(timezone.utc)), "format_version": 1,
        "profile": {"display_name": profile.display_name, "daily_goal_minutes": profile.daily_goal_minutes, "daily_review_target": profile.daily_review_target, "preferred_mode": profile.preferred_mode, "reminder_time": profile.reminder_time},
        "knowledge_bases": [{"id": w.id, "name": w.name, "description": w.description, "learning_goal": w.learning_goal, "domain": w.domain, "created_at": _iso(w.created_at)} for w in workspaces],
        "documents": [{"id": d.id, "workspace_id": d.workspace_id, "filename": d.filename, "file_type": d.file_type, "summary": d.summary, "outline": d.outline, "created_at": _iso(d.created_at)} for d in documents],
        "knowledge_points": [_point(p) for p in points], "flashcards": [_card(c) for c in cards],
        "quizzes": [_quiz(q, reveal=True) for q in quizzes],
        "activities": [{"id": a.id, "workspace_id": a.workspace_id, "type": a.activity_type, "title": a.title, "duration_seconds": a.duration_seconds, "payload": a.payload, "created_at": _iso(a.created_at)} for a in activities],
    }
