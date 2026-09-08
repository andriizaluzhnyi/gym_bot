"""Tests for GYM-12: streak calculation (src/services/streak.py).

No DB needed — calculate_streak() is a pure function over plain
datetime.date values.
"""

from datetime import date

from src.services.streak import calculate_streak


class TestEmpty:
    def test_no_sessions_returns_zero_streaks(self):
        assert calculate_streak([], today=date(2026, 1, 15)) == {
            'current_streak': 0, 'longest_streak': 0, 'unit': 'week',
        }


class TestCurrentWeekWithoutTraining:
    def test_current_incomplete_week_does_not_break_the_streak(self):
        # Trained the two weeks before this one; nothing yet this week
        # (a Wednesday) — the streak should still read 2, not 0.
        session_dates = [
            date(2026, 1, 5),   # Mon, week 2
            date(2026, 1, 12),  # Mon, week 3
        ]
        result = calculate_streak(session_dates, today=date(2026, 1, 21))  # Wed, week 4

        assert result['current_streak'] == 2
        assert result['longest_streak'] == 2

    def test_current_week_with_training_counts_it(self):
        session_dates = [
            date(2026, 1, 5),   # week 2
            date(2026, 1, 12),  # week 3
            date(2026, 1, 20),  # week 4 — same week as `today`
        ]
        result = calculate_streak(session_dates, today=date(2026, 1, 21))  # week 4

        assert result['current_streak'] == 3
        assert result['longest_streak'] == 3


class TestSkippedWeekBreaksStreak:
    def test_a_fully_skipped_completed_week_resets_current_streak(self):
        # Trained week 2, skipped week 3 entirely, trained week 4 (today).
        session_dates = [
            date(2026, 1, 5),   # week 2
            date(2026, 1, 20),  # week 4
        ]
        result = calculate_streak(session_dates, today=date(2026, 1, 21))  # week 4

        assert result['current_streak'] == 1
        assert result['longest_streak'] == 1

    def test_old_streak_reads_zero_once_a_full_week_has_passed(self):
        # Trained weeks 2-3, then nothing — today is week 5, so week 4 was
        # a fully-skipped completed week.
        session_dates = [
            date(2026, 1, 5),   # week 2
            date(2026, 1, 12),  # week 3
        ]
        result = calculate_streak(session_dates, today=date(2026, 1, 26))  # week 5

        assert result['current_streak'] == 0
        assert result['longest_streak'] == 2


class TestWeekBoundary:
    def test_sunday_and_following_monday_are_different_weeks(self):
        # 2026-01-18 is a Sunday, 2026-01-19 the Monday right after —
        # ISO weeks run Mon-Sun, so these must land in different weeks
        # and contribute two consecutive weeks, not one.
        session_dates = [date(2026, 1, 18), date(2026, 1, 19)]
        result = calculate_streak(session_dates, today=date(2026, 1, 19))

        assert result['current_streak'] == 2
        assert result['longest_streak'] == 2

    def test_two_sessions_same_iso_week_count_as_one_week(self):
        # Monday and Sunday of the same ISO week (2026-01-12 .. 01-18).
        session_dates = [date(2026, 1, 12), date(2026, 1, 18)]
        result = calculate_streak(session_dates, today=date(2026, 1, 15))

        assert result['current_streak'] == 1
        assert result['longest_streak'] == 1


class TestLongestStreak:
    def test_longest_streak_can_exceed_current_streak(self):
        # A 3-week streak long ago, a gap, then today's (still-open,
        # untrained) week only.
        session_dates = [
            date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19),  # weeks 2-4
        ]
        result = calculate_streak(session_dates, today=date(2026, 2, 16))  # week 8

        assert result['current_streak'] == 0
        assert result['longest_streak'] == 3

    def test_multiple_runs_picks_the_longest(self):
        session_dates = [
            date(2026, 1, 5),   # week 2 — run of 1
            date(2026, 1, 19),  # week 4 \
            date(2026, 1, 26),  # week 5  } run of 3
            date(2026, 2, 2),   # week 6 /
        ]
        result = calculate_streak(session_dates, today=date(2026, 2, 2))

        assert result['longest_streak'] == 3
