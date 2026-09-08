"""Workout streak calculation (GYM-12).

Pure, DB-free logic on purpose, same convention as
``src/services/personal_records.py`` (GYM-7): :func:`calculate_streak`
takes whatever local calendar dates the caller already resolved (from
``WorkoutSession.performed_at`` via ``to_local_date``, ``settings.timezone``)
and does no I/O itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta

#: The unit calculate_streak() / GET /api/statistics/streak report the
#: streak in — weeks, not days, so a rest day (or two) within a week
#: doesn't reset it.
STREAK_UNIT = 'week'

_IsoWeek = tuple[int, int]


def _iso_week(day: date) -> _IsoWeek:
    """``(iso_year, iso_week)`` for ``day`` — the week identity streaks are
    counted in. ISO weeks run Monday-Sunday, so a Sunday and the Monday
    right after it always land in different weeks.
    """
    iso = day.isocalendar()
    return iso[0], iso[1]


def _week_start(iso_week: _IsoWeek) -> date:
    """The Monday of ISO week ``iso_week``."""
    iso_year, week = iso_week
    return date.fromisocalendar(iso_year, week, 1)


def _prev_week(iso_week: _IsoWeek) -> _IsoWeek:
    return _iso_week(_week_start(iso_week) - timedelta(days=7))


def _next_week(iso_week: _IsoWeek) -> _IsoWeek:
    return _iso_week(_week_start(iso_week) + timedelta(days=7))


def calculate_streak(session_dates: Sequence[date], today: date) -> dict:
    """How many consecutive ISO weeks (Monday-Sunday) had at least one
    workout, ending at ``today``'s week.

    ``current_streak`` walks backward from ``today``'s week: if that week
    has no session yet, it's skipped — not counted, but it doesn't reset
    the streak either, since the week isn't over — and the walk continues
    from the previous week; from there, each consecutive week with a
    session adds one, stopping at the first fully-skipped week. So only a
    completed week with zero sessions breaks the streak, never the current
    in-progress one.

    ``longest_streak`` is the longest run of consecutive weeks with a
    session found anywhere in ``session_dates`` (always >= the returned
    ``current_streak``, since that streak is itself one such run). Both
    are ``0`` for an empty ``session_dates``.
    """
    weeks_with_sessions = {_iso_week(d) for d in session_dates}

    if not weeks_with_sessions:
        return {'current_streak': 0, 'longest_streak': 0, 'unit': STREAK_UNIT}

    week = _iso_week(today)
    if week not in weeks_with_sessions:
        week = _prev_week(week)

    current_streak = 0
    while week in weeks_with_sessions:
        current_streak += 1
        week = _prev_week(week)

    longest_streak = 0
    run = 0
    previous_week: _IsoWeek | None = None
    for week in sorted(weeks_with_sessions, key=_week_start):
        is_consecutive = (
            previous_week is not None and week == _next_week(previous_week)
        )
        run = run + 1 if is_consecutive else 1
        longest_streak = max(longest_streak, run)
        previous_week = week

    return {
        'current_streak': current_streak,
        'longest_streak': longest_streak,
        'unit': STREAK_UNIT,
    }
