"""Tests for src/utils/datetime_utils.py — period/day boundaries used by
the statistics endpoints (GYM-4) must follow settings.timezone, not UTC.
"""

from datetime import datetime

import pytest

from src.utils.datetime_utils import period_bounds_utc, to_local_date

KYIV = "Europe/Kyiv"  # UTC+2 (EET) / UTC+3 (EEST)


class TestToLocalDate:
    def test_converts_to_local_calendar_day(self):
        # 23:30 UTC on Jan 1st is already Jan 2nd in Kyiv (UTC+2 in winter).
        dt = datetime(2026, 1, 1, 23, 30)
        assert to_local_date(dt, KYIV).isoformat() == "2026-01-02"

    def test_same_day_when_local_offset_does_not_cross_midnight(self):
        dt = datetime(2026, 1, 1, 10, 0)
        assert to_local_date(dt, KYIV).isoformat() == "2026-01-01"


class TestPeriodBoundsUtc:
    def test_all_period_has_no_bounds(self):
        assert period_bounds_utc("all", KYIV) == (None, None)

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            period_bounds_utc("year", KYIV)

    def test_week_bounds_are_monday_to_monday_local(self):
        # Wednesday 2026-01-07 10:00 Kyiv time (winter, UTC+2) = 08:00 UTC.
        now_utc = datetime(2026, 1, 7, 8, 0)
        start, end = period_bounds_utc("week", KYIV, now_utc=now_utc)

        # Monday 2026-01-05 00:00 Kyiv == 2026-01-04 22:00 UTC.
        assert start == datetime(2026, 1, 4, 22, 0)
        # Following Monday 2026-01-12 00:00 Kyiv == 2026-01-11 22:00 UTC.
        assert end == datetime(2026, 1, 11, 22, 0)

    def test_month_bounds_are_calendar_month_local(self):
        now_utc = datetime(2026, 1, 15, 12, 0)
        start, end = period_bounds_utc("month", KYIV, now_utc=now_utc)

        assert start == datetime(2025, 12, 31, 22, 0)  # Jan 1 00:00 Kyiv
        assert end == datetime(2026, 1, 31, 22, 0)  # Feb 1 00:00 Kyiv

    def test_month_bounds_roll_over_year(self):
        now_utc = datetime(2026, 12, 15, 12, 0)
        start, end = period_bounds_utc("month", KYIV, now_utc=now_utc)

        assert start == datetime(2026, 11, 30, 22, 0)  # Dec 1 00:00 Kyiv
        assert end == datetime(2026, 12, 31, 22, 0)  # Jan 1 00:00 Kyiv (2027)
