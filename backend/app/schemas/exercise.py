"""Exercise and learning session schemas."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Exercise schemas ─────────────────────────────────────────────────

class ExerciseOption(BaseModel):
    A: str
    B: str
    C: str
    D: str


class ExerciseResponse(BaseModel):
    id: UUID
    type: str
    question: str
    options: dict
    difficulty: str
    priority: str
    topic: str | None = None
    tags: list | None = None
    is_new: bool = False
    sm2_state: dict | None = None

    class Config:
        from_attributes = True


# ── Learning session schemas ────────────────────────────────────────

class SessionStartRequest(BaseModel):
    kb_id: str
    topic: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    mode: str = Field(default="all", pattern=r"^(new|due|review|wrong|all)$")


class SessionStartResponse(BaseModel):
    session_id: str  # = kb_id, for simplicity
    exercises: list[ExerciseResponse]
    total_available: int
    stats: dict | None = None


class AnswerSubmitRequest(BaseModel):
    exercise_id: str
    selected: str = Field(..., pattern=r"^[ABCDabcd]$")


class AnswerSubmitResponse(BaseModel):
    correct: bool
    correct_answer: str
    explanation: str | None = None
    sm2_state: dict


# ── Generation schemas ──────────────────────────────────────────────

class GenerateExercisesRequest(BaseModel):
    kb_id: str
    limit: int | None = Field(default=None, ge=1, le=200)


class GenerateExercisesResponse(BaseModel):
    kb_id: str
    total_chunks: int
    processed: int
    exercises_created: int
    errors: int


class GenerateExercisesAsyncResponse(BaseModel):
    """Returned when exercise generation is submitted as a Celery task."""

    kb_id: str
    task_id: str
    status: str = "pending"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


# ── Stats schemas ───────────────────────────────────────────────────

class ExerciseStatsResponse(BaseModel):
    kb_id: str
    total_exercises: int
    attempted: int
    mastered: int
    weak_points: int
    due_for_review: int
    new_available: int
    wrong_count: int = 0    # 错题本：答错过至少一次的题目数
    overall_accuracy: float
