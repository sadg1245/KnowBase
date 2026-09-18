"""Compatibility and follow-up workflows; scoring remains in assessment_service."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.assessment import LearningTask, MistakeRecord, QuizAttempt, QuizRun, QuizSet
from app.models.document import Document
from app.models.learning import KnowledgePoint, QuizQuestion, StudyActivity
from app.services import assessment_service as assessment
from app.services.ownership import workspace_owner_id
from app.services.weakness_service import recalculate_knowledge_point, upsert_weak_learning_tasks


def serialize_row(row):
    """Portable column values, never relationships or authentication settings."""
    return {column.name: (assessment._iso(value) if isinstance(value, datetime) else value)
            for column in row.__table__.columns for value in [getattr(row, column.name)]}


async def set_view(db, quiz_set_id, run=None):
    paper = await assessment._quiz_set(db, quiz_set_id)
    questions = (await db.execute(select(QuizQuestion).where(QuizQuestion.quiz_set_id == paper.id))).scalars().all()
    if run is None:
        run = (await db.execute(select(QuizRun).where(QuizRun.quiz_set_id == paper.id, QuizRun.question_ids.is_(None))
            .order_by(QuizRun.round_number.desc()).limit(1))).scalar_one_or_none()
    attempts = [] if run is None else (await db.execute(select(QuizAttempt).where(QuizAttempt.quiz_run_id == run.id)
        .order_by(QuizAttempt.submitted_at, QuizAttempt.id))).scalars().all()
    payload = assessment.serialize_quiz_set(paper, questions=questions, run=run, attempts=attempts)
    payload["latest_run"] = assessment.serialize_quiz_run(run, attempts=attempts) if run else None
    return payload


async def run_view(db, run):
    payload = assessment.serialize_quiz_run(run)
    payload["quiz_set"] = await set_view(db, run.quiz_set_id, run)
    payload["attempts"] = payload["quiz_set"]["latest_run"]["attempts"]
    return payload


def normalize_legacy_question(question):
    question.question_type = {"choice": "single_choice", "short": "short_answer"}.get(question.question_type, question.question_type)
    if question.answer_payload is None:
        question.answer_payload = question.answer
    if question.question_type == "short_answer" and not question.grading_rubric:
        question.grading_rubric = {"key_points": [question.answer]}


async def ensure_chat_mistake(db, question, sources):
    normalize_legacy_question(question)
    question.source_snapshot = list(sources or [])
    if question.document_id is None:
        for source in question.source_snapshot:
            document_id = source.get("document_id") if isinstance(source, dict) else None
            document = await db.get(Document, document_id) if document_id else None
            if document is not None and document.workspace_id == question.workspace_id:
                question.document_id = document.id
                break
    record = (await db.execute(select(MistakeRecord).where(MistakeRecord.question_id == question.id))).scalar_one_or_none()
    if record is None:
        record = MistakeRecord(question_id=question.id, workspace_id=question.workspace_id,
            knowledge_point_id=question.knowledge_point_id, correct_answer_snapshot=question.answer_payload,
            source_snapshot=question.source_snapshot, mastery_status="unresolved")
        db.add(record)
    await db.flush()
    return record


async def standalone_submission(db, question_id, payload, settings, *, is_redo=False):
    """Reuse original IDs; attach orphan questions once, then use ordinary runs/grades."""
    async with assessment._process_lock(db, "question", question_id):
        await assessment._clean_transaction(db)
        try:
            await assessment._begin_write_transaction(db)
            question = await assessment._locked_question(db, question_id)
            normalize_legacy_question(question)
            if question.quiz_set_id is None:
                paper = QuizSet(workspace_id=question.workspace_id, title="Legacy practice", question_count=1,
                    question_types=[question.question_type], status="ready", generation_model="legacy",
                    knowledge_point_ids=[question.knowledge_point_id] if question.knowledge_point_id else [],
                    document_ids=[question.document_id] if question.document_id else [])
                db.add(paper)
                await db.flush()
                question.quiz_set_id = paper.id
            paper_id = question.quiz_set_id
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    run = await assessment.create_quiz_run(db, paper_id, answer_mode="sequential", question_ids=[question_id])
    await assessment.start_quiz_run(db, run.id)
    attempt = await assessment.submit_question(db, run.id, question_id, payload, settings, is_redo=is_redo)
    return attempt


async def legacy_submission(db, question_id, payload, settings):
    question = await db.get(QuizQuestion, question_id)
    if question is None:
        raise assessment.AssessmentNotFoundError("Question not found")
    paper = await db.get(QuizSet, question.quiz_set_id) if question.quiz_set_id else None
    if paper and paper.generation_model != "legacy":
        run = (await db.execute(select(QuizRun).where(QuizRun.quiz_set_id == paper.id, QuizRun.question_ids.is_(None))
            .order_by(QuizRun.round_number.desc()).limit(1))).scalar_one_or_none()
        if run is None:
            raise assessment.AssessmentStateError("Start this quiz set using the assessment API")
        return await assessment.submit_question(db, run.id, question.id, payload, settings)
    return await standalone_submission(db, question_id, payload, settings)


async def complete_task(db, task_id):
    initial = await db.get(LearningTask, task_id)
    if initial is None:
        raise assessment.AssessmentNotFoundError("Learning task not found")
    namespace, entity_id = ("point", initial.knowledge_point_id) if initial.knowledge_point_id else ("task", task_id)
    async with assessment._process_lock(db, namespace, entity_id):
        await assessment._clean_transaction(db)
        try:
            await assessment._begin_write_transaction(db)
            task = (await db.execute(select(LearningTask).where(LearningTask.id == task_id)
                .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
            if task is None:
                raise assessment.AssessmentNotFoundError("Learning task not found")
            if task.status == "completed":
                await db.commit()
                return task
            if task.status != "pending":
                raise assessment.AssessmentStateError("Only pending tasks can be completed")
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
            db.add(StudyActivity(
                user_id=await workspace_owner_id(db, task.workspace_id),
                workspace_id=task.workspace_id, activity_type="learning_task",
                title=task.title, duration_seconds=0, payload={"task_id": task.id, "knowledge_point_id": task.knowledge_point_id}))
            await db.flush()
            if task.knowledge_point_id:
                await recalculate_knowledge_point(db, task.knowledge_point_id)
            await db.commit()
            from app.services.learner_profile import invalidate_workspace_profile

            await invalidate_workspace_profile(db, task.workspace_id)
            return task
        except Exception:
            await db.rollback()
            raise


async def recalculate_scope(db, workspace_id=None, document_id=None, knowledge_point_id=None):
    # Explicit IDs are validated rather than silently producing an empty scope.
    if workspace_id:
        await assessment._workspace(db, workspace_id)
    if document_id:
        document = await db.get(Document, document_id)
        if document is None:
            raise assessment.AssessmentNotFoundError("Document not found")
        if workspace_id and document.workspace_id != workspace_id:
            raise assessment.AssessmentScopeError("Document is outside the workspace")
    if knowledge_point_id:
        point = await db.get(KnowledgePoint, knowledge_point_id)
        if point is None:
            raise assessment.AssessmentNotFoundError("Knowledge point not found")
        if (workspace_id and point.workspace_id != workspace_id) or (document_id and point.document_id != document_id):
            raise assessment.AssessmentScopeError("Knowledge point is outside the selected scope")
    query = select(KnowledgePoint)
    if workspace_id:
        query = query.where(KnowledgePoint.workspace_id == workspace_id)
    if document_id:
        query = query.where(KnowledgePoint.document_id == document_id)
    if knowledge_point_id:
        query = query.where(KnowledgePoint.id == knowledge_point_id)
    ids = list((await db.execute(query.with_only_columns(KnowledgePoint.id).order_by(KnowledgePoint.id))).scalars())
    await assessment._clean_transaction(db)
    for point_id in ids:
        async with assessment._process_lock(db, "point", point_id):
            try:
                await assessment._begin_write_transaction(db)
                point = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id).with_for_update())).scalar_one_or_none()
                if point is not None:
                    state = await recalculate_knowledge_point(db, point_id)
                    await upsert_weak_learning_tasks(db, state)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
    return ids
