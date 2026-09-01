"""Celery application configuration."""
from __future__ import annotations

from celery import Celery

from app.config import settings


# ── Monkey-patch redis-py to use RESP2 (compat with Redis 3.x for Windows) ──
# Redis 3.x for Windows doesn't support the HELLO command needed for RESP3.
# Patch both sync and async Connection classes so that kombu's internal pools
# and any direct redis usage both default to protocol 2.


def _patch_redis_init():
    try:
        import redis.connection as _redis_sync
        import redis.asyncio.connection as _redis_async
    except ImportError:
        return  # Redis not installed, skip patch

    for mod in (_redis_sync, _redis_async):
        _orig = mod.Connection.__init__

        def _make_patched(orig_fn):
            def _patched(self, **kwargs):
                kwargs.setdefault("protocol", 2)
                orig_fn(self, **kwargs)
            return _patched

        mod.Connection.__init__ = _make_patched(_orig)


_patch_redis_init()


celery_app = Celery(
    "coderag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.indexing",
        "app.tasks.git_sync",
        "app.tasks.evaluation",
        "app.tasks.exercise_generation",
        "app.tasks.quality_check",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 关键：任务默认路由到 default 队列（start_all.sh 启动 worker 用 --queues=default）。
    # 不设置时 Celery 默认发到名为 "celery" 的队列，与 worker 监听不匹配导致任务永不消费。
    task_default_queue="default",
    task_default_exchange="default",
    task_default_routing_key="default",
)
