"""Achievement catalog and unlock checks (GYM-13a).

Unlike ``src/services/personal_records.py`` / ``streak.py`` (pure
calculation, no I/O), unlocking an achievement means persisting a row — so
this module splits in two: a pure half (the catalog plus
:func:`evaluate_achievements`, unit-tested without a DB the same way
``calculate_prs``/``calculate_streak`` are) and :class:`AchievementsService`,
a thin wrapper that does the DB read/write around it. ``check_and_unlock``
is meant to be called right after a workout is saved
(``src/webapp/server.py``'s ``api_save_workout_log``), the same
non-critical spot GYM-9's PR notification plugs into.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import WorkoutSession
from src.database.repository import UserAchievementRepository, WorkoutSessionRepository
from src.services.streak import calculate_streak
from src.utils.datetime_utils import to_local_date


@dataclass(frozen=True)
class _UserStats:
    """The numbers every achievement's condition is checked against —
    computed once per :func:`evaluate_achievements` call and shared across
    the whole catalog.
    """

    workouts_count: int
    total_volume: float
    has_logged_sets: bool
    longest_streak: int


@dataclass(frozen=True)
class AchievementDefinition:
    """One entry in the fixed achievement catalog."""

    code: str
    title: str
    description: str
    is_unlocked: Callable[[_UserStats], bool]


#: Fixed in-code catalog (GYM-13a) — not a DB table, so adding or tweaking
#: an achievement is a code change, not a migration. GYM-13b's
#: ``GET /api/statistics/achievements`` is expected to merge this against a
#: user's unlocked rows to also list the still-locked ones with their
#: ``description`` as a hint.
ACHIEVEMENTS: tuple[AchievementDefinition, ...] = (
    AchievementDefinition(
        code='WORKOUTS_10', title='10 тренувань',
        description='Завершіть 10 тренувань',
        is_unlocked=lambda stats: stats.workouts_count >= 10,
    ),
    AchievementDefinition(
        code='WORKOUTS_50', title='50 тренувань',
        description='Завершіть 50 тренувань',
        is_unlocked=lambda stats: stats.workouts_count >= 50,
    ),
    AchievementDefinition(
        code='WORKOUTS_100', title='100 тренувань',
        description='Завершіть 100 тренувань',
        is_unlocked=lambda stats: stats.workouts_count >= 100,
    ),
    AchievementDefinition(
        code='STREAK_4_WEEKS', title='Серія 4 тижні',
        description='Тренуйтесь 4 тижні поспіль',
        # The best streak ever reached (GYM-12's longest_streak), not just
        # the one currently active — once earned, a badge stays earned
        # even after the streak itself later breaks.
        is_unlocked=lambda stats: stats.longest_streak >= 4,
    ),
    AchievementDefinition(
        code='STREAK_12_WEEKS', title='Серія 12 тижнів',
        description='Тренуйтесь 12 тижнів поспіль',
        is_unlocked=lambda stats: stats.longest_streak >= 12,
    ),
    AchievementDefinition(
        code='FIRST_PR', title='Перший рекорд',
        description='Залогуйте свій перший підхід',
        # Every logged set is automatically its exercise's max the moment
        # it's the first one ever recorded (GYM-7's calculate_prs), so
        # "first PR" is exactly "has logged at least one set".
        is_unlocked=lambda stats: stats.has_logged_sets,
    ),
    AchievementDefinition(
        code='VOLUME_10T', title='10 тонн',
        description='Підніміть сумарно 10 000 кг за всю історію тренувань',
        is_unlocked=lambda stats: stats.total_volume >= 10_000,
    ),
)


def _compute_stats(
    sessions: Sequence[WorkoutSession], today: date, tz_name: str
) -> _UserStats:
    all_sets = [
        workout_set
        for workout_session in sessions
        for workout_set in workout_session.sets
    ]
    session_dates = [to_local_date(s.performed_at, tz_name) for s in sessions]
    streak = calculate_streak(session_dates, today)

    return _UserStats(
        workouts_count=len(sessions),
        total_volume=sum(s.weight * s.reps for s in all_sets),
        has_logged_sets=bool(all_sets),
        longest_streak=streak['longest_streak'],
    )


def evaluate_achievements(
    sessions: Sequence[WorkoutSession],
    today: date,
    tz_name: str,
    already_unlocked: Collection[str] = (),
) -> list[AchievementDefinition]:
    """Which achievements newly unlock for a user whose (already-fetched)
    *completed* sessions are ``sessions`` — pure, no DB.

    ``already_unlocked`` is the set of ``achievement_code`` the caller
    already knows the user has, so those are skipped — a call is
    idempotent no matter how many times it runs against the same history.
    Returned in catalog order.
    """
    stats = _compute_stats(sessions, today, tz_name)
    return [
        achievement for achievement in ACHIEVEMENTS
        if achievement.code not in already_unlocked and achievement.is_unlocked(stats)
    ]


class AchievementsService:
    """Unlocks and persists achievements for a user (GYM-13a)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def check_and_unlock(
        self, user_id: uuid.UUID, today: date, tz_name: str
    ) -> list[AchievementDefinition]:
        """Check every achievement's condition against ``user_id``'s full
        history and persist any newly-satisfied one to
        ``user_achievements``.

        ``today``/``tz_name`` mirror ``calculate_streak``'s own params —
        the caller resolves "today" once (``to_local_date(utcnow(),
        settings.timezone)``) rather than this service reaching for
        ``settings`` itself. Returns just the achievements unlocked *by
        this call*, for the caller to notify the user about (same spot
        GYM-9's PR check is called from).
        """
        sessions = await WorkoutSessionRepository(self.session).get_sessions_by_period(
            user_id
        )
        achievement_repo = UserAchievementRepository(self.session)
        already_unlocked = await achievement_repo.get_unlocked_codes(user_id)

        newly_unlocked = evaluate_achievements(
            sessions, today, tz_name, already_unlocked
        )

        for achievement in newly_unlocked:
            await achievement_repo.unlock(user_id, achievement.code)

        return newly_unlocked
