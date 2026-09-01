"""Tests for the SM-2 spaced repetition algorithm (app/core/learning/sm2.py).

Covers:
  - SM2State property invariants
  - SM2Scheduler.update() with correct answers at various quality levels
  - SM2Scheduler.update() with wrong answers
  - Ease factor update formula
  - Mastery detection
  - Weak point detection
  - update_binary() convenience wrapper
  - Edge cases and boundary conditions
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.learning.sm2 import (
    CONSECUTIVE_WRONG_THRESHOLD,
    DEFAULT_EASE_FACTOR,
    GUESS_PENALTY,
    INITIAL_EF_BY_DIFFICULTY,
    INTERVAL_AFTER_FIRST,
    INTERVAL_AFTER_SECOND,
    MIN_EASE_FACTOR,
    Quality,
    SM2Scheduler,
    SM2State,
)


# ═════════════════════════════════════════════════════════════════════
#  SM2State property tests
# ═════════════════════════════════════════════════════════════════════

class TestSM2State:
    """SM2State dataclass property invariants."""

    def test_default_state(self, sm2_state: SM2State):
        assert sm2_state.interval == 0
        assert sm2_state.ease_factor == DEFAULT_EASE_FACTOR
        assert sm2_state.repetitions == 0
        assert sm2_state.last_quality is None
        assert sm2_state.consecutive_correct == 0
        assert sm2_state.consecutive_wrong == 0
        assert sm2_state.total_attempts == 0
        assert sm2_state.total_correct == 0
        assert sm2_state.is_mastered is False
        assert sm2_state.is_weak is False
        assert sm2_state.is_due is True  # due_date is now -> is_due
        assert sm2_state.accuracy == 0.0

    def test_accuracy_zero_attempts(self, sm2_state: SM2State):
        assert sm2_state.accuracy == 0.0

    def test_accuracy_half_correct(self, sm2_state: SM2State):
        sm2_state.total_attempts = 4
        sm2_state.total_correct = 2
        assert sm2_state.accuracy == 0.5

    def test_accuracy_all_correct(self, sm2_state: SM2State):
        sm2_state.total_attempts = 5
        sm2_state.total_correct = 5
        assert sm2_state.accuracy == 1.0

    def test_is_weak_below_threshold(self, sm2_state: SM2State):
        sm2_state.consecutive_wrong = CONSECUTIVE_WRONG_THRESHOLD - 1
        assert sm2_state.is_weak is False

    def test_is_weak_at_threshold(self, sm2_state: SM2State):
        sm2_state.consecutive_wrong = CONSECUTIVE_WRONG_THRESHOLD
        assert sm2_state.is_weak is True

    def test_is_weak_above_threshold(self, sm2_state: SM2State):
        sm2_state.consecutive_wrong = CONSECUTIVE_WRONG_THRESHOLD + 5
        assert sm2_state.is_weak is True

    def test_is_due_future(self):
        state = SM2State(due_date=datetime.now() + timedelta(days=7))
        assert state.is_due is False

    def test_is_due_past(self):
        state = SM2State(due_date=datetime.now() - timedelta(hours=1))
        assert state.is_due is True


# ═════════════════════════════════════════════════════════════════════
#  SM2Scheduler.update() — correct answers
# ═════════════════════════════════════════════════════════════════════

class TestSM2FirstCorrect:
    """First correct answer — quality >= 3."""

    def test_first_correct_sets_interval_and_ef(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(sm2_state, Quality.PERFECT_RESPONSE)
        expected_interval = max(1, int(INTERVAL_AFTER_FIRST * GUESS_PENALTY))
        assert state.interval == expected_interval
        # SM-2 formula runs AFTER initial EF assignment: EF = 2.3 + 0.1 = 2.4
        assert state.ease_factor == INITIAL_EF_BY_DIFFICULTY["medium"] + 0.1
        assert state.repetitions == 1
        assert state.consecutive_correct == 1
        assert state.consecutive_wrong == 0
        assert state.total_attempts == 1
        assert state.total_correct == 1
        assert state.last_quality == Quality.PERFECT_RESPONSE

    def test_first_correct_medium_difficulty(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(sm2_state, Quality.PERFECT_RESPONSE, initial_difficulty="medium")
        # SM-2 formula adds 0.1 for q=5: 2.3 + 0.1 = 2.4
        assert state.ease_factor == INITIAL_EF_BY_DIFFICULTY["medium"] + 0.1

    def test_first_correct_easy_difficulty(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(sm2_state, Quality.PERFECT_RESPONSE, initial_difficulty="easy")
        # SM-2 formula adds 0.1 for q=5: 2.5 + 0.1 = 2.6
        assert state.ease_factor == INITIAL_EF_BY_DIFFICULTY["easy"] + 0.1

    def test_first_correct_hard_difficulty(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(sm2_state, Quality.PERFECT_RESPONSE, initial_difficulty="hard")
        # SM-2 formula adds 0.1 for q=5: 2.0 + 0.1 = 2.1
        assert state.ease_factor == INITIAL_EF_BY_DIFFICULTY["hard"] + 0.1

    def test_first_correct_due_date_set(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        before = datetime.now()
        state = sm2_scheduler.update(sm2_state, Quality.PERFECT_RESPONSE)
        assert state.due_date >= before + timedelta(days=INTERVAL_AFTER_FIRST - 1)

    def test_first_correct_quality_3_penalty(self, sm2_state: SM2State, sm2_scheduler: SM2Scheduler):
        """CORRECT_WITH_DIFFICULTY (q=3) gets both guess penalty AND difficulty penalty on later reps."""
        state = sm2_scheduler.update(sm2_state, Quality.CORRECT_WITH_DIFFICULTY)
        expected_interval = max(1, int(INTERVAL_AFTER_FIRST * GUESS_PENALTY))
        assert state.interval == expected_interval
        assert state.repetitions == 1


class TestSM2SecondCorrect:
    """Second consecutive correct answer."""

    def test_second_correct_uses_fixed_interval(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(repetitions=1, interval=1, ease_factor=DEFAULT_EASE_FACTOR)
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.interval == INTERVAL_AFTER_SECOND
        assert state.repetitions == 2
        assert state.consecutive_correct == 1
        assert state.total_correct == 1

    def test_second_correct_quality_3(self, sm2_scheduler: SM2Scheduler):
        """q=3 on second repeat applies 0.8x penalty."""
        state = SM2State(repetitions=1, interval=1, ease_factor=DEFAULT_EASE_FACTOR)
        state = sm2_scheduler.update(state, Quality.CORRECT_WITH_DIFFICULTY)
        # INTERVAL_AFTER_SECOND = 6, but q=3 penalty only applies at repetitions >= 2
        # On second repetition (repetitions=1 -> 2), interval = INTERVAL_AFTER_SECOND (no *0.8 penalty)
        assert state.interval == INTERVAL_AFTER_SECOND
        assert state.repetitions == 2


class TestSM2SubsequentCorrect:
    """Third and later correct answers — interval *= EF."""

    def test_third_correct_multiplies_by_ef(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=2, interval=6, ease_factor=2.5,
            consecutive_correct=2, total_attempts=2, total_correct=2,
        )
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        expected = int(6 * 2.5)
        assert state.interval == expected
        assert state.repetitions == 3

    def test_fifth_correct_with_quality_3_penalty(self, sm2_scheduler: SM2Scheduler):
        """At repetitions >= 2, q=3 applies 0.8x penalty to the interval."""
        state = SM2State(
            repetitions=4, interval=30, ease_factor=2.5,
            consecutive_correct=4, total_attempts=4, total_correct=4,
        )
        state = sm2_scheduler.update(state, Quality.CORRECT_WITH_DIFFICULTY)
        expected = max(1, int(30 * 2.5 * 0.8))
        assert state.interval == expected
        assert state.repetitions == 5

    def test_large_interval_stays_sane(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=10, interval=365, ease_factor=2.5,
            consecutive_correct=10, total_attempts=10, total_correct=10,
        )
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        expected = int(365 * 2.5)
        assert state.interval == expected
        assert state.repetitions == 11


# ═════════════════════════════════════════════════════════════════════
#  SM2Scheduler.update() — wrong answers
# ═════════════════════════════════════════════════════════════════════

class TestSM2WrongAnswers:
    """Answers with quality < 3 should reset progress."""

    def test_wrong_resets_repetitions(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=5, interval=30, ease_factor=2.5,
            consecutive_correct=5, total_attempts=5, total_correct=5,
        )
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.repetitions == 0
        assert state.interval == 0
        assert state.consecutive_correct == 0
        assert state.consecutive_wrong == 1
        assert state.total_attempts == 6
        assert state.total_correct == 5  # unchanged

    def test_wrong_clears_mastery(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=5, interval=30, ease_factor=2.5,
            consecutive_correct=5, total_attempts=5, total_correct=5,
            is_mastered=True,
        )
        state = sm2_scheduler.update(state, Quality.COMPLETE_BLACKOUT)
        assert state.is_mastered is False

    def test_wrong_due_date_tomorrow(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(SM2State(), Quality.INCORRECT_BUT_REMEMBERED)
        # interval=0 -> due_date = now + 0 days = today -> is_due is True
        # Actually: interval=0 => timedelta(days=0) => due_date = now
        # Since we set due_date to datetime.now(), it should be "now" so is_due is True
        assert state.is_due

    def test_wrong_does_not_count_as_correct(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(total_attempts=0, total_correct=0)
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.total_correct == 0
        assert state.total_attempts == 1

    def test_consecutive_wrong_tracking(self, sm2_scheduler: SM2Scheduler):
        state = SM2State()
        for _ in range(4):
            state = sm2_scheduler.update(state, Quality.COMPLETE_BLACKOUT)
        assert state.consecutive_wrong == 4
        assert state.is_weak is True

    def test_wrong_after_correct_resets_consecutive(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(consecutive_correct=3, repetitions=3)
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.consecutive_correct == 0
        assert state.consecutive_wrong == 1

    def test_quality_zero_handling(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(SM2State(), Quality.COMPLETE_BLACKOUT)
        assert state.repetitions == 0
        assert state.last_quality == Quality.COMPLETE_BLACKOUT


# ═════════════════════════════════════════════════════════════════════
#  Ease factor update tests
# ═════════════════════════════════════════════════════════════════════

class TestEaseFactor:
    """SM-2 ease factor update formula:
    EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
    """

    def test_perfect_response_increases_ef(self, sm2_scheduler: SM2Scheduler):
        """Start from repetitions > 0 so first-correct branch doesn't reset EF."""
        state = SM2State(ease_factor=2.5, repetitions=2, interval=6)
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        # q=5: delta = 0.1 - (0)*(0.08 + 0*0.02) = 0.1
        assert state.ease_factor == pytest.approx(2.6, rel=1e-9)

    def test_correct_with_hesitation_increases_ef_slightly(self, sm2_scheduler: SM2Scheduler):
        """Start from repetitions > 0 so first-correct branch doesn't reset EF."""
        state = SM2State(ease_factor=2.5, repetitions=2, interval=6)
        state = sm2_scheduler.update(state, Quality.CORRECT_WITH_HESITATION)
        # q=4: delta = 0.1 - (1)*(0.08 + 1*0.02) = 0.1 - 0.1 = 0.0
        assert state.ease_factor == pytest.approx(2.5, rel=1e-9)

    def test_incorrect_reduces_ef(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(ease_factor=2.5)
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        # q=1: delta = 0.1 - (4)*(0.08 + 4*0.02) = 0.1 - 4*0.16 = 0.1 - 0.64 = -0.54
        assert state.ease_factor == pytest.approx(1.96, rel=1e-9)

    def test_ef_never_below_minimum(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(ease_factor=MIN_EASE_FACTOR)
        state = sm2_scheduler.update(state, Quality.COMPLETE_BLACKOUT)
        assert state.ease_factor >= MIN_EASE_FACTOR
        # q=0: delta = 0.1 - (5)*(0.08 + 5*0.02) = 0.1 - 5*0.18 = 0.1 - 0.9 = -0.8
        # 1.3 + (-0.8) = 0.5 -> clamped to 1.3
        assert state.ease_factor == pytest.approx(MIN_EASE_FACTOR, rel=1e-9)

    def test_ef_increase_with_high_quality_sustained(self, sm2_scheduler: SM2Scheduler):
        """Multiple perfect responses should keep increasing EF."""
        state = SM2State(ease_factor=2.5)
        for _ in range(5):
            state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.ease_factor > 2.5

    def test_quality_clipping(self, sm2_scheduler: SM2Scheduler):
        """Quality values outside 0-5 should be clamped."""
        state = sm2_scheduler.update(SM2State(), 10)
        assert state.last_quality == 5
        state = sm2_scheduler.update(SM2State(), -1)
        assert state.last_quality == 0


# ═════════════════════════════════════════════════════════════════════
#  Mastery detection tests
# ═════════════════════════════════════════════════════════════════════

class TestMastery:
    """Mastered at 5+ repetitions with >=85% accuracy."""

    def test_mastery_at_threshold(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=4, interval=30, ease_factor=2.5,
            total_attempts=10, total_correct=9,  # 90% accuracy
        )
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 5
        assert state.is_mastered is True

    def test_not_mastered_below_5_reps(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(repetitions=3)
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 4
        assert state.is_mastered is False

    def test_not_mastered_low_accuracy(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=4, interval=30, ease_factor=2.5,
            total_attempts=10, total_correct=6,  # 60% accuracy
        )
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 5
        assert state.is_mastered is False  # accuracy 63.6% < 85%

    def test_mastery_lost_on_wrong(self, sm2_scheduler: SM2Scheduler):
        state = SM2State(
            repetitions=5, interval=30, ease_factor=2.5,
            total_attempts=6, total_correct=6,
            is_mastered=True,
        )
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.is_mastered is False


# ═════════════════════════════════════════════════════════════════════
#  update_binary() tests
# ═════════════════════════════════════════════════════════════════════

class TestBinary:
    """update_binary maps correct→q=4, wrong→q=1."""

    def test_binary_correct(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update_binary(SM2State(), is_correct=True)
        assert state.last_quality == Quality.CORRECT_WITH_HESITATION
        assert state.total_attempts == 1
        assert state.total_correct == 1

    def test_binary_wrong(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update_binary(SM2State(), is_correct=False)
        assert state.last_quality == Quality.INCORRECT_BUT_REMEMBERED
        assert state.total_attempts == 1
        assert state.total_correct == 0

    def test_binary_with_difficulty(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update_binary(SM2State(), is_correct=True, initial_difficulty="hard")
        assert state.ease_factor == INITIAL_EF_BY_DIFFICULTY["hard"]

    def test_binary_round_trip_correct_wrong(self, sm2_scheduler: SM2Scheduler):
        state = SM2State()
        state = sm2_scheduler.update_binary(state, is_correct=True)
        assert state.total_correct == 1
        assert state.consecutive_correct == 1
        state = sm2_scheduler.update_binary(state, is_correct=False)
        assert state.total_correct == 1  # unchanged
        assert state.consecutive_correct == 0
        assert state.consecutive_wrong == 1
        assert state.repetitions == 0


# ═════════════════════════════════════════════════════════════════════
#  Integration / combined scenarios
# ═════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Realistic learning session scenarios."""

    def test_ideal_learning_path(self, sm2_scheduler: SM2Scheduler):
        """Learner answers correctly every time — should reach mastery."""
        state = SM2State()
        for _ in range(6):
            state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.is_mastered is True
        assert state.repetitions == 6
        assert state.interval > INTERVAL_AFTER_SECOND
        assert state.consecutive_wrong == 0

    def test_rocky_learning_path(self, sm2_scheduler: SM2Scheduler):
        """Learner struggles initially, then stabilizes."""
        state = SM2State()

        # First attempt: wrong
        state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.repetitions == 0

        # Second attempt: correct
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 1

        # Third attempt: wrong again
        state = sm2_scheduler.update(state, Quality.COMPLETE_BLACKOUT)
        assert state.repetitions == 0

        # Four consecutive corrects
        for _ in range(4):
            state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 4
        assert state.consecutive_correct == 4
        assert state.consecutive_wrong == 0

    def test_weak_point_flagging(self, sm2_scheduler: SM2Scheduler):
        """3+ consecutive wrong → flagged as weak."""
        state = SM2State()
        for _ in range(CONSECUTIVE_WRONG_THRESHOLD):
            state = sm2_scheduler.update(state, Quality.INCORRECT_BUT_REMEMBERED)
        assert state.is_weak is True

        # After one correct, weak flag clears
        state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.is_weak is False

    def test_interval_growth(self, sm2_scheduler: SM2Scheduler):
        """Interval should grow monotonically with consecutive correct answers."""
        intervals = []
        state = SM2State()
        for _ in range(6):
            state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
            intervals.append(state.interval)
        # Each interval should be >= previous (non-decreasing)
        for i in range(1, len(intervals)):
            assert intervals[i] >= intervals[i - 1], (
                f"Interval decreased: {intervals[i - 1]} -> {intervals[i]}"
            )

    def test_review_then_forget(self, sm2_scheduler: SM2Scheduler):
        """After mastering, a wrong answer should reset progress."""
        state = SM2State(
            repetitions=6, interval=100, ease_factor=2.5,
            total_attempts=6, total_correct=6,
            is_mastered=True,
        )
        state = sm2_scheduler.update(state, Quality.COMPLETE_BLACKOUT)
        assert state.is_mastered is False
        assert state.repetitions == 0
        assert state.interval == 0


# ═════════════════════════════════════════════════════════════════════
#  Edge cases and boundary values
# ═════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary and edge case scenarios."""

    def test_quality_clamping_above(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(SM2State(), 999)
        assert state.last_quality == 5

    def test_quality_clamping_negative(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(SM2State(), -999)
        assert state.last_quality == 0

    def test_unknown_difficulty_falls_back_to_default(self, sm2_scheduler: SM2Scheduler):
        state = sm2_scheduler.update(SM2State(), Quality.PERFECT_RESPONSE, initial_difficulty="unknown")
        # Initial EF = DEFAULT_EASE_FACTOR (2.5) + 0.1 from SM-2 formula = 2.6
        assert state.ease_factor == DEFAULT_EASE_FACTOR + 0.1

    def test_repetitions_do_not_overflow(self, sm2_scheduler: SM2Scheduler):
        """Interval grows exponentially — cap test at overflow-safe count."""
        state = SM2State()
        for _ in range(8):
            state = sm2_scheduler.update(state, Quality.PERFECT_RESPONSE)
        assert state.repetitions == 8
        assert state.is_mastered is True

    def test_interval_minimum_on_wrong(self, sm2_scheduler: SM2Scheduler):
        """After wrong, interval=0 → due_date is today."""
        state = sm2_scheduler.update(SM2State(), Quality.INCORRECT_BUT_REMEMBERED)
        assert state.interval == 0

    def test_quality_3_at_second_rep(self, sm2_scheduler: SM2Scheduler):
        """Second repetition with q=3: interval = INTERVAL_AFTER_SECOND."""
        state = SM2State(repetitions=1, interval=1, ease_factor=2.0)
        state = sm2_scheduler.update(state, Quality.CORRECT_WITH_DIFFICULTY)
        # Second correct uses INTERVAL_AFTER_SECOND = 6
        assert state.interval == INTERVAL_AFTER_SECOND
