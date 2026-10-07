"""Helpers for a group reminder's list of daily send times.

A ``GroupChat`` stores each reminder type's times (``nutrition_time``,
``measurements_time``, ``photos_time``) as one comma-separated string of
``"HH:MM"`` values, e.g. ``"08:00,13:30,20:00"`` — so a trainer can set
any number of reminders per day, at any minute. Always stored sorted and
de-duplicated (see :func:`join_times`), so the string itself is a stable,
human-readable representation.
"""

import re
from datetime import time

# A sane upper bound: keeps the settings keyboard usable and the stored
# string well under the column's 255 chars (24 × "HH:MM," = 144).
MAX_REMINDER_TIMES_PER_DAY = 24

_TIME_TOKEN_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")
_SEPARATORS_RE = re.compile(r"[,;\s]+")


def normalize_time(value: str) -> str:
    """``"8:05"``/``"08.05"``/``"08:05"`` -> ``"08:05"``. Raises
    ``ValueError`` for anything that isn't a valid 24-hour time.
    """
    match = _TIME_TOKEN_RE.match(value.strip())
    if match is None:
        raise ValueError(f"Invalid time: {value!r}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time: {value!r}")
    return f"{hour:02d}:{minute:02d}"


def parse_time_input(raw: str) -> list[str]:
    """Parse free-form user input — one or more times separated by
    commas, semicolons, spaces or newlines — into a sorted, de-duplicated
    list of ``"HH:MM"`` strings. Raises ``ValueError`` naming the first
    invalid token, or if there are no times at all.
    """
    tokens = [t for t in _SEPARATORS_RE.split(raw.strip()) if t]
    if not tokens:
        raise ValueError("No times given")
    return sorted({normalize_time(t) for t in tokens})


def split_times(stored: str | None) -> list[str]:
    """The stored comma-separated column value -> sorted list of
    ``"HH:MM"``. Invalid fragments are skipped rather than raising, so a
    hand-edited/legacy value can never crash the scheduler.
    """
    result: set[str] = set()
    for token in (stored or "").split(","):
        token = token.strip()
        if not token:
            continue
        try:
            result.add(normalize_time(token))
        except ValueError:
            continue
    return sorted(result)


def join_times(times: list[str]) -> str:
    """List of ``"HH:MM"`` -> stored comma-separated value (sorted,
    de-duplicated)."""
    return ",".join(sorted({normalize_time(t) for t in times}))


def to_time(value: str) -> time:
    hour_str, minute_str = normalize_time(value).split(":")
    return time(int(hour_str), int(minute_str))
