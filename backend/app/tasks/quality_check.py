"""Celery task for automated RAG quality check (auto quality gate).

把耗时的 AutoQualityGate.run_check（多轮 LLM 出题 + 检索，数分钟）移出
HTTP 请求路径：单 worker 下同步端点会阻塞所有其他请求。任务入队后立即
返回 task_id，前端轮询状态。

两个独立进程的坑（都处理了）：
  1. 事件循环：celery --pool=solo 每次任务新建事件循环，共享 SQLAlchemy
     async engine 的连接池是 loop 绑定的，复用会报 "Future attached to a
     different loop" → 每任务创建独立 engine 并 dispose。
  2. 运行时 embedding 配置：celery worker 无 app lifespan，默认静态配置
     是 384 维 all-MiniLM，与生产 1024 维集合维度不匹配 → 任务开始前从
     DB 预热运行时配置（同 gt_annotate_helper 的做法）。
"""
from __future__ import annotations

import asyncio
import logging

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=1, track_started=True)
def run_quality_check_task(self, kb_id: str, rounds: int = 3,
                           chunks_per_doc: int = 3, questions_per_chunk: int = 2) -> dict:
    """Run the automated quality check in the background."""
    try:
        report = _run_quality_check(kb_id, rounds, chunks_per_doc, questions_per_chunk)
        logger.info("Auto quality check done for KB '%s': status=%s",
                    kb_id, report.get("status"))
        return {"status": "completed", "kb_id": kb_id, "report": report}
    except Exception as exc:
        logger.error("Auto quality check failed for KB '%s': %s", kb_id, exc)
        self.retry(exc=exc, countdown=60)
        return {"status": "failed", "kb_id": kb_id, "error": str(exc)}


def _run_quality_check(kb_id: str, rounds: int, chunks_per_doc: int,
                       questions_per_chunk: int) -> dict:
    """Execute the async check in a fresh event loop with a task-scoped engine."""
    async def _run():
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.config import settings

        # 每任务独立 engine：连接池不跨事件循环复用（避免 asyncmy Future 绑定旧 loop）
        engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await _warm_embedding_config(factory)

            from app.core.evaluation.auto_gate import AutoQualityGate

            async with factory() as db:
                report = await AutoQualityGate.run_check(
                    db, kb_id,
                    rounds=rounds,
                    chunks_per_doc=chunks_per_doc,
                    questions_per_chunk=questions_per_chunk,
                )
                await db.commit()
                return report
        finally:
            await engine.dispose()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


async def _warm_embedding_config(factory) -> None:
    """Load admin-configured runtime embedding config into the process cache.

    celery worker 是独立进程、无 app lifespan，启动时不会像 API 进程那样加载
    system_config 里的 embedding 配置；默认回退到静态 384 维模型，与生产
    1024 维集合维度不匹配。这里从 DB 读配置并设置（同 gt_annotate_helper）。
    """
    from app.core.monitoring.config_manager import ConfigManager, EMBEDDING_CONFIG_KEY
    from app.embedding.factory import clear_embedding_model_cache
    from app.embedding.runtime_config import set_runtime_embedding_config
    from app.llm.crypto import decrypt

    try:
        async with factory() as db:
            cfg = await ConfigManager.get_config(db, EMBEDDING_CONFIG_KEY)
        if cfg and cfg.config_value:
            v = cfg.config_value
            set_runtime_embedding_config({
                "provider": v.get("provider", "openai"),
                "base_url": v.get("base_url", ""),
                "model": v.get("model", ""),
                "api_key": decrypt(v.get("api_key_encrypted", "")),
                "dimension": int(v.get("dimension") or 1024),
            })
            clear_embedding_model_cache()
            logger.info("Embedding runtime config warmed (provider=%s model=%s)",
                        v.get("provider"), v.get("model"))
    except Exception as exc:
        logger.warning("Failed to warm embedding runtime config: %s", exc)
