"""Monitoring endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_admin_user
from app.models.user import User
from app.schemas.misc import DashboardSummary

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/metrics")
async def get_metrics(
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.tracker import MetricsTracker
    return MetricsTracker.get_metrics()


@router.get("/latency")
async def get_latency(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_latency_stats(db)


@router.get("/tokens")
async def get_token_usage(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_token_stats(db)


@router.get("/vector-db")
async def get_vector_db_health(
    _admin: User = Depends(get_current_admin_user),
):
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_vector_db_health()


@router.get("/dashboard", response_model=DashboardSummary)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """One-shot aggregation for the monitoring dashboard."""
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_dashboard_summary(db)


@router.get("/models")
async def get_models(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """LLM usage distribution by provider/model."""
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_model_distribution(db)


@router.get("/kb-storage")
async def get_kb_storage(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Per-KB storage capacity (DB counters vs ChromaDB vectors)."""
    from app.core.monitoring.tracker import MetricsTracker
    return await MetricsTracker.get_kb_storage_stats(db)
