"""Celery task for background exercise generation.

Moves the long-running ``ExerciseService.generate_for_kb`` call out of
the HTTP request path so users are not blocked waiting for LLM calls.
"""
from __future__ import annotations

import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=1, track_started=True)
def generate_exercises_task(self, kb_id: str, limit: int | None = None) -> dict:
    """Batch-generate exercises for a knowledge base (async wrapper)."""
    try:
        result = _run_generate(kb_id, limit)
        logger.info("Generated exercises for KB '%s': %s", kb_id, result)
        return {"status": "completed", "kb_id": kb_id, **result}
    except Exception as exc:
        logger.error("Exercise generation failed for KB '%s': %s", kb_id, exc)
        self.retry(exc=exc, countdown=60)
        return {"status": "failed", "kb_id": kb_id, "error": str(exc)}


def _run_generate(kb_id: str, limit: int | None) -> dict:
    """Execute the async generation in a fresh event loop."""
    async def _run():
        from app.db.session import async_session_factory
        from app.services.exercise_service import ExerciseService

        async with async_session_factory() as db:
            result = await ExerciseService.generate_for_kb(
                db, kb_id, limit=limit,
            )
            await db.commit()
            return result

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
