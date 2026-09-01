"""Knowledge base import orchestration."""
from __future__ import annotations


class KBImporter:
    """Orchestrates importing content into a knowledge base."""

    @staticmethod
    async def import_file(db, kb_id: str, file_path: str, mime_type: str | None = None) -> dict:
        """Import a single file and trigger indexing."""
        import hashlib
        from pathlib import Path

        path = Path(file_path)
        file_size = path.stat().st_size

        # Trigger Celery task for async processing
        from app.tasks.indexing import index_document
        task = index_document.delay(str(path), kb_id, mime_type)

        return {
            "file_path": str(path),
            "file_name": path.name,
            "file_size": file_size,
            "mime_type": mime_type or "unknown",
            "task_id": task.id,
        }

    @staticmethod
    async def import_url(db, kb_id: str, url: str, title: str | None = None) -> dict:
        """Import a URL and trigger indexing."""
        from app.tasks.indexing import index_url
        task = index_url.delay(url, kb_id, title)
        return {"url": url, "title": title, "task_id": task.id}

    @staticmethod
    async def import_git_repo(
        db, kb_id: str, repo_url: str, branch: str = "main", paths: list[str] | None = None
    ) -> dict:
        """Clone and import a git repository."""
        from app.tasks.git_sync import sync_git_repo
        task = sync_git_repo.delay(repo_url, branch, kb_id, paths)
        return {"repo_url": repo_url, "branch": branch, "task_id": task.id}
