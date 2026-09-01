"""Search endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., min_length=1),
    kb_id: UUID | None = None,
    k: int = Query(5, ge=1, le=100),
    strategy: str = Query("hybrid"),
    alpha: float = Query(0.6, ge=0.0, le=1.0),
    rerank: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search across knowledge bases."""
    from app.core.rag.pipeline import RAGPipeline
    # Use simplified search endpoint
    pipeline = RAGPipeline()
    result = await pipeline.search_only(query=q, kb_id=kb_id, k=k, strategy=strategy, alpha=alpha, rerank=rerank)
    return result
