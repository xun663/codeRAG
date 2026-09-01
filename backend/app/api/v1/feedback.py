"""Feedback endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.misc import MessageRatingCreate, FeedbackDetailCreate

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("/messages/{msg_id}/rating")
async def submit_rating(
    msg_id: UUID,
    data: MessageRatingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.feedback.service import FeedbackService
    return await FeedbackService.submit_rating(db, msg_id, current_user, data.rating)


@router.post("/messages/{msg_id}/detail")
async def submit_detailed_feedback(
    msg_id: UUID,
    data: FeedbackDetailCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.feedback.service import FeedbackService
    return await FeedbackService.submit_detail(db, msg_id, current_user, data)


@router.get("/summary")
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.core.feedback.service import FeedbackService
    return await FeedbackService.get_summary(db)
