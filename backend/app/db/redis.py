"""Redis client (optional, lazy init)."""
from __future__ import annotations

from app.config import settings

_redis_client = None


def get_redis_client():
    """Get or create the async Redis client singleton (lazy, thread-safe)."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not settings.redis_url:
        return None
    try:
        # Ensure RESP2 for Redis 3.x compat (same patch as celery_app.py)
        import redis.asyncio as aioredis
        import redis.asyncio.connection as _conn

        _orig_init = _conn.Connection.__init__

        def _patched_init(self, **kwargs):
            kwargs.setdefault("protocol", 2)
            _orig_init(self, **kwargs)

        _conn.Connection.__init__ = _patched_init

        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    except Exception:
        _redis_client = None
    return _redis_client


async def get_redis():
    """FastAPI dependency for Redis client. Returns None if not configured."""
    return get_redis_client()
