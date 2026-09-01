"""Evaluation endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.misc import EvalDatasetCreate, EvalDatasetResponse, EvalQAPairCreate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.get("/datasets", response_model=PaginatedResponse[EvalDatasetResponse])
async def list_datasets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.evaluation.dataset_service import EvalDatasetService
    items, total = await EvalDatasetService.list_datasets(db, page, page_size)
    return PaginatedResponse(items=items, total=total, page=page, page_size=page_size,
                             pages=(total + page_size - 1) // page_size)


@router.post("/datasets", response_model=EvalDatasetResponse, status_code=201)
async def create_dataset(
    data: EvalDatasetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.evaluation.dataset_service import EvalDatasetService
    return await EvalDatasetService.create_dataset(db, current_user, data)


@router.post("/datasets/{ds_id}/qa-pairs")
async def add_qa_pairs(
    ds_id: UUID,
    pairs: list[EvalQAPairCreate],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.evaluation.dataset_service import EvalDatasetService
    return await EvalDatasetService.add_qa_pairs(db, ds_id, pairs)


@router.post("/datasets/{ds_id}/run")
async def run_evaluation(
    ds_id: UUID,
    config: dict | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.evaluation.dataset_service import EvalDatasetService
    return await EvalDatasetService.run_evaluation(db, ds_id, config or {})


@router.get("/datasets/{ds_id}/results")
async def get_results(
    ds_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.evaluation.dataset_service import EvalDatasetService
    return await EvalDatasetService.get_results(db, ds_id)
