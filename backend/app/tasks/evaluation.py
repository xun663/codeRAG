"""Evaluation run tasks."""
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True)
def run_evaluation_task(self, dataset_id: str, config: dict | None = None) -> dict:
    """Run evaluation as a Celery task."""
    import asyncio
    from app.db.session import async_session_factory
    from app.core.evaluation.dataset_service import EvalDatasetService

    async def _run():
        async with async_session_factory() as db:
            service = EvalDatasetService()
            from uuid import UUID
            result = await service.run_evaluation(db, UUID(dataset_id), config or {})
            await db.commit()
            return result

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()
