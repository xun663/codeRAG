"""Exercise and learning session API endpoints."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.exceptions import ForbiddenException, NotFoundException
from app.middleware.auth import get_current_user
from app.models.feedback import Exercise
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.services.kb_service import KBService
from celery import states as celery_states

from app.schemas.exercise import (
    AnswerSubmitRequest,
    AnswerSubmitResponse,
    ExerciseStatsResponse,
    GenerateExercisesRequest,
    GenerateExercisesResponse,
    GenerateExercisesAsyncResponse,
    SessionStartRequest,
    SessionStartResponse,
    TaskStatusResponse,
)
from app.services.exercise_service import ExerciseService

router = APIRouter(prefix="/exercises", tags=["exercises"])


async def _check_generate_permission(db: AsyncSession, kb_id, user: User) -> None:
    """出题权限：官方库（platform）仅 admin 可生成共享题；个人库仅 owner/写权限成员可生成私有题。"""
    uid = uuid.UUID(str(kb_id)) if not isinstance(kb_id, uuid.UUID) else kb_id
    r = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == uid))
    kb = r.scalar_one_or_none()
    if not kb:
        raise NotFoundException("Knowledge base not found")
    if kb.scope == "platform":
        if user.role != "admin":
            raise ForbiddenException("仅管理员可在官方库生成题目")
    else:
        await KBService.check_kb_write_access(db, uid, user)


@router.post("/generate", response_model=GenerateExercisesResponse)
async def generate_exercises(
    data: GenerateExercisesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate exercises from chunks in a knowledge base (LLM-powered, sync).

    For large KBs (10+ chunks), the request may take 10s+.
    Use ``POST /exercises/generate-async`` for non-blocking generation.
    """
    await _check_generate_permission(db, data.kb_id, current_user)
    result = await ExerciseService.generate_for_kb(
        db, data.kb_id, limit=data.limit
    )
    return GenerateExercisesResponse(kb_id=data.kb_id, **result)


@router.post("/generate-async", response_model=GenerateExercisesAsyncResponse)
async def generate_exercises_async(
    data: GenerateExercisesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit exercise generation as a background Celery task.

    Returns immediately with a ``task_id``.
    Poll ``GET /exercises/tasks/{task_id}`` for status.
    """
    await _check_generate_permission(db, data.kb_id, current_user)
    from app.tasks.exercise_generation import generate_exercises_task

    task = generate_exercises_task.delay(data.kb_id, data.limit)
    return GenerateExercisesAsyncResponse(
        kb_id=data.kb_id,
        task_id=task.id,
        status="pending",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """Poll the status of an exercise generation task."""
    from app.tasks.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    return TaskStatusResponse(
        task_id=task_id,
        status=result.state,
        result=result.result if result.successful() else None,
    )


@router.post("/sessions/start", response_model=SessionStartResponse)
async def start_session(
    data: SessionStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a learning session: get due exercises for a KB.

    Returns a mix of new (never seen) and due-for-review exercises,
    sorted by priority then due date.
    """
    await KBService.check_kb_access(db, data.kb_id, current_user)
    exercises = await ExerciseService.get_due_exercises(
        db, current_user, data.kb_id, limit=data.limit, topic=data.topic, mode=data.mode
    )
    stats = await ExerciseService.get_stats(db, current_user, data.kb_id)

    return SessionStartResponse(
        session_id=data.kb_id,
        exercises=exercises,
        total_available=len(exercises),
        stats=stats,
    )


@router.post("/sessions/answer", response_model=AnswerSubmitResponse)
async def submit_answer(
    data: AnswerSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an answer for an exercise and get feedback + updated SM-2 state."""
    # 校验该题目所属知识库的读权限（个人库题目仅 owner/成员可见）
    r = await db.execute(select(Exercise.kb_id).where(Exercise.id == data.exercise_id))
    ex_kb_id = r.scalar_one_or_none()
    if not ex_kb_id:
        raise NotFoundException("Exercise not found")
    await KBService.check_kb_access(db, ex_kb_id, current_user)
    result = await ExerciseService.submit_answer(
        db, current_user, data.exercise_id, data.selected
    )
    return AnswerSubmitResponse(**result)


@router.get("/stats/{kb_id}", response_model=ExerciseStatsResponse)
async def get_stats(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get learning statistics for a user in a knowledge base."""
    await KBService.check_kb_access(db, kb_id, current_user)
    result = await ExerciseService.get_stats(db, current_user, kb_id)
    return ExerciseStatsResponse(**result)
