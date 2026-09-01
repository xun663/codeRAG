"""Exercise generation and learning session service.

Core flow:
  1. Generate exercises from chunks (LLM-based, during/after ingestion)
  2. Query exercises by KB + topic for learning sessions
  3. Submit answers → update SM-2 state → return next exercise
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import NotFoundException
from app.models.user import User
from app.models.document import DocumentChunk
from app.models.feedback import Exercise, ExerciseState
from app.core.learning.sm2 import SM2Scheduler, SM2State

# ── Exercise generation prompt (matches the design doc) ─────────────

_EXERCISE_GEN_SYSTEM = """\
你是一个编程知识教学专家。你的任务：根据提供的知识切片内容，生成 1-2 道选择题，\
用于检测学习者对切片内容的理解程度。

规则：
1. 题目必须严格源自切片内容，不得引入切片中未出现的知识点。
2. 每道题 4 个选项（A/B/C/D），仅 1 个正确答案。
3. 干扰项必须来自：切片中对比的概念、切片中提到的常见误解、切片中出现的同类 API/函数。
4. 禁止使用"以上都对"、"以上都不对"作为选项。
5. 解析（explanation）必须包含：正确答案的原因 + 每个错误选项的辨析。
6. 根据切片类型自动选择题型：
   - concept_match：考察对定义、原理、概念区分的理解
   - code_fill：考察 API 或代码语法的正确记忆和调用
   - output_predict：考察代码执行过程的推理能力
   - error_diagnose：考察常见错误的识别和修复（仅限切片明确提到错误或陷阱时使用）
7. 所有输出内容必须使用中文（题干、选项、解析），代码部分保持原样。

仅输出合法 JSON，不要输出任何解释或 Markdown。"""

_EXERCISE_GEN_USER = """\
切片内容：
---
{content}
---

为以下切片生成 1-2 道题。主题：{topic}，语言：{language}。
输出 JSON 格式：
{{
  "exercises": [
    {{
      "type": "concept_match | code_fill | output_predict | error_diagnose",
      "question": "题干（中文）",
      "options": {{"A": "选项A", "B": "选项B", "C": "选项C", "D": "选项D"}},
      "answer": "A",
      "explanation": "详细解析（中文）：正确答案的原因 + 每个错误选项的辨析",
      "difficulty": "easy | medium | hard"
    }}
  ]
}}"""


class ExerciseService:
    """Service for exercise generation and learning sessions."""

    # ── Exercise Generation ─────────────────────────────────────────

    @staticmethod
    async def generate_for_chunk(
        chunk: DocumentChunk,
        topic: str = "",
        language: str = "",
    ) -> list[dict]:
        """Generate 1-2 exercises from a single chunk using LLM.

        Returns list of exercise dicts ready for DB insertion.
        """
        from app.llm.factory import get_llm_provider

        llm = get_llm_provider()
        content = chunk.content
        if len(content) > 2000:
            content = content[:2000]  # Truncate long chunks

        topic = topic or chunk.metadata_json.get("topic", "Programming")
        language = language or chunk.metadata_json.get("language", "")

        prompt = _EXERCISE_GEN_USER.format(content=content, topic=topic, language=language)

        try:
            raw = await llm.generate(prompt=prompt, system_prompt=_EXERCISE_GEN_SYSTEM)
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3].strip()
            data = json.loads(raw)
            return data.get("exercises", [])
        except Exception:
            return []

    @staticmethod
    async def generate_for_kb(
        db: AsyncSession,
        kb_id: str,
        *,
        limit: int | None = None,
        skip_existing: bool = True,
    ) -> dict:
        """Batch-generate exercises for all chunks in a knowledge base.

        Args:
            db: Database session.
            kb_id: Knowledge base ID.
            limit: Max chunks to process (None = all).
            skip_existing: Skip chunks that already have exercises.

        Returns:
            {"total_chunks": N, "processed": N, "exercises_created": N, "errors": N}
        """
        uid = uuid.UUID(kb_id)
        q = select(DocumentChunk).where(
            DocumentChunk.kb_id == uid,
            DocumentChunk.token_count >= 15,  # Skip very short fragments
            DocumentChunk.chunk_type.in_([
                "text", "text_heading",
                "code_block_python", "code_block_java",
                "code_block_javascript", "code_block_go", "code_block_rust",
            ]),
        )

        if skip_existing:
            # Exclude chunks that already have exercises
            existing_sub = select(Exercise.chunk_id).distinct()
            q = q.where(DocumentChunk.id.not_in(existing_sub))

        if limit:
            q = q.limit(limit)

        r = await db.execute(q)
        chunks = list(r.scalars().all())

        # ── Parallel execution ───────────────────────────────────────
        # Use asyncio.Semaphore to limit concurrency (default: 5 at a time).
        # This avoids API rate limits while dramatically speeding up
        # exercise generation vs the old sequential 0.5s/chunk approach.
        sem = asyncio.Semaphore(settings.exercise_gen_concurrency or 5)

        async def _process_one(chunk: DocumentChunk) -> int:
            """Generate exercises for a single chunk and persist to DB.
            Returns number of exercises created, or 0 on failure.
            """
            async with sem:
                exercises = await ExerciseService.generate_for_chunk(chunk)
                if not exercises:
                    return 0

                created = 0
                for ex_data in exercises:
                    question = ex_data.get("question")
                    options = ex_data.get("options")
                    answer = ex_data.get("answer")
                    if not question or not options or not answer:
                        continue

                    exercise = Exercise(
                        id=uuid.uuid4(),
                        chunk_id=chunk.id,
                        kb_id=uid,
                        doc_id=chunk.doc_id,
                        type=ex_data.get("type", "concept_match"),
                        question=question,
                        options=options,
                        answer=answer,
                        explanation=ex_data.get("explanation", ""),
                        difficulty=ex_data.get("difficulty", "medium"),
                        topic=chunk.metadata_json.get("topic", ""),
                        tags=chunk.metadata_json.get("key_terms", []),
                    )
                    db.add(exercise)
                    created += 1
                return created

        results = await asyncio.gather(*[_process_one(c) for c in chunks])
        total_created = sum(results)
        errors = sum(1 for r in results if r == 0)

        await db.flush()

        return {
            "total_chunks": len(chunks),
            "processed": len(chunks),
            "exercises_created": total_created,
            "errors": errors,
        }

    # ── Learning Session ────────────────────────────────────────────

    @staticmethod
    async def get_due_exercises(
        db: AsyncSession,
        user: User,
        kb_id: str,
        *,
        limit: int = 10,
        topic: str | None = None,
        mode: str = "all",
    ) -> list[dict]:
        """Get exercises for a learning session.

        Args:
            mode:
                - "new": only never-attempted exercises
                - "due": only SM-2 due-for-review exercises
                - "review": only previously attempted (for active review)
                - "all": new + due (default, current behavior)
        """
        uid = uuid.UUID(kb_id)

        # 1. Get all exercises for this KB
        ex_q = select(Exercise).where(Exercise.kb_id == uid)
        if topic:
            ex_q = ex_q.where(Exercise.topic == topic)
        r = await db.execute(ex_q)
        all_exercises = list(r.scalars().all())

        if not all_exercises:
            return []

        ex_ids = [e.id for e in all_exercises]

        # 2. Get existing states for this user
        state_q = select(ExerciseState).where(
            and_(
                ExerciseState.user_id == user.id,
                ExerciseState.exercise_id.in_(ex_ids),
            )
        )
        r = await db.execute(state_q)
        states = {s.exercise_id: s for s in r.scalars().all()}

        # 3. Build result based on mode
        now = datetime.now()
        results = []

        for ex in all_exercises:
            state = states.get(ex.id)

            if mode == "new":
                # Only never-attempted
                if state is None:
                    results.append(ExerciseService._to_dict(ex, is_new=True))

            elif mode == "due":
                # Only SM-2 due
                if state is not None and state.due_date <= now:
                    results.append(ExerciseService._to_dict(ex, state=state, is_new=False))

            elif mode == "review":
                # Only previously attempted (active review — user chooses)
                if state is not None:
                    results.append(ExerciseService._to_dict(ex, state=state, is_new=False))

            elif mode == "wrong":
                # 错题本：答错过至少一次的题目（total_attempts > total_correct），方便回顾
                if state is not None and (state.total_attempts or 0) > (state.total_correct or 0):
                    results.append(ExerciseService._to_dict(ex, state=state, is_new=False))

            else:  # "all" — new + due
                if state is None:
                    results.append(ExerciseService._to_dict(ex, is_new=True))
                elif state.due_date <= now:
                    results.append(ExerciseService._to_dict(ex, state=state, is_new=False))

        # 4. Sort: priority (high > normal > low) → due_date
        priority_order = {"high": 0, "normal": 1, "low": 2}
        results.sort(key=lambda x: (
            priority_order.get(x.get("priority", "normal"), 1),
            x.get("due_date", ""),
        ))

        return results[:limit]

    @staticmethod
    async def submit_answer(
        db: AsyncSession,
        user: User,
        exercise_id: str,
        selected: str,
    ) -> dict:
        """Submit an answer, update SM-2 state, return feedback.

        Returns:
            {
                "correct": bool,
                "correct_answer": "A",
                "explanation": "...",
                "sm2_state": {...},
                "is_weak": bool,
            }
        """
        eid = uuid.UUID(exercise_id)

        # Get exercise
        r = await db.execute(select(Exercise).where(Exercise.id == eid))
        exercise = r.scalar_one_or_none()
        if not exercise:
            raise NotFoundException("Exercise not found")

        is_correct = (selected.upper() == exercise.answer.upper())

        # Get or create state
        r = await db.execute(
            select(ExerciseState).where(
                and_(
                    ExerciseState.user_id == user.id,
                    ExerciseState.exercise_id == eid,
                )
            )
        )
        state = r.scalar_one_or_none()

        if state is None:
            state = ExerciseState(
                id=uuid.uuid4(),
                user_id=user.id,
                exercise_id=eid,
                interval=0,
                ease_factor=2.5,
                repetitions=0,
                due_date=datetime.now(),
                consecutive_correct=0,
                consecutive_wrong=0,
                total_attempts=0,
                total_correct=0,
                is_mastered=False,
            )
            db.add(state)

        # Apply SM-2 update (use or 0 to handle None from DB)
        sm2 = SM2State(
            interval=state.interval or 0,
            ease_factor=state.ease_factor or 2.5,
            repetitions=state.repetitions or 0,
            due_date=state.due_date or datetime.now(),
            last_quality=state.last_quality,
            consecutive_correct=state.consecutive_correct or 0,
            consecutive_wrong=state.consecutive_wrong or 0,
            total_attempts=state.total_attempts or 0,
            total_correct=state.total_correct or 0,
            is_mastered=state.is_mastered or False,
        )

        SM2Scheduler.update_binary(sm2, is_correct, initial_difficulty=exercise.difficulty)

        # Write back to DB model
        state.interval = sm2.interval
        state.ease_factor = sm2.ease_factor
        state.repetitions = sm2.repetitions
        state.due_date = sm2.due_date
        state.last_quality = sm2.last_quality
        state.consecutive_correct = sm2.consecutive_correct
        state.consecutive_wrong = sm2.consecutive_wrong
        state.total_attempts = sm2.total_attempts
        state.total_correct = sm2.total_correct
        state.is_mastered = sm2.is_mastered

        await db.flush()

        return {
            "correct": is_correct,
            "correct_answer": exercise.answer,
            "explanation": exercise.explanation,
            "sm2_state": {
                "interval": sm2.interval,
                "ease_factor": round(sm2.ease_factor, 2),
                "repetitions": sm2.repetitions,
                "due_date": sm2.due_date.isoformat(),
                "is_mastered": sm2.is_mastered,
                "is_weak": sm2.is_weak,
                "accuracy": round(sm2.accuracy, 2),
            },
        }

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        user: User,
        kb_id: str,
    ) -> dict:
        """Get learning statistics for a user in a KB."""
        uid = uuid.UUID(kb_id)

        # Total exercises in KB
        r = await db.execute(
            select(func.count(Exercise.id)).where(Exercise.kb_id == uid)
        )
        total_exercises = r.scalar_one()

        # User's states in this KB
        r = await db.execute(
            select(ExerciseState).where(
                and_(
                    ExerciseState.user_id == user.id,
                    ExerciseState.exercise_id.in_(
                        select(Exercise.id).where(Exercise.kb_id == uid)
                    ),
                )
            )
        )
        states = list(r.scalars().all())

        attempted = len(states)
        mastered = sum(1 for s in states if s.is_mastered)
        weak = sum(1 for s in states if s.consecutive_wrong >= 3)
        wrong = sum(1 for s in states if (s.total_attempts or 0) > (s.total_correct or 0))
        due = sum(1 for s in states if s.due_date <= datetime.now())

        total_correct = sum(s.total_correct for s in states)
        total_attempts = sum(s.total_attempts for s in states)
        overall_accuracy = total_correct / total_attempts if total_attempts > 0 else 0.0

        return {
            "kb_id": kb_id,
            "total_exercises": total_exercises,
            "attempted": attempted,
            "mastered": mastered,
            "weak_points": weak,
            "wrong_count": wrong,
            "due_for_review": due,
            "new_available": total_exercises - attempted,
            "overall_accuracy": round(overall_accuracy, 2),
        }

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _to_dict(
        ex: Exercise,
        state: ExerciseState | None = None,
        is_new: bool = False,
    ) -> dict:
        return {
            "id": str(ex.id),
            "type": ex.type,
            "question": ex.question,
            "options": ex.options,
            "difficulty": ex.difficulty,
            "priority": ex.priority,
            "topic": ex.topic,
            "tags": ex.tags,
            "is_new": is_new,
            "sm2_state": {
                "interval": state.interval if state else 0,
                "ease_factor": round(state.ease_factor, 2) if state else 2.5,
                "repetitions": state.repetitions if state else 0,
                "due_date": state.due_date.isoformat() if state else datetime.now().isoformat(),
                "is_mastered": state.is_mastered if state else False,
                "is_weak": state.consecutive_wrong >= 3 if state else False,
            },
        }
