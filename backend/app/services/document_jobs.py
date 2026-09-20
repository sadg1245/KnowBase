"""Celery dispatch boundaries for document processing and learning generation."""

from app.models.document import Document


def enqueue_document_processing(document: Document) -> None:
    """Queue parsing after its processing state has been committed."""
    from app.collector.tasks import process_document_task

    process_document_task.delay(
        document_id=document.id,
        file_path=document.file_path,
        file_type=document.file_type,
        workspace_id=document.workspace_id,
    )


def enqueue_learning_generation(
    document_id: str, *, overwrite_tags: bool = False, force: bool = False
) -> None:
    """Queue learning-material generation after parsing is durably ready."""
    from app.collector.tasks import generate_learning_content_task

    generate_learning_content_task.delay(
        document_id=document_id, overwrite_tags=overwrite_tags, force=force
    )


def enqueue_document_enrichment(document_id: str) -> None:
    """Queue background enrichment (summary / question vectors) after a document is ready."""
    from app.collector.tasks import enrich_document_task

    enrich_document_task.delay(document_id=document_id)
