"""Tests for GYM-30: `POST /api/workout/program/exercise` and
`GET /api/exercises` (src/webapp/server.py) — adding one exercise to a
program day from the Mini App, and the catalog-autocomplete search behind
its exercise-name field.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import ExerciseRepository, UserRepository, WorkoutProgramRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_add_program_exercise, api_search_exercises, settings
from tests.test_webapp_auth import build_init_data


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(username: str, telegram_id: int, *, sync_enabled: bool = False):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        user.sync_workout_to_sheets = sync_enabled
        await session.commit()
        return user


async def _add_exercises(user_id, day: int, items: list[dict]):
    async with async_session_maker() as session:
        rows = await WorkoutProgramRepository(session).add_exercises(user_id, day, items)
        await session.commit()
        return rows


async def _add_catalog_exercise(name: str, muscle_group: str | None = None):
    async with async_session_maker() as session:
        exercise = await ExerciseRepository(session).get_or_create_by_name(
            name, muscle_group=muscle_group
        )
        await session.commit()
        return exercise


def _mock_request(
    method: str, path: str, *, telegram_id: int, body: dict | None = None
) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(method, path, headers={"Authorization": init_data})
    if body is not None:
        async def fake_json():
            return body
        request.json = fake_json  # type: ignore[method-assign, assignment]
    return request


VALID_BODY = {
    "day": 1,
    "muscle_group": "🏋️ Груди",
    "exercise": "Жим лежачи",
    "sets_reps": "3/10",
    "comment": "повільно",
}


class TestApiAddProgramExerciseAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "POST", "/api/workout/program/exercise",
            headers={"Authorization": "garbage"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 401

    async def test_invalid_json_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1
        )

        async def bad_json():
            raise json.JSONDecodeError("bad", "", 0)
        request.json = bad_json  # type: ignore[method-assign, assignment]

        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_missing_day_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        body = {**VALID_BODY}
        del body["day"]
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=body
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_non_int_day_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "day": "one"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_zero_day_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "day": 0},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_muscle_group_outside_allowed_list_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "muscle_group": "Не існує"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_missing_exercise_name_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "exercise": "  "},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_invalid_sets_reps_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "sets_reps": "до відмови"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_bare_number_sets_reps_is_accepted(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "sets_reps": "5"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 200

    async def test_bare_number_mixed_with_a_combined_block_returns_400(self):
        # GYM-46: a bare number is only meaningful as the sole block —
        # "3, 4/6" isn't "3 sets (reps unknown), then 4/6".
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "sets_reps": "3, 4/6"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 400

    async def test_sets_reps_too_long_returns_400_with_length_message(self):
        # GYM-46: normalizes to 68 chars, over the 50-char column limit —
        # a distinct message from the generic "invalid format" one.
        await _make_user("lifter", telegram_id=1)
        too_long = ", ".join(["11/11"] * 10)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "sets_reps": too_long},
        )
        response = await api_add_program_exercise(request)
        payload = json.loads(response.body)

        assert response.status == 400
        assert "too long" in payload["error"]

    async def test_non_admin_requesting_another_user_gets_403(self):
        await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=999,
            body={**VALID_BODY, "user": "lifter"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 403


class TestApiAddProgramExercise:
    async def test_adds_exercise_and_returns_row_shape(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        response = await api_add_program_exercise(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"] == {
            "day": "1",
            "muscle_group": "🏋️ Груди",
            "exercise": "Жим лежачи",
            "sets_reps": "3/10",
            "comment": "повільно",
            "created_at": payload["data"]["created_at"],
            # GYM-31: exercise_id/has_details, same shape GET
            # /api/workout/program returns.
            "exercise_id": payload["data"]["exercise_id"],
            "has_details": False,
        }

    async def test_untidy_multi_block_sets_reps_is_stored_normalized(self):
        # GYM-46: "2/12,4x6" (no spaces, "x" separator) is stored as the
        # canonical "2/12, 4/6".
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "sets_reps": "2/12,4x6"},
        )
        response = await api_add_program_exercise(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["sets_reps"] == "2/12, 4/6"

    async def test_appends_after_existing_exercises_in_the_day(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_exercises(user.id, 1, [
            {"exercise": "Присідання", "muscle_group": "🦵 Ноги", "sets_reps": "4/8"},
        ])

        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        await api_add_program_exercise(request)

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(user.id, day=1)
        assert [p["exercise"] for p in program] == ["Присідання", "Жим лежачи"]

    async def test_reuses_existing_catalog_entry_instead_of_duplicating(self):
        await _make_user("lifter", telegram_id=1)
        existing = await _add_catalog_exercise("Жим лежачи", muscle_group="🏋️ Груди")

        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1,
            body={**VALID_BODY, "exercise": "жим лежачи"},  # different case
        )
        await api_add_program_exercise(request)

        async with async_session_maker() as session:
            all_exercises = await ExerciseRepository(session).search("жим", limit=10)
        assert len(all_exercises) == 1
        assert all_exercises[0].id == existing.id

    async def test_has_details_true_when_catalog_entry_already_has_media(self):
        await _make_user("lifter", telegram_id=1)
        existing = await _add_catalog_exercise("Жим лежачи", muscle_group="🏋️ Груди")
        async with async_session_maker() as session:
            exercise = await ExerciseRepository(session).get_by_id(existing.id)
            exercise.description = "Опис"
            await session.commit()

        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        response = await api_add_program_exercise(request)
        payload = json.loads(response.body)

        assert payload["data"]["exercise_id"] == existing.id
        assert payload["data"]["has_details"] is True

    async def test_optional_comment_defaults_to_empty_string(self):
        await _make_user("lifter", telegram_id=1)
        body = {**VALID_BODY}
        del body["comment"]
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=body
        )
        response = await api_add_program_exercise(request)
        payload = json.loads(response.body)
        assert payload["data"]["comment"] == ""

    async def test_admin_can_add_to_another_users_program(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_user_id", 999)
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=999,
            body={**VALID_BODY, "user": "lifter"},
        )
        response = await api_add_program_exercise(request)
        assert response.status == 200

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(owner.id)
        assert len(program) == 1

    async def test_mirrors_to_sheets_when_sync_enabled(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.add_workout_program = AsyncMock(return_value=True)
            response = await api_add_program_exercise(request)
            instance.add_workout_program.assert_awaited_once()
            call_args = instance.add_workout_program.await_args
            assert call_args.args[0] == [{
                "exercise": "Жим лежачи",
                "muscle_group": "🏋️ Груди",
                "sets_reps": "3/10",
                "comment": "повільно",
                "day": 1,
            }]
            assert call_args.kwargs == {"user_name": "lifter"}

        assert response.status == 200

    async def test_does_not_mirror_when_sync_disabled(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=False)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            await api_add_program_exercise(request)
            mock_sheets_cls.assert_not_called()

    async def test_sheets_failure_does_not_fail_the_request(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        request = _mock_request(
            "POST", "/api/workout/program/exercise", telegram_id=1, body=VALID_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.add_workout_program = AsyncMock(side_effect=RuntimeError("boom"))
            response = await api_add_program_exercise(request)

        assert response.status == 200


class TestApiSearchExercises:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/exercises?q=жим", headers={"Authorization": "garbage"}
        )
        response = await api_search_exercises(request)
        assert response.status == 401

    async def test_blank_query_with_empty_catalog_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request("GET", "/api/exercises", telegram_id=1)
        response = await api_search_exercises(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": []}

    async def test_blank_query_lists_existing_catalog_entries(self):
        """GYM-41: the "add exercise" name field shows a pick-list on
        focus, before the user types anything — GET /api/exercises with
        no `q` must return something to pick from, not an empty list.
        """
        await _make_user("lifter", telegram_id=1)
        await _add_catalog_exercise("Жим лежачи", muscle_group="🏋️ Груди")
        await _add_catalog_exercise("Присідання", muscle_group="🦵 Ноги")

        request = _mock_request("GET", "/api/exercises", telegram_id=1)
        response = await api_search_exercises(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert {row["name"] for row in payload} == {"Жим лежачи", "Присідання"}

    async def test_blank_query_with_no_q_param_at_all_also_lists_entries(self):
        await _make_user("lifter", telegram_id=1)
        await _add_catalog_exercise("Тяга")

        request = _mock_request("GET", "/api/exercises?q=", telegram_id=1)
        response = await api_search_exercises(request)
        payload = json.loads(response.body)["data"]

        assert len(payload) == 1

    async def test_matches_case_and_whitespace_insensitively(self):
        await _make_user("lifter", telegram_id=1)
        await _add_catalog_exercise("Жим лежачи", muscle_group="🏋️ Груди")

        request = _mock_request(
            "GET", "/api/exercises?q=" + "жим  лёжа".replace("ё", "е"), telegram_id=1
        )
        response = await api_search_exercises(request)
        payload = json.loads(response.body)["data"]

        assert len(payload) == 1
        assert payload[0]["name"] == "Жим лежачи"
        assert payload[0]["muscle_group"] == "🏋️ Груди"
        assert "id" in payload[0]

    async def test_no_match_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        await _add_catalog_exercise("Жим лежачи")

        request = _mock_request(
            "GET", "/api/exercises?q=присідання", telegram_id=1
        )
        response = await api_search_exercises(request)
        payload = json.loads(response.body)["data"]

        assert payload == []
