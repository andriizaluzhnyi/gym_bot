"""Tests for GYM-13a: the achievement catalog and evaluate_achievements()
(src/services/achievements.py).

No DB needed — WorkoutSession/WorkoutSet are plain SQLAlchemy declarative
models, so building them in memory (never added to a session) and
assigning `.sets` directly is enough to drive the pure
evaluate_achievements(), same approach as test_personal_records.py (GYM-7).
AchievementsService itself (the DB read/write half) is covered in
test_webapp_achievements.py against a real DB.
"""

from datetime import date, datetime, timedelta

from src.database.models import WorkoutSession, WorkoutSet
from src.services.achievements import ACHIEVEMENTS, evaluate_achievements

TZ = "Europe/Kyiv"
ALL_CODES = {a.code for a in ACHIEVEMENTS}


def _session(
    *, session_id: int, performed_at: datetime, sets: list[dict]
) -> WorkoutSession:
    workout_session = WorkoutSession(
        id=session_id,
        user_id="00000000-0000-0000-0000-000000000001",
        performed_at=performed_at,
        completed_at=performed_at,
    )
    workout_session.sets = [
        WorkoutSet(
            session_id=session_id,
            user_id="00000000-0000-0000-0000-000000000001",
            exercise_name=s.get("exercise_name", "Жим лежачи"),
            muscle_group=s.get("muscle_group", "Груди"),
            set_number=s.get("set_number", 1),
            weight=s["weight"],
            reps=s["reps"],
            performed_at=performed_at,
        )
        for s in sets
    ]
    return workout_session


class TestEmptyHistory:
    def test_no_sessions_unlocks_nothing(self):
        unlocked = evaluate_achievements([], today=date(2026, 1, 15), tz_name=TZ)
        assert unlocked == []


class TestFirstPr:
    def test_first_logged_set_unlocks_first_pr(self):
        sessions = [_session(
            session_id=1, performed_at=datetime(2026, 1, 1, 10, 0),
            sets=[{"weight": 60.0, "reps": 10}],
        )]
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 1), tz_name=TZ
        )}
        assert "FIRST_PR" in codes

    def test_already_unlocked_first_pr_is_skipped(self):
        sessions = [_session(
            session_id=1, performed_at=datetime(2026, 1, 1, 10, 0),
            sets=[{"weight": 60.0, "reps": 10}],
        )]
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 1), tz_name=TZ,
            already_unlocked={"FIRST_PR"},
        )}
        assert "FIRST_PR" not in codes


class TestWorkoutCountAchievements:
    def _sessions(self, count: int) -> list[WorkoutSession]:
        return [
            _session(
                session_id=i,
                performed_at=datetime(2026, 1, 1, 10, 0) + timedelta(days=i),
                sets=[{"weight": 10.0, "reps": 1}],
            )
            for i in range(count)
        ]

    def test_ninth_workout_does_not_unlock_workouts_10(self):
        codes = {a.code for a in evaluate_achievements(
            self._sessions(9), today=date(2026, 1, 20), tz_name=TZ
        )}
        assert "WORKOUTS_10" not in codes

    def test_tenth_workout_unlocks_workouts_10_only(self):
        codes = {a.code for a in evaluate_achievements(
            self._sessions(10), today=date(2026, 1, 20), tz_name=TZ
        )}
        assert "WORKOUTS_10" in codes
        assert "WORKOUTS_50" not in codes
        assert "WORKOUTS_100" not in codes

    def test_fiftieth_workout_unlocks_10_and_50(self):
        codes = {a.code for a in evaluate_achievements(
            self._sessions(50), today=date(2026, 3, 1), tz_name=TZ
        )}
        assert {"WORKOUTS_10", "WORKOUTS_50"} <= codes
        assert "WORKOUTS_100" not in codes

    def test_hundredth_workout_unlocks_all_three_count_thresholds(self):
        codes = {a.code for a in evaluate_achievements(
            self._sessions(100), today=date(2026, 6, 1), tz_name=TZ
        )}
        assert {"WORKOUTS_10", "WORKOUTS_50", "WORKOUTS_100"} <= codes


class TestVolumeAchievement:
    def test_below_10_tonnes_does_not_unlock(self):
        sessions = [_session(
            session_id=1, performed_at=datetime(2026, 1, 1, 10, 0),
            sets=[{"weight": 100.0, "reps": 10}],  # 1000 kg
        )]
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 1), tz_name=TZ
        )}
        assert "VOLUME_10T" not in codes

    def test_10_tonnes_across_sessions_unlocks(self):
        sessions = [
            _session(
                session_id=i,
                performed_at=datetime(2026, 1, 1, 10, 0) + timedelta(days=i),
                sets=[{"weight": 100.0, "reps": 10}],  # 1000 kg each
            )
            for i in range(10)
        ]
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 20), tz_name=TZ
        )}
        assert "VOLUME_10T" in codes


class TestStreakAchievements:
    def _weekly_sessions(self, weeks: int) -> list[WorkoutSession]:
        # One session per week, weeks 2..(1+weeks) of 2026, each on a
        # Monday — matches tests/test_streak.py's ISO-week fixtures.
        return [
            _session(
                session_id=i,
                performed_at=datetime(2026, 1, 5, 10, 0) + timedelta(weeks=i),
                sets=[{"weight": 10.0, "reps": 1}],
            )
            for i in range(weeks)
        ]

    def test_three_week_streak_unlocks_nothing(self):
        sessions = self._weekly_sessions(3)
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 19), tz_name=TZ
        )}
        assert "STREAK_4_WEEKS" not in codes

    def test_four_week_streak_unlocks_streak_4_only(self):
        sessions = self._weekly_sessions(4)
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 1, 26), tz_name=TZ
        )}
        assert "STREAK_4_WEEKS" in codes
        assert "STREAK_12_WEEKS" not in codes

    def test_twelve_week_streak_unlocks_both(self):
        sessions = self._weekly_sessions(12)
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 3, 23), tz_name=TZ
        )}
        assert {"STREAK_4_WEEKS", "STREAK_12_WEEKS"} <= codes

    def test_streak_achievement_stays_earned_after_it_breaks(self):
        # A 4-week streak long past, then a big gap up to `today`.
        sessions = self._weekly_sessions(4)
        codes = {a.code for a in evaluate_achievements(
            sessions, today=date(2026, 6, 1), tz_name=TZ
        )}
        assert "STREAK_4_WEEKS" in codes


class TestAlreadyUnlockedIsSkippedForEveryAchievement:
    def test_everything_already_unlocked_returns_nothing(self):
        sessions = [
            _session(
                session_id=i,
                performed_at=datetime(2026, 1, 1, 10, 0) + timedelta(days=i),
                sets=[{"weight": 200.0, "reps": 10}],
            )
            for i in range(15)
        ]
        unlocked = evaluate_achievements(
            sessions, today=date(2026, 3, 1), tz_name=TZ,
            already_unlocked=ALL_CODES,
        )
        assert unlocked == []
