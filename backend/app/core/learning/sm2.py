"""SM-2 spaced repetition scheduler — adapted for programming exercises.

Standard SM-2 (SuperMemo 2) adaptions:
  - Initial ease_factor varies by exercise difficulty (easy=2.5, medium=2.3, hard=2.0)
  - First-correct answer gets a 0.7× interval penalty to counteract 25% guess probability
  - Binary fallback: when no self-rated quality (0-5) available, use correct/wrong → q=4/q=1
  - Consecutive wrong ≥ 3 triggers weak-point flagging for priority boost
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum


class Quality(IntEnum):
    """SM-2 self-assessment quality scale (0-5)."""
    COMPLETE_BLACKOUT = 0
    INCORRECT_BUT_REMEMBERED = 1
    INCORRECT_BUT_EASY_RECALL = 2
    CORRECT_WITH_DIFFICULTY = 3
    CORRECT_WITH_HESITATION = 4
    PERFECT_RESPONSE = 5


# ── SM-2 defaults (adapted for programming learning) ────────────────
DEFAULT_EASE_FACTOR = 2.5
MIN_EASE_FACTOR = 1.3
GUESS_PENALTY = 0.7        # 4-choice → 25% guess chance → reduce interval

INITIAL_EF_BY_DIFFICULTY = {
    "easy": 2.5,
    "medium": 2.3,
    "hard": 2.0,
}

# Intervals (days) for early repetitions
INTERVAL_AFTER_FIRST = 1    # 1 day after first correct
INTERVAL_AFTER_SECOND = 6   # 6 days after second correct

# Weak-point threshold
CONSECUTIVE_WRONG_THRESHOLD = 3  # flag as weak after 3 consecutive wrong


@dataclass
class SM2State:
    """Mutable SM-2 scheduling state for one (user, exercise) pair."""
    interval: int = 0
    ease_factor: float = DEFAULT_EASE_FACTOR
    repetitions: int = 0
    due_date: datetime = field(default_factory=datetime.now)
    last_quality: int | None = None
    consecutive_correct: int = 0
    consecutive_wrong: int = 0
    total_attempts: int = 0
    total_correct: int = 0
    is_mastered: bool = False

    @property
    def is_weak(self) -> bool:
        """Flagged as weak point when repeatedly wrong."""
        return self.consecutive_wrong >= CONSECUTIVE_WRONG_THRESHOLD

    @property
    def is_due(self) -> bool:
        """Whether this exercise is due for review."""
        return datetime.now() >= self.due_date

    @property
    def accuracy(self) -> float:
        """Historical accuracy rate."""
        if self.total_attempts == 0:
            return 0.0
        return self.total_correct / self.total_attempts


class SM2Scheduler:
    """Stateless SM-2 algorithm implementation."""

    @staticmethod
    def update(
        state: SM2State,
        quality: int,
        *,
        initial_difficulty: str = "medium",
    ) -> SM2State:
        """Apply one SM-2 review iteration and return updated state.

        Args:
            state: Current scheduling state.
            quality: SM-2 quality rating (0-5).
            initial_difficulty: The exercise's inherent difficulty level
                (easy/medium/hard), used only on first correct answer to
                set the initial ease factor.

        Returns:
            Updated SM2State (mutated in-place + returned for chaining).
        """
        q = max(0, min(5, quality))
        state.last_quality = q
        state.total_attempts += 1

        if q >= Quality.CORRECT_WITH_DIFFICULTY:
            # ── Correct answer ──────────────────────────────────
            state.total_correct += 1
            state.consecutive_correct += 1
            state.consecutive_wrong = 0

            if state.repetitions == 0:
                # First correct: short interval, possibly penalized
                state.interval = INTERVAL_AFTER_FIRST
                state.interval = max(1, int(state.interval * GUESS_PENALTY))
                # Set initial EF based on difficulty
                state.ease_factor = INITIAL_EF_BY_DIFFICULTY.get(
                    initial_difficulty, DEFAULT_EASE_FACTOR
                )
            elif state.repetitions == 1:
                state.interval = INTERVAL_AFTER_SECOND
            else:
                state.interval = int(state.interval * state.ease_factor)
                # Apply extra penalty for correct-with-difficulty
                if q == Quality.CORRECT_WITH_DIFFICULTY:
                    state.interval = max(1, int(state.interval * 0.8))

            state.repetitions += 1

            # Mark mastered after 5+ repetitions with high accuracy
            if state.repetitions >= 5 and state.accuracy >= 0.85:
                state.is_mastered = True
        else:
            # ── Wrong answer ─────────────────────────────────────
            state.consecutive_wrong += 1
            state.consecutive_correct = 0
            state.repetitions = 0
            state.interval = 0  # Review again tomorrow
            state.is_mastered = False

        # ── Update ease factor (SM-2 formula) ──────────────────
        ef_delta = 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
        state.ease_factor = max(MIN_EASE_FACTOR, state.ease_factor + ef_delta)

        # ── Set next due date ───────────────────────────────────
        state.due_date = datetime.now() + timedelta(days=state.interval)

        return state

    @staticmethod
    def update_binary(
        state: SM2State,
        is_correct: bool,
        *,
        initial_difficulty: str = "medium",
    ) -> SM2State:
        """Convenience wrapper: correct → q=4, wrong → q=1.

        Use this when the learning UI doesn't collect self-rated quality,
        only correct/wrong from a multiple-choice answer.
        """
        quality = Quality.CORRECT_WITH_HESITATION if is_correct else Quality.INCORRECT_BUT_REMEMBERED
        return SM2Scheduler.update(state, quality, initial_difficulty=initial_difficulty)
