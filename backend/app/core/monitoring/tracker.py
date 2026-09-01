"""Metrics tracker for monitoring."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.conversation import Conversation, Message
from app.models.document import Document
from app.models.feedback import FeedbackDetail
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User


class MetricsTracker:
    """Track and report system metrics."""

    @staticmethod
    def get_metrics() -> dict:
        """Get current Prometheus-style metrics."""
        return {
            "status": "ok",
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        }

    @staticmethod
    async def get_latency_stats(db: AsyncSession) -> dict:
        """Get API latency statistics."""
        result = await db.execute(
            select(
                func.avg(Message.latency_ms),
                func.min(Message.latency_ms),
                func.max(Message.latency_ms),
                func.count(Message.id),
            ).where(Message.latency_ms.isnot(None))
        )
        avg, min_val, max_val, count = result.one()

        return {
            "avg_ms": round(float(avg or 0), 2),
            "min_ms": int(min_val or 0),
            "max_ms": int(max_val or 0),
            "total_requests": count,
        }

    @staticmethod
    async def get_token_stats(db: AsyncSession) -> dict:
        """Get token usage statistics."""
        result = await db.execute(
            select(
                func.sum(Message.prompt_tokens),
                func.sum(Message.completion_tokens),
                func.count(Message.id),
            ).where(Message.prompt_tokens.isnot(None))
        )
        prompt_sum, completion_sum, count = result.one()

        return {
            "total_prompt": int(prompt_sum or 0),
            "total_completion": int(completion_sum or 0),
            "total_requests": count,
            "avg_per_request": int((prompt_sum + completion_sum) / count) if count else 0,
        }

    @staticmethod
    async def get_vector_db_health() -> dict:
        """Get vector database health status."""
        from app.vector_store.factory import get_vector_store
        try:
            store = get_vector_store()
            stats = await store.get_collection_stats("default")
            return {"status": "healthy", **stats}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Dashboard aggregation ───────────────────────────────────

    @staticmethod
    async def get_kb_storage_stats(db: AsyncSession) -> list[dict]:
        """Per-KB capacity: DB counters vs real ChromaDB vector counts."""
        from app.vector_store.factory import get_vector_store

        from app.models.document import DocumentChunk

        kbs = (
            (await db.execute(select(KnowledgeBase))).scalars().all()
        )
        # Live-count DB chunks per KB (counters may be stale)
        chunk_counts = dict(
            (await db.execute(
                select(DocumentChunk.kb_id, func.count(DocumentChunk.id)).group_by(DocumentChunk.kb_id)
            )).all()
        )
        doc_counts = dict(
            (await db.execute(
                select(Document.kb_id, func.count(Document.id)).group_by(Document.kb_id)
            )).all()
        )

        # ChromaDB vector counts per KB collection
        try:
            store = get_vector_store()
            vector_counts = {}
            for kb in kbs:
                coll = f"kb_{kb.id}"
                try:
                    stats = await store.get_collection_stats(coll)
                    vector_counts[str(kb.id)] = stats.get("count", 0)
                except Exception:
                    vector_counts[str(kb.id)] = 0
        except Exception:
            vector_counts = {}

        return [
            {
                "name": kb.name,
                "docs": doc_counts.get(kb.id, kb.doc_count or 0),
                "chunks": chunk_counts.get(kb.id, kb.chunk_count or 0),
                "vectordb_chunks": vector_counts.get(str(kb.id), 0),
            }
            for kb in kbs
        ]

    @staticmethod
    async def get_model_distribution(db: AsyncSession) -> list[dict]:
        """LLM usage grouped by provider/model."""
        result = await db.execute(
            select(
                Message.llm_provider,
                Message.llm_model,
                func.count(Message.id),
            )
            .where(Message.llm_provider.isnot(None))
            .group_by(Message.llm_provider, Message.llm_model)
            .order_by(func.count(Message.id).desc())
        )
        return [
            {"provider": p, "model": m, "count": cnt}
            for p, m, cnt in result.all()
        ]

    @staticmethod
    async def get_rating_summary(db: AsyncSession) -> dict:
        """User feedback rating summary + distribution."""
        result = await db.execute(
            select(
                func.avg(FeedbackDetail.rating),
                func.count(FeedbackDetail.id),
            )
        )
        avg, total = result.one()
        dist_result = await db.execute(
            select(FeedbackDetail.rating, func.count(FeedbackDetail.id))
            .group_by(FeedbackDetail.rating)
        )
        distribution = {r: c for r, c in dist_result.all()}
        return {
            "avg": round(float(avg or 0), 2),
            "total": int(total or 0),
            "distribution": distribution,
        }

    @staticmethod
    async def get_recent_activity(db: AsyncSession, hours: int = 24) -> list[dict]:
        """Message volume per hour over the last N hours (MySQL-safe)."""
        since = datetime.now() - timedelta(hours=hours)
        rows = dict(
            (await db.execute(
                select(
                    func.date_format(Message.created_at, "%Y-%m-%d %H:00"),
                    func.count(Message.id),
                )
                .where(Message.created_at >= since)
                .group_by(func.date_format(Message.created_at, "%Y-%m-%d %H:00"))
                .order_by(func.date_format(Message.created_at, "%Y-%m-%d %H:00"))
            )).all()
        )
        # Fill missing hours with 0
        buckets = []
        for i in range(hours, -1, -1):
            h = since + timedelta(hours=i)
            key = h.strftime("%Y-%m-%d %H:00")
            buckets.append({"hour": key[5:], "count": int(rows.get(key, 0))})
        return buckets

    @staticmethod
    async def get_health(db: AsyncSession) -> dict:
        """Health checks: database, redis, chromadb."""
        checks: dict[str, dict] = {}

        # Database
        try:
            await db.execute(select(func.count(Message.id)).limit(1))
            checks["database"] = {"status": "ok"}
        except Exception as e:
            checks["database"] = {"status": "error", "detail": str(e)}

        # Redis
        try:
            from app.db.redis import get_redis_client
            redis = await get_redis_client()
            if redis:
                await redis.ping()
                checks["redis"] = {"status": "ok"}
            else:
                checks["redis"] = {"status": "ok", "detail": "disabled"}
        except Exception as e:
            checks["redis"] = {"status": "error", "detail": str(e)}

        # ChromaDB
        try:
            from app.vector_store.factory import get_vector_store
            store = get_vector_store()
            await store.get_collection_stats("default")
            checks["chromadb"] = {"status": "ok"}
        except Exception as e:
            checks["chromadb"] = {"status": "error", "detail": str(e)}

        overall = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"
        return {"status": overall, "checks": checks}

    @staticmethod
    async def get_dashboard_summary(db: AsyncSession) -> dict:
        """One-shot aggregation for the monitoring dashboard."""
        usage = {
            "total_conversations": (
                await db.execute(select(func.count(Conversation.id)))
            ).scalar() or 0,
            "total_messages": (
                await db.execute(select(func.count(Message.id)))
            ).scalar() or 0,
            "total_users": (
                await db.execute(select(func.count(User.id)))
            ).scalar() or 0,
            "total_kbs": (
                await db.execute(select(func.count(KnowledgeBase.id)))
            ).scalar() or 0,
            "total_documents": (
                await db.execute(select(func.count(Document.id)))
            ).scalar() or 0,
        }

        return {
            "system_health": await MetricsTracker.get_health(db),
            "usage": usage,
            "latency": await MetricsTracker.get_latency_stats(db),
            "tokens": await MetricsTracker.get_token_stats(db),
            "models": await MetricsTracker.get_model_distribution(db),
            "kb_storage": await MetricsTracker.get_kb_storage_stats(db),
            "ratings": await MetricsTracker.get_rating_summary(db),
            "recent_activity": await MetricsTracker.get_recent_activity(db),
        }
