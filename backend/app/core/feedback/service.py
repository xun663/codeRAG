"""Feedback service."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Message
from app.models.feedback import FeedbackDetail
from app.models.user import User


class FeedbackService:
    @staticmethod
    async def submit_rating(db: AsyncSession, msg_id, user: User, rating: int) -> dict:
        result = await db.execute(select(Message).where(Message.id == msg_id))
        msg = result.scalar_one_or_none()
        if not msg:
            from app.exceptions import NotFoundException
            raise NotFoundException("Message not found")

        msg.user_rating = rating
        await db.flush()
        return {"message": "Rating submitted", "rating": rating}

    @staticmethod
    async def submit_detail(db: AsyncSession, msg_id, user: User, data) -> dict:
        detail = FeedbackDetail(
            id=uuid.uuid4(),
            message_id=msg_id,
            user_id=user.id,
            rating=data.rating,
            feedback_type=data.feedback_type,
            comment=data.comment,
            is_helpful=data.is_helpful,
        )
        db.add(detail)
        await db.flush()
        return {"message": "Feedback submitted", "id": str(detail.id)}

    @staticmethod
    async def get_summary(db: AsyncSession) -> dict:
        # Average rating
        result = await db.execute(select(func.avg(Message.user_rating)).where(Message.user_rating.isnot(None)))
        avg_rating = result.scalar() or 0

        # Rating distribution
        result = await db.execute(
            select(Message.user_rating, func.count(Message.id))
            .where(Message.user_rating.isnot(None))
            .group_by(Message.user_rating)
        )
        distribution = {str(row[0]): row[1] for row in result.all()}

        # Total feedback
        result = await db.execute(select(func.count(FeedbackDetail.id)))
        total_feedback = result.scalar()

        return {
            "avg_rating": round(float(avg_rating), 2),
            "rating_distribution": distribution,
            "total_feedback": total_feedback,
        }
