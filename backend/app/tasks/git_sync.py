"""Git repository sync tasks."""
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, max_retries=2)
def sync_git_repo(self, repo_url: str, branch: str, kb_id: str, paths: list[str] | None = None) -> dict:
    """Clone and index a Git repository."""
    import tempfile
    import os

    try:
        import git
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir, branch=branch, depth=1)
            files_indexed = 0

            for root, _, files in os.walk(tmpdir):
                # Skip .git directory
                if ".git" in root:
                    continue
                for file in files:
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, tmpdir)

                    # Filter by specified paths
                    if paths and not any(rel_path.startswith(p) for p in paths):
                        continue

                    # Skip binary and large files
                    if _should_skip(file_path):
                        continue

                    # Trigger indexing
                    from app.tasks.indexing import index_document
                    index_document.delay(str(file_path), kb_id)
                    files_indexed += 1

            return {"status": "completed", "repo": repo_url, "files_indexed": files_indexed}
    except Exception as e:
        self.retry(exc=e, countdown=300)
        return {"status": "failed", "repo": repo_url, "error": str(e)}


def _should_skip(file_path: str) -> bool:
    """Check if file should be skipped."""
    import os
    skip_extensions = {".exe", ".dll", ".so", ".bin", ".png", ".jpg", ".jpeg",
                       ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot",
                       ".mp4", ".mp3", ".zip", ".tar", ".gz", ".7z"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext in skip_extensions:
        return True
    if os.path.getsize(file_path) > 10 * 1024 * 1024:  # 10MB
        return True
    return False
