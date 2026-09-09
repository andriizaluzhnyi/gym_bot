"""Tests for GYM-27: the Exercise catalog (ExerciseRepository,
normalize_exercise_name) and WorkoutProgramRepository
(src/database/repository.py, src/services/exercise_names.py).
"""

import re
import uuid

import pytest

from src.database.models import Base
from src.database.repository import (
    ExerciseRepository,
    UserRepository,
    WorkoutProgramRepository,
)
from src.database.session import async_session_maker, engine
from src.services.exercise_names import normalize_exercise_name


@pytest.fixture(autouse=True)
async def _create_tables():
    """Reset all tables before each test.

    GYM-41: this used to be ``create_all`` only (no ``drop_all``), unlike
    every other test file's fixture — harmless on a fresh DB, but the
    shared SQLite file at ``tests/conftest.py``'s path persists across
    separate ``pytest`` invocations, so a leftover ``exercises`` row from
    an earlier run (unique on ``normalized_name``) could make
    ``get_or_create_by_name`` return that stale row here instead of
    creating a fresh one — exactly what broke
    ``TestExerciseRepositoryGetOrCreateByName`` intermittently.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(session):
    user_repo = UserRepository(session)
    user, _ = await user_repo.get_or_create(
        telegram_id=uuid.uuid4().int % (2**31), first_name="Test",
    )
    await session.flush()
    return user


CHEST_ITEM = {
    "exercise": "Жим лежачи", "muscle_group": "🏋️ Груди", "sets_reps": "3/10",
}
LEGS_ITEM = {
    "exercise": "Присідання", "muscle_group": "🦵 Ноги", "sets_reps": "4/8",
    "comment": "з паузою",
}


class TestNormalizeExerciseName:
    def test_lowercases(self):
        assert normalize_exercise_name("ЖИМ ЛЕЖАЧИ") == "жим лежачи"

    def test_trims_and_collapses_whitespace(self):
        assert normalize_exercise_name("  Жим   лежачи  ") == "жим лежачи"

    def test_unifies_curly_and_straight_apostrophe(self):
        assert normalize_exercise_name("Тяга Т-грифа’") == normalize_exercise_name(
            "Тяга Т-грифа'"
        )

    def test_equivalent_inputs_produce_the_same_result(self):
        assert normalize_exercise_name("Жим лежачи") == normalize_exercise_name(
            "  жим   ЛЕЖАЧИ "
        )

    def test_different_names_stay_different(self):
        assert normalize_exercise_name("Жим лежачи") != normalize_exercise_name(
            "Присідання"
        )


class TestExerciseRepositoryGetOrCreateByName:
    async def test_creates_a_new_entry(self):
        async with async_session_maker() as session:
            exercise = await ExerciseRepository(session).get_or_create_by_name(
                "Жим лежачи", muscle_group="🏋️ Груди"
            )
            await session.commit()

            assert exercise.id is not None
            assert exercise.name == "Жим лежачи"
            assert exercise.normalized_name == "жим лежачи"
            assert exercise.muscle_group == "🏋️ Груди"

    async def test_returns_the_same_entry_for_an_equivalent_name(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            first = await repo.get_or_create_by_name(
                "Жим лежачи", muscle_group="🏋️ Груди"
            )
            second = await repo.get_or_create_by_name("  жим   ЛЕЖАЧИ ")
            await session.commit()

            assert second.id == first.id

    async def test_does_not_overwrite_muscle_group_on_existing_entry(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            first = await repo.get_or_create_by_name(
                "Жим лежачи", muscle_group="🏋️ Груди"
            )
            again = await repo.get_or_create_by_name(
                "Жим лежачи", muscle_group="🦵 Ноги"
            )
            await session.commit()

            assert again.id == first.id
            assert again.muscle_group == "🏋️ Груди"


class TestExerciseRepositorySearch:
    async def test_matches_contains_normalized(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            await repo.get_or_create_by_name("Жим лежачи")
            await session.commit()

            results = await repo.search("жим")
            assert [e.name for e in results] == ["Жим лежачи"]

    async def test_no_match_returns_empty_list(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            await repo.get_or_create_by_name("Жим лежачи")
            await session.commit()

            assert await repo.search("присідання") == []

    async def test_blank_query_returns_recent_entries_instead_of_empty(self):
        """GYM-41: an empty q backs the "pick from what's already there"
        list shown on focus, not a "type to search" empty state.
        """
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            await repo.get_or_create_by_name("Жим лежачи")
            await repo.get_or_create_by_name("Присідання")
            await session.commit()

            results = await repo.search("")
            assert {e.name for e in results} == {"Жим лежачи", "Присідання"}

    async def test_blank_query_orders_most_recently_added_first(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            await repo.get_or_create_by_name("Жим лежачи")
            await repo.get_or_create_by_name("Присідання")
            await session.commit()

            results = await repo.search("")
            assert [e.name for e in results] == ["Присідання", "Жим лежачи"]

    async def test_blank_query_respects_limit(self):
        async with async_session_maker() as session:
            repo = ExerciseRepository(session)
            for name in ["A", "B", "C"]:
                await repo.get_or_create_by_name(name)
            await session.commit()

            results = await repo.search("", limit=2)
            assert len(results) == 2

    async def test_blank_query_with_empty_catalog_returns_empty_list(self):
        async with async_session_maker() as session:
            assert await ExerciseRepository(session).search("") == []


class TestAddExercises:
    async def test_creates_rows_linked_to_the_catalog(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            rows = await WorkoutProgramRepository(session).add_exercises(
                user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM]
            )
            await session.commit()

            assert len(rows) == 2
            assert rows[0].exercise_name == "Жим лежачи"
            assert rows[0].exercise_id is not None
            assert rows[1].comment == "з паузою"

    async def test_positions_are_sequential_from_zero(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            rows = await WorkoutProgramRepository(session).add_exercises(
                user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM]
            )
            await session.commit()
            assert [r.position for r in rows] == [0, 1]

    async def test_appending_continues_the_position_sequence(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            more = await repo.add_exercises(user.id, day=1, items=[LEGS_ITEM])
            await session.commit()

            assert [r.position for r in more] == [1]

    async def test_reuses_catalog_entry_for_the_same_exercise_name(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            first = await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            second = await repo.add_exercises(user.id, day=2, items=[CHEST_ITEM])
            await session.commit()

            assert first[0].exercise_id == second[0].exercise_id


class TestGetProgram:
    async def test_returns_sheets_compatible_shape(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            await WorkoutProgramRepository(session).add_exercises(
                user.id, day=1, items=[CHEST_ITEM]
            )
            await session.commit()

            program = await WorkoutProgramRepository(session).get_program(user.id)

            assert len(program) == 1
            row = program[0]
            assert row["day"] == "1"
            assert row["muscle_group"] == "🏋️ Груди"
            assert row["exercise"] == "Жим лежачи"
            assert row["sets_reps"] == "3/10"
            assert row["comment"] == ""
            # GYM-31/GYM-44: exercise_id/has_details/id are additive — same
            # Sheets-compatible core keys, plus these for the details icon
            # and (id) precise addressing of this row.
            assert set(row.keys()) == {
                "id", "day", "muscle_group", "exercise", "sets_reps",
                "comment", "created_at", "exercise_id", "has_details",
            }
            assert row["has_details"] is False
            assert isinstance(row["id"], int)

    async def test_has_details_true_when_catalog_entry_has_any_media_field(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            rows = await WorkoutProgramRepository(session).add_exercises(
                user.id, day=1, items=[CHEST_ITEM]
            )
            exercise = await ExerciseRepository(session).get_by_id(
                rows[0].exercise_id
            )
            exercise.description = "Лягти на лаву, опустити штангу до грудей."
            await session.commit()

            program = await WorkoutProgramRepository(session).get_program(user.id)
            assert program[0]["has_details"] is True

    async def test_created_at_is_formatted_like_a_sheets_cell(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            await WorkoutProgramRepository(session).add_exercises(
                user.id, day=1, items=[CHEST_ITEM]
            )
            await session.commit()

            program = await WorkoutProgramRepository(session).get_program(user.id)
            assert re.match(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$", program[0]["created_at"])

    async def test_filters_by_day(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            await repo.add_exercises(user.id, day=2, items=[LEGS_ITEM])
            await session.commit()

            program = await repo.get_program(user.id, day=2)
            assert len(program) == 1
            assert program[0]["exercise"] == "Присідання"

    async def test_filters_by_muscle(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM])
            await session.commit()

            program = await repo.get_program(user.id, muscle="🦵 Ноги")
            assert len(program) == 1
            assert program[0]["exercise"] == "Присідання"

    async def test_ordered_by_day_then_position(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=2, items=[LEGS_ITEM])
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            await session.commit()

            program = await repo.get_program(user.id)
            assert [p["day"] for p in program] == ["1", "2"]

    async def test_does_not_see_another_users_program(self):
        async with async_session_maker() as session:
            owner = await _make_user(session)
            other = await _make_user(session)
            await WorkoutProgramRepository(session).add_exercises(
                owner.id, day=1, items=[CHEST_ITEM]
            )
            await session.commit()

            program = await WorkoutProgramRepository(session).get_program(other.id)
            assert program == []


class TestDeleteDay:
    async def test_deletes_every_exercise_in_the_day(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM])
            await session.commit()

            deleted = await repo.delete_day(user.id, 1)
            await session.commit()

            assert deleted is True
            assert await repo.get_program(user.id, day=1) == []

    async def test_returns_false_when_day_is_already_empty(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            deleted = await WorkoutProgramRepository(session).delete_day(user.id, 5)
            assert deleted is False

    async def test_leaves_other_days_untouched(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            await repo.add_exercises(user.id, day=2, items=[LEGS_ITEM])
            await session.commit()

            await repo.delete_day(user.id, 1)
            await session.commit()

            remaining = await repo.get_program(user.id)
            assert len(remaining) == 1
            assert remaining[0]["day"] == "2"

    async def test_muscle_scoped_delete_leaves_other_groups_in_the_same_day(self):
        """GYM-41: a day can span several muscle groups (GYM-30) — a
        muscle-scoped delete must only remove that group's rows.
        """
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM])
            await session.commit()

            deleted = await repo.delete_day(user.id, 1, muscle=CHEST_ITEM["muscle_group"])
            await session.commit()

            assert deleted is True
            remaining = await repo.get_program(user.id, day=1)
            assert [r["exercise"] for r in remaining] == [LEGS_ITEM["exercise"]]

    async def test_muscle_scoped_delete_returns_false_when_that_group_is_empty(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            await session.commit()

            deleted = await repo.delete_day(user.id, 1, muscle=LEGS_ITEM["muscle_group"])

            assert deleted is False
            remaining = await repo.get_program(user.id, day=1)
            assert len(remaining) == 1  # the chest exercise is untouched

    async def test_no_muscle_param_still_deletes_the_whole_day(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM])
            await session.commit()

            deleted = await repo.delete_day(user.id, 1)
            await session.commit()

            assert deleted is True
            assert await repo.get_program(user.id, day=1) == []


class TestDeleteExercise:
    async def test_deletes_the_matching_exercise(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM, LEGS_ITEM])
            await session.commit()

            deleted = await repo.delete_exercise(user.id, 1, "Жим лежачи")
            await session.commit()

            assert deleted is True
            remaining = await repo.get_program(user.id, day=1)
            assert [r["exercise"] for r in remaining] == ["Присідання"]

    async def test_returns_false_when_nothing_matches(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            deleted = await WorkoutProgramRepository(session).delete_exercise(
                user.id, 1, "Немає такої"
            )
            assert deleted is False


class TestGetLastDayForMuscle:
    async def test_returns_zero_when_none_exist(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            last_day = await WorkoutProgramRepository(session).get_last_day_for_muscle(
                user.id, "🏋️ Груди"
            )
            assert last_day == 0

    async def test_returns_the_highest_day_for_that_muscle(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(user.id, day=1, items=[CHEST_ITEM])
            await repo.add_exercises(user.id, day=3, items=[CHEST_ITEM])
            await repo.add_exercises(user.id, day=2, items=[LEGS_ITEM])
            await session.commit()

            last_day = await repo.get_last_day_for_muscle(user.id, "🏋️ Груди")
            assert last_day == 3


class TestGetDaysSummary:
    async def test_groups_by_day_with_muscle_groups_and_counts(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            repo = WorkoutProgramRepository(session)
            await repo.add_exercises(
                user.id, day=1,
                items=[
                    CHEST_ITEM, LEGS_ITEM,
                    {**CHEST_ITEM, "exercise": "Розведення гантелей"},
                ],
            )
            await repo.add_exercises(user.id, day=2, items=[LEGS_ITEM])
            await session.commit()

            summary = await repo.get_days_summary(user.id)

            assert summary == [
                {"day": 1, "muscle_groups": ["🏋️ Груди", "🦵 Ноги"], "exercises_count": 3},
                {"day": 2, "muscle_groups": ["🦵 Ноги"], "exercises_count": 1},
            ]

    async def test_empty_when_no_program(self):
        async with async_session_maker() as session:
            user = await _make_user(session)
            summary = await WorkoutProgramRepository(session).get_days_summary(user.id)
            assert summary == []
