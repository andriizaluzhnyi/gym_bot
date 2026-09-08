"""Tests for draft (in-progress) workout sessions (GYM-2c).

Covers the DB-backed autosave/resume model: a session with
``completed_at is None`` is a draft; ``WorkoutSessionRepository`` exposes
starting, resuming and completing one, and ``WorkoutSetRepository`` exposes
replacing one exercise's sets in place (used by the autosave endpoint).
"""

import uuid

import pytest

from src.database.models import Base, WorkoutSet
from src.database.repository import (
    UserRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import utcnow


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(session, *, username: str | None = None):
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=uuid.uuid4().int % (2**31),
        first_name="Test",
        username=username or f"lifter_{uuid.uuid4().hex[:8]}",
    )
    await session.flush()
    return user


class TestStartAndResumeDraft:
    async def test_no_existing_draft_returns_none(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            await session.commit()

            draft = await WorkoutSessionRepository(session).get_active_draft(
                user.id, day=1, muscle_group="Груди"
            )
            assert draft is None

    async def test_start_draft_creates_uncompleted_session(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            await session.commit()

            draft = await WorkoutSessionRepository(session).start_draft_session(
                user.id, day=1, muscle_group="Груди"
            )
            await session.commit()

            assert draft.id is not None
            assert draft.completed_at is None
            assert draft.day == 1
            assert draft.muscle_group == "Груди"

    async def test_get_active_draft_finds_matching_day_and_muscle(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            started = await repo.start_draft_session(
                user.id, day=1, muscle_group="Груди"
            )
            await session.commit()

            found = await repo.get_active_draft(
                user.id, day=1, muscle_group="Груди"
            )
            assert found is not None
            assert found.id == started.id

    async def test_get_active_draft_does_not_match_other_day_or_muscle(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            await repo.start_draft_session(user.id, day=1, muscle_group="Груди")
            await session.commit()

            assert await repo.get_active_draft(user.id, day=2, muscle_group="Груди") is None
            assert await repo.get_active_draft(user.id, day=1, muscle_group="Спина") is None

    async def test_completed_draft_is_not_returned_as_active(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(user.id, day=1, muscle_group="Груди")
            await session.commit()

            await repo.complete_session(draft.id, user.id, duration_seconds=600)
            await session.commit()

            assert await repo.get_active_draft(user.id, day=1, muscle_group="Груди") is None

    async def test_none_day_and_muscle_match_none_not_other_values(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            await repo.start_draft_session(user.id, day=None, muscle_group=None)
            await session.commit()

            assert await repo.get_active_draft(user.id, day=None, muscle_group=None) is not None
            assert await repo.get_active_draft(user.id, day=1, muscle_group=None) is None

    async def test_stale_draft_beyond_max_age_is_ignored(self):
        from datetime import timedelta

        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(user.id, day=1, muscle_group="Груди")
            draft.performed_at = utcnow() - timedelta(hours=48)
            await session.commit()

            assert (
                await repo.get_active_draft(
                    user.id, day=1, muscle_group="Груди", max_age=timedelta(hours=24)
                )
                is None
            )


class TestCompleteSession:
    async def test_returns_none_for_unknown_session(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            await session.commit()

            result = await WorkoutSessionRepository(session).complete_session(
                999999, user.id
            )
            assert result is None

    async def test_returns_none_for_wrong_owner(self):
        async with async_session_maker() as session:
            owner = await _make_user(session)
            other = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(owner.id)
            await session.commit()

            result = await repo.complete_session(draft.id, other.id)
            assert result is None

    async def test_sets_completed_at_and_duration(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(user.id)
            await session.commit()

            completed = await repo.complete_session(
                draft.id, user.id, duration_seconds=1234
            )
            await session.commit()

            assert completed.completed_at is not None
            assert completed.duration_seconds == 1234

    async def test_calling_twice_does_not_move_completed_at_again(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(user.id)
            await session.commit()

            first = await repo.complete_session(draft.id, user.id, duration_seconds=100)
            await session.commit()
            first_completed_at = first.completed_at

            second = await repo.complete_session(draft.id, user.id, duration_seconds=200)
            await session.commit()

            assert second.completed_at == first_completed_at
            assert second.duration_seconds == 200


class TestReplaceExerciseSets:
    async def test_creates_sets_for_new_exercise(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            session_repo = WorkoutSessionRepository(session)
            draft = await session_repo.start_draft_session(user.id)
            await session.commit()

            await WorkoutSetRepository(session).replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Жим лежачи",
                muscle_group="Груди",
                planned_sets_reps="3x10",
                sets=[
                    {"set_number": 1, "weight": 60.0, "reps": 10},
                    {"set_number": 2, "weight": 62.5, "reps": 8},
                ],
            )
            await session.commit()

            rows = (await session.execute(
                WorkoutSet.__table__.select().where(WorkoutSet.session_id == draft.id)
            )).fetchall()
            assert len(rows) == 2
            assert {r.weight for r in rows} == {60.0, 62.5}

    async def test_replacing_with_fewer_sets_removes_the_extra_rows(self):
        """Mirrors the frontend renumbering a set after one is removed."""
        async with async_session_maker() as session:
            user = await _make_user(session)
            session_repo = WorkoutSessionRepository(session)
            draft = await session_repo.start_draft_session(user.id)
            set_repo = WorkoutSetRepository(session)
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Присідання",
                sets=[
                    {"set_number": 1, "weight": 100.0, "reps": 5},
                    {"set_number": 2, "weight": 100.0, "reps": 5},
                    {"set_number": 3, "weight": 100.0, "reps": 4},
                ],
            )
            await session.commit()

            # User removed the middle set; the frontend renumbers and resends.
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Присідання",
                sets=[
                    {"set_number": 1, "weight": 100.0, "reps": 5},
                    {"set_number": 2, "weight": 100.0, "reps": 4},
                ],
            )
            await session.commit()

            rows = (await session.execute(
                WorkoutSet.__table__.select().where(WorkoutSet.session_id == draft.id)
            )).fetchall()
            assert len(rows) == 2
            assert sorted(r.set_number for r in rows) == [1, 2]

    async def test_empty_sets_list_clears_the_exercise(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            session_repo = WorkoutSessionRepository(session)
            draft = await session_repo.start_draft_session(user.id)
            set_repo = WorkoutSetRepository(session)
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Тяга",
                sets=[{"set_number": 1, "weight": 80.0, "reps": 5}],
            )
            await session.commit()

            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Тяга",
                sets=[],
            )
            await session.commit()

            rows = (await session.execute(
                WorkoutSet.__table__.select().where(WorkoutSet.session_id == draft.id)
            )).fetchall()
            assert rows == []

    async def test_other_exercises_in_same_session_are_untouched(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            session_repo = WorkoutSessionRepository(session)
            draft = await session_repo.start_draft_session(user.id)
            set_repo = WorkoutSetRepository(session)
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Жим лежачи",
                sets=[{"set_number": 1, "weight": 60.0, "reps": 10}],
            )
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Присідання",
                sets=[{"set_number": 1, "weight": 100.0, "reps": 5}],
            )
            await session.commit()

            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Жим лежачи",
                sets=[{"set_number": 1, "weight": 65.0, "reps": 8}],
            )
            await session.commit()

            rows = (await session.execute(
                WorkoutSet.__table__.select().where(WorkoutSet.session_id == draft.id)
            )).fetchall()
            by_exercise = {r.exercise_name: r for r in rows}
            assert by_exercise["Жим лежачи"].weight == 65.0
            assert by_exercise["Присідання"].weight == 100.0


class TestCompletedFilterExcludesDrafts:
    async def test_get_sessions_by_period_excludes_drafts(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutSessionRepository(session)
            await repo.start_draft_session(user.id, day=1)
            completed = await repo.create_session_with_sets(
                user_id=user.id,
                performed_at=utcnow(),
                sets=[{"exercise_name": "Тяга", "set_number": 1, "weight": 80, "reps": 5}],
            )
            await session.commit()

            sessions = await repo.get_sessions_by_period(user.id)
            ids = [s.id for s in sessions]
            assert completed.id in ids
            assert len(ids) == 1

    async def test_get_sets_by_user_and_exercise_excludes_drafts(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            session_repo = WorkoutSessionRepository(session)
            set_repo = WorkoutSetRepository(session)

            draft = await session_repo.start_draft_session(user.id)
            await set_repo.replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Жим лежачи",
                sets=[{"set_number": 1, "weight": 999.0, "reps": 1}],
            )
            await session_repo.create_session_with_sets(
                user_id=user.id,
                performed_at=utcnow(),
                sets=[
                    {"exercise_name": "Жим лежачи", "set_number": 1, "weight": 60, "reps": 10}
                ],
            )
            await session.commit()

            sets = await set_repo.get_sets_by_user_and_exercise(user.id, "Жим лежачи")
            assert [s.weight for s in sets] == [60.0]
