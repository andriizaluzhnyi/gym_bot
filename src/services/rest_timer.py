"""Pure decision logic for the workout rest-timer reminder (GYM-47).

Extracted out of the scheduled task inside ``api_start_rest_timer``
(``src/webapp/server.py``) so the "should this reminder still fire" rule
has a name and can be unit-tested without ``asyncio.sleep``, a bot
instance, or a live database — the function just looks at the
``WorkoutSession`` row the caller already re-read and says yes/no.
"""

from src.database.models import WorkoutSession


def should_send_rest_reminder(session: WorkoutSession | None) -> bool:
    """Whether a scheduled rest-timer reminder should still be sent.

    ``session`` is the ``WorkoutSession`` the timer was started for,
    re-read from the DB right before the reminder would fire (``None`` if
    the row no longer exists — treated the same as "already finished",
    since a session is never deleted in normal operation). Returns
    ``False`` once ``completed_at`` is set.

    The common case this closes: the user logs the workout's last set,
    which starts a fresh rest timer, and immediately taps "Завершити
    тренування" before the timer runs out. Without this check the
    scheduled task would still send "⏱️ Час відпочинку закінчився!" for a
    workout that's already done.

    Only meaningful when a ``session_id`` was actually supplied to
    ``POST /api/workout/rest-timer`` in the first place — a caller with no
    ``session_id`` (an older client, or a timer started while the workout
    session itself couldn't be created, e.g. offline) has nothing to check
    against and keeps sending unconditionally, same as before this ticket;
    that decision is made by the caller *before* it looks up a session at
    all, not by this function.
    """
    return session is not None and session.completed_at is None
