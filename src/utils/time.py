"""Time-related helpers."""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as a naive ``datetime``.

    Drop-in replacement for the deprecated ``datetime.utcnow()`` that avoids
    the ``DeprecationWarning`` while keeping the same naive-UTC semantics
    expected by the rest of the codebase (e.g. naive ``DateTime`` columns).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
