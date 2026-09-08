"""Tests for GYM-30: src/services/workout_program_parsing.py — pure
sets_reps helpers shared between the bot's program-creation FSM
(src/bot/handlers/workout_program.py) and
`POST /api/workout/program/exercise` (src/webapp/server.py).
"""

from src.services.workout_program_parsing import (
    MUSCLE_GROUPS,
    combine_sets_reps,
    is_valid_sets_reps,
    looks_like_combined_sets_reps,
)


class TestLooksLikeCombinedSetsReps:
    def test_slash_separator_is_combined(self):
        assert looks_like_combined_sets_reps("3/10") is True

    def test_pipe_separator_is_combined(self):
        assert looks_like_combined_sets_reps("3|10") is True

    def test_bare_number_is_not_combined(self):
        assert looks_like_combined_sets_reps("3") is False

    def test_free_text_without_separator_is_not_combined(self):
        assert looks_like_combined_sets_reps("три підходи") is False


class TestCombineSetsReps:
    def test_joins_sets_and_reps_with_slash(self):
        assert combine_sets_reps("3", "10") == "3/10"

    def test_empty_reps_returns_sets_unchanged(self):
        assert combine_sets_reps("3/10", "") == "3/10"

    def test_strips_whitespace_from_both_parts(self):
        assert combine_sets_reps(" 3 ", " 10 ") == "3/10"

    def test_empty_reps_preserves_pipe_separator_already_in_sets(self):
        assert combine_sets_reps("4|8", "") == "4|8"


class TestIsValidSetsReps:
    def test_slash_format_is_valid(self):
        assert is_valid_sets_reps("3/10") is True

    def test_pipe_format_is_valid(self):
        assert is_valid_sets_reps("4|8") is True

    def test_bare_number_is_valid(self):
        assert is_valid_sets_reps("5") is True

    def test_whitespace_around_separator_is_tolerated(self):
        assert is_valid_sets_reps("3 / 10") is True

    def test_free_text_is_invalid(self):
        assert is_valid_sets_reps("до відмови") is False

    def test_empty_string_is_invalid(self):
        assert is_valid_sets_reps("") is False

    def test_non_numeric_parts_are_invalid(self):
        assert is_valid_sets_reps("три/десять") is False

    def test_double_separator_is_invalid(self):
        assert is_valid_sets_reps("3//10") is False


def test_muscle_groups_is_a_non_empty_list_of_strings():
    assert isinstance(MUSCLE_GROUPS, list)
    assert len(MUSCLE_GROUPS) > 0
    assert all(isinstance(g, str) for g in MUSCLE_GROUPS)
