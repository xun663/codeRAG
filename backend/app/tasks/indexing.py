"""Document indexing Celery tasks."""
from __future__ import annotations

from pathlib import Path

from app.tasks.celery_app import celery_app
from app.core.documents.pipeline import DocumentPipeline


@celery_app.task(bind=True, max_retries=3)
def index_document(self, file_path: str, kb_id: str, mime_type: str | None = None) -> dict:
    """Index a single document file."""
    try:
        pipeline = DocumentPipeline()
        result = pipeline.process_file_sync(file_path, kb_id, mime_type)
        return {"status": "completed", "file": file_path, "chunks": len(result["chunks"])}
    except Exception as e:
        self.retry(exc=e, countdown=60)
        return {"status": "failed", "file": file_path, "error": str(e)}


@celery_app.task(bind=True, max_retries=3)
def index_url(self, url: str, kb_id: str, title: str | None = None) -> dict:
    """Index content from a URL."""
    try:
        pipeline = DocumentPipeline()
        result = pipeline.process_url_sync(url, kb_id, title)
        return {"status": "completed", "url": url, "chunks": len(result["chunks"])}
    except Exception as e:
        self.retry(exc=e, countdown=120)
        return {"status": "failed", "url": url, "error": str(e)}


@celery_app.task
def rebuild_kb_index(kb_id: str) -> dict:
    """Rebuild entire knowledge base index."""
    from app.vector_store.factory import get_vector_store

    pipeline = DocumentPipeline()
    store = get_vector_store()

    # Delete and recreate collection
    store.delete_collection_sync(f"kb_{kb_id}")
    store.create_collection_sync(f"kb_{kb_id}")

    # Re-index all documents
    # In production, this would iterate over all documents in the KB
    return {"status": "rebuilding", "kb_id": kb_id}
