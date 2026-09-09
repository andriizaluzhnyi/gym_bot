"""Tests for GYM-30/GYM-46: src/services/workout_program_parsing.py —
pure sets_reps helpers shared between the bot's program-creation FSM
(src/bot/handlers/workout_program.py) and
`POST /api/workout/program/exercise` (src/webapp/server.py).
"""

from src.services.workout_program_parsing import (
    MAX_SETS_REPS_LENGTH,
    MUSCLE_GROUPS,
    combine_sets_reps,
    is_valid_sets_reps,
    looks_like_combined_sets_reps,
    normalize_sets_reps,
    parse_sets_reps,
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


class TestParseSetsReps:
    def test_single_slash_block(self):
        assert parse_sets_reps("3/10") == [(3, 10)]

    def test_single_pipe_block(self):
        assert parse_sets_reps("4|8") == [(4, 8)]

    def test_x_and_cyrillic_kha_are_accepted_separators(self):
        assert parse_sets_reps("4x10") == [(4, 10)]
        assert parse_sets_reps("4х10") == [(4, 10)]

    def test_bare_number_alone_parses_with_zero_reps(self):
        assert parse_sets_reps("5") == [(5, 0)]

    def test_whitespace_around_separator_is_tolerated(self):
        assert parse_sets_reps("3 / 10") == [(3, 10)]

    def test_multiple_comma_separated_blocks(self):
        assert parse_sets_reps("2/12, 4/6") == [(2, 12), (4, 6)]

    def test_untidy_spacing_and_mixed_separators_across_blocks(self):
        assert parse_sets_reps("2/12,4x6") == [(2, 12), (4, 6)]

    def test_bare_number_is_only_valid_as_the_sole_block(self):
        assert parse_sets_reps("3, 4/6") is None

    def test_zero_sets_is_invalid(self):
        assert parse_sets_reps("0/10") is None
        assert parse_sets_reps("0") is None

    def test_zero_reps_is_invalid_for_a_combined_block(self):
        assert parse_sets_reps("3/0") is None

    def test_non_numeric_parts_are_invalid(self):
        assert parse_sets_reps("три/десять") is None
        assert parse_sets_reps("a/b") is None

    def test_double_separator_is_invalid(self):
        assert parse_sets_reps("3//10") is None

    def test_empty_or_blank_is_invalid(self):
        assert parse_sets_reps("") is None
        assert parse_sets_reps("   ") is None

    def test_trailing_comma_is_invalid(self):
        assert parse_sets_reps("3/10,") is None

    def test_free_text_is_invalid(self):
        assert parse_sets_reps("до відмови") is None


class TestNormalizeSetsReps:
    def test_canonical_single_block_is_unchanged(self):
        assert normalize_sets_reps("3/10") == "3/10"

    def test_pipe_and_x_separators_normalize_to_slash(self):
        assert normalize_sets_reps("4|8") == "4/8"
        assert normalize_sets_reps("4x10") == "4/10"

    def test_bare_number_normalizes_to_itself(self):
        assert normalize_sets_reps("5") == "5"

    def test_untidy_multi_block_input_normalizes_to_canonical_form(self):
        assert normalize_sets_reps("2/12,4x6") == "2/12, 4/6"

    def test_extra_whitespace_is_collapsed(self):
        assert normalize_sets_reps("2 / 12 ,  4 / 6") == "2/12, 4/6"

    def test_invalid_input_returns_none(self):
        assert normalize_sets_reps("до відмови") is None
        assert normalize_sets_reps("") is None


class TestIsValidSetsReps:
    def test_slash_format_is_valid(self):
        assert is_valid_sets_reps("3/10") is True

    def test_pipe_format_is_valid(self):
        assert is_valid_sets_reps("4|8") is True

    def test_bare_number_is_valid(self):
        assert is_valid_sets_reps("5") is True

    def test_whitespace_around_separator_is_tolerated(self):
        assert is_valid_sets_reps("3 / 10") is True

    def test_multiple_comma_separated_blocks_are_valid(self):
        assert is_valid_sets_reps("2/12, 4/6") is True

    def test_untidy_multi_block_input_is_valid(self):
        assert is_valid_sets_reps("2/12,4x6") is True

    def test_free_text_is_invalid(self):
        assert is_valid_sets_reps("до відмови") is False

    def test_empty_string_is_invalid(self):
        assert is_valid_sets_reps("") is False

    def test_non_numeric_parts_are_invalid(self):
        assert is_valid_sets_reps("три/десять") is False

    def test_double_separator_is_invalid(self):
        assert is_valid_sets_reps("3//10") is False

    def test_bare_number_mixed_with_a_combined_block_is_invalid(self):
        assert is_valid_sets_reps("3, 4/6") is False

    def test_zero_sets_or_reps_is_invalid(self):
        assert is_valid_sets_reps("0/10") is False
        assert is_valid_sets_reps("3/0") is False

    def test_value_that_normalizes_within_the_column_limit_is_valid(self):
        # 10 blocks of "1/1" joined by ", " is 48 chars — within
        # MAX_SETS_REPS_LENGTH (50).
        value = ", ".join(["1/1"] * 10)
        assert len(value) <= MAX_SETS_REPS_LENGTH
        assert is_valid_sets_reps(value) is True

    def test_value_that_normalizes_past_the_column_limit_is_invalid(self):
        # 10 blocks of "11/11" joined by ", " is 68 chars — over the limit.
        value = ", ".join(["11/11"] * 10)
        assert len(value) > MAX_SETS_REPS_LENGTH
        assert is_valid_sets_reps(value) is False


def test_muscle_groups_is_a_non_empty_list_of_strings():
    assert isinstance(MUSCLE_GROUPS, list)
    assert len(MUSCLE_GROUPS) > 0
    assert all(isinstance(g, str) for g in MUSCLE_GROUPS)
