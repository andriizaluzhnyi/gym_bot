"""Tests for src/utils/reminder_times.py — parsing/storing a group
reminder's list of daily times."""

import pytest

from src.utils.reminder_times import (
    join_times,
    normalize_time,
    parse_time_input,
    split_times,
)


class TestNormalizeTime:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("8:05", "08:05"), ("08:05", "08:05"), ("8.05", "08:05"), ("23:59", "23:59"),
         ("0:00", "00:00")],
    )
    def test_valid(self, raw, expected):
        assert normalize_time(raw) == expected

    @pytest.mark.parametrize("raw", ["24:00", "12:60", "8", "8:5", "ab:cd", "", "-1:00"])
    def test_invalid(self, raw):
        with pytest.raises(ValueError):
            normalize_time(raw)


class TestParseTimeInput:
    def test_mixed_separators_sorted_and_deduplicated(self):
        assert parse_time_input("21:45, 8:15;13:00\n08:15") == ["08:15", "13:00", "21:45"]

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_time_input("  ,  ")

    def test_one_bad_token_raises(self):
        with pytest.raises(ValueError):
            parse_time_input("08:00, nine")


class TestSplitJoin:
    def test_round_trip(self):
        assert split_times(join_times(["20:00", "08:00", "08:00"])) == ["08:00", "20:00"]

    def test_split_skips_garbage(self):
        assert split_times(" 20:00,,bad, 8:00") == ["08:00", "20:00"]

    def test_split_empty(self):
        assert split_times("") == []
        assert split_times(None) == []
