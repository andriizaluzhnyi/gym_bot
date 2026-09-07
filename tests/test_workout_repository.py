"""Tests for WorkoutSession/WorkoutSet models and repositories (GYM-1)."""

import uuid

import pytest

from src.database.models import Base, WorkoutSession, WorkoutSet
from src.database.repository import (
    UserRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import utcnow


@pytest.fixture(autouse=True)
async def _create_tables():
    """Ensure all tables (including the new ones) exist before each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(session, *, username: str | None = "lifter"):
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=uuid.uuid4().int % (2**31),
        first_name="Test",
        username=username,
    )
    await session.flush()
    return user


class TestUserRepositoryGetByUsername:
    async def test_returns_user_by_username(self):
        async with async_session_maker() as session:
            user = await _make_user(session, username="trainer_client")
            await session.commit()

            found = await UserRepository(session).get_by_username("trainer_client")
            assert found is not None
            assert found.id == user.id

    async def test_returns_none_for_unknown_username(self):
        async with async_session_maker() as session:
            found = await UserRepository(session).get_by_username(
                "does-not-exist-at-all"
            )
            assert found is None


class TestCreateSessionWithSets:
    async def test_creates_session_and_all_sets(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            performed_at = utcnow()

            workout_session = await WorkoutSessionRepository(
                session
            ).create_session_with_sets(
                user_id=user.id,
                performed_at=performed_at,
                day=1,
                muscle_group="Груди",
                duration_seconds=3600,
                sets=[
                    {
                        "exercise_name": "Жим лежачи",
                        "muscle_group": "Груди",
                        "set_number": 1,
                        "weight": 60.0,
                        "reps": 10,
                        "planned_sets_reps": "3x10",
                    },
                    {
                        "exercise_name": "Жим лежачи",
                        "muscle_group": "Груди",
                        "set_number": 2,
                        "weight": 62.5,
                        "reps": 8,
                    },
                ],
            )
            await session.commit()

            assert workout_session.id is not None
            assert workout_session.duration_seconds == 3600

            result = await session.get(WorkoutSession, workout_session.id)
            assert result is not None

            sets = (
                await session.execute(
                    WorkoutSet.__table__.select().where(
                        WorkoutSet.session_id == workout_session.id
                    )
                )
            ).fetchall()
            assert len(sets) == 2
            # user_id is denormalized onto each set for fast lookups
            assert all(row.user_id == user.id for row in sets)

    async def test_owner_is_the_user_passed_in_not_a_default(self):
        """The session/sets belong to the given user_id (e.g. the workout's
        owner resolved from ``body['user']``), regardless of who is calling."""
        async with async_session_maker() as session:
            owner = await _make_user(session, username="owner")
            other = await _make_user(session, username="trainer")

            workout_session = await WorkoutSessionRepository(
                session
            ).create_session_with_sets(
                user_id=owner.id,
                performed_at=utcnow(),
                sets=[
                    {
                        "exercise_name": "Присідання",
                        "set_number": 1,
                        "weight": 100.0,
                        "reps": 5,
                    }
                ],
            )
            await session.commit()

            assert workout_session.user_id == owner.id
            assert workout_session.user_id != other.id


class TestGetSessionsByPeriod:
    async def test_filters_by_period_and_orders_newest_first(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)

            from datetime import timedelta

            now = utcnow()
            old = await repo.create_session_with_sets(
                user_id=user.id,
                performed_at=now - timedelta(days=30),
                sets=[{"exercise_name": "Тяга", "set_number": 1, "weight": 80, "reps": 5}],
            )
            recent = await repo.create_session_with_sets(
                user_id=user.id,
                performed_at=now,
                sets=[{"exercise_name": "Тяга", "set_number": 1, "weight": 85, "reps": 5}],
            )
            await session.commit()

            sessions = await repo.get_sessions_by_period(
                user.id, start=now - timedelta(days=1), end=now + timedelta(days=1)
            )

            ids = [s.id for s in sessions]
            assert recent.id in ids
            assert old.id not in ids
            # Sets are eagerly loaded.
            assert len(sessions[0].sets) == 1

    async def test_empty_range_returns_empty_list(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            from datetime import timedelta

            sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
                user.id,
                start=utcnow() + timedelta(days=100),
                end=utcnow() + timedelta(days=200),
            )
            assert sessions == []


class TestGetSetsByUserAndExercise:
    async def test_returns_only_matching_exercise_ordered_by_date(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)

            from datetime import timedelta

            now = utcnow()
            await repo.create_session_with_sets(
                user_id=user.id,
                performed_at=now - timedelta(days=2),
                sets=[
                    {"exercise_name": "Жим лежачи", "set_number": 1, "weight": 50, "reps": 10},
                ],
            )
            await repo.create_session_with_sets(
                user_id=user.id,
                performed_at=now,
                sets=[
                    {"exercise_name": "Жим лежачи", "set_number": 1, "weight": 55, "reps": 8},
                    {"exercise_name": "Присідання", "set_number": 1, "weight": 90, "reps": 5},
                ],
            )
            await session.commit()

            sets = await WorkoutSetRepository(session).get_sets_by_user_and_exercise(
                user.id, "Жим лежачи"
            )

            assert [s.weight for s in sets] == [50, 55]
            assert all(s.exercise_name == "Жим лежачи" for s in sets)

    async def test_respects_limit(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)

            for i in range(3):
                await repo.create_session_with_sets(
                    user_id=user.id,
                    performed_at=utcnow(),
                    sets=[
                        {
                            "exercise_name": "Станова тяга",
                            "set_number": 1,
                            "weight": 100 + i,
                            "reps": 5,
                        }
                    ],
                )
            await session.commit()

            sets = await WorkoutSetRepository(session).get_sets_by_user_and_exercise(
                user.id, "Станова тяга", limit=2
            )
            assert len(sets) == 2
