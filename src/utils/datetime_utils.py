"""Time-related helpers."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    """Return the current UTC time as a naive ``datetime``.

    Drop-in replacement for the deprecated ``datetime.utcnow()`` that avoids
    the ``DeprecationWarning`` while keeping the same naive-UTC semantics
    expected by the rest of the codebase (e.g. naive ``DateTime`` columns).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local_date(performed_at_utc: datetime, tz_name: str) -> date:
    """Convert a naive-UTC ``datetime`` (as stored in the DB) to the
    calendar date it falls on in ``tz_name``.

    Used to group per-set timestamps into calendar days for statistics
    (GYM-4): storage is always UTC, but "day" boundaries must follow
    ``settings.timezone``, not UTC midnight.
    """
    aware_utc = performed_at_utc.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(ZoneInfo(tz_name)).date()


def period_bounds_utc(
    period: str, tz_name: str, *, now_utc: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """Return naive-UTC ``[start, end)`` bounds for a statistics period.

    ``period`` is one of:

    - ``"day"`` — the current calendar day (00:00 to the following 00:00),
      local to ``tz_name`` (GYM-21: "today" for the nutrition tracker —
      what UTC-based day boundaries used to get wrong, see
      ``DailyNutritionRepository.get_today_total``/``get_meals_for_local_day``).
    - ``"week"`` — the current calendar week (Monday 00:00 to the following
      Monday 00:00), local to ``tz_name``.
    - ``"month"`` — the current calendar month, local to ``tz_name``.
    - ``"all"`` — no bounds; returns ``(None, None)``.

    "Current" is anchored on ``now_utc`` (naive UTC; defaults to
    :func:`utcnow`) converted to ``tz_name`` — periods must be computed in
    ``settings.timezone``, storage stays UTC (GYM-4). Raises ``ValueError``
    for any other ``period``.
    """
    if period == "all":
        return None, None
    if period not in ("day", "week", "month"):
        raise ValueError(f"Unknown period: {period!r}")

    tz = ZoneInfo(tz_name)
    now_local = (now_utc or utcnow()).replace(tzinfo=timezone.utc).astimezone(tz)

    if period == "day":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
    elif period == "week":
        start_local = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_local = start_local + timedelta(days=7)
    else:  # month
        start_local = now_local.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)

    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
