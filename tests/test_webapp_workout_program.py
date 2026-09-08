"""Tests for GYM-28: `GET /api/workout/program`, `DELETE /api/workout/day`,
`DELETE /api/workout/exercise` (src/webapp/server.py) — DB is now the
primary store (GYM-27's `WorkoutProgramRepository`), Sheets an opt-in
mirror on delete, and `?user=` is gated by `_resolve_program_owner`
(covered exhaustively in its own test file; here just one 403/200 case
per endpoint to prove the wiring).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutProgramRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import (
    api_delete_exercise,
    api_delete_workout_day,
    api_get_workout_program,
    settings,
)
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


def _mock_request(method: str, path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(method, path, headers={"Authorization": init_data})


CHEST_ITEM = {
    "exercise": "Жим лежачи", "muscle_group": "🏋️ Груди", "sets_reps": "3/10",
}
LEGS_ITEM = {
    "exercise": "Присідання", "muscle_group": "🦵 Ноги", "sets_reps": "4/8",
}


class TestApiGetWorkoutProgram:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/workout/program", headers={"Authorization": "garbage"}
        )
        response = await api_get_workout_program(request)
        assert response.status == 401

    async def test_defaults_to_the_caller_own_program(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_exercises(user.id, 1, [CHEST_ITEM])

        request = _mock_request("GET", "/api/workout/program", telegram_id=1)
        response = await api_get_workout_program(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["exercises"] == [{
            "day": "1",
            "muscle_group": "🏋️ Груди",
            "exercise": "Жим лежачи",
            "sets_reps": "3/10",
            "comment": "",
            "created_at": payload["data"]["exercises"][0]["created_at"],
            # GYM-31: exercise_id/has_details back the "ⓘ" details icon.
            "exercise_id": payload["data"]["exercises"][0]["exercise_id"],
            "has_details": False,
        }]

    async def test_empty_program_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request("GET", "/api/workout/program", telegram_id=1)
        response = await api_get_workout_program(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["exercises"] == []

    async def test_filters_by_day_and_muscle(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_exercises(user.id, 1, [CHEST_ITEM])
        await _add_exercises(user.id, 2, [LEGS_ITEM])

        request = _mock_request(
            "GET", "/api/workout/program?day=2", telegram_id=1
        )
        payload = json.loads((await api_get_workout_program(request)).body)
        assert [e["exercise"] for e in payload["data"]["exercises"]] == ["Присідання"]

        request = _mock_request(
            "GET", "/api/workout/program?muscle=🏋️ Груди", telegram_id=1
        )
        payload = json.loads((await api_get_workout_program(request)).body)
        assert [e["exercise"] for e in payload["data"]["exercises"]] == ["Жим лежачи"]

    async def test_non_admin_requesting_another_user_gets_403(self):
        await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "GET", "/api/workout/program?user=lifter", telegram_id=999
        )
        response = await api_get_workout_program(request)
        assert response.status == 403

    async def test_admin_can_view_another_users_program(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_user_id", 999)
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_exercises(owner.id, 1, [CHEST_ITEM])

        request = _mock_request(
            "GET", "/api/workout/program?user=lifter", telegram_id=999
        )
        response = await api_get_workout_program(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert len(payload["data"]["exercises"]) == 1


class TestApiDeleteWorkoutDay:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "DELETE", "/api/workout/day?day=1", headers={"Authorization": "garbage"}
        )
        response = await api_delete_workout_day(request)
        assert response.status == 401

    async def test_missing_day_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request("DELETE", "/api/workout/day", telegram_id=1)
        response = await api_delete_workout_day(request)
        assert response.status == 400

    async def test_nonexistent_day_returns_404(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request("DELETE", "/api/workout/day?day=5", telegram_id=1)
        response = await api_delete_workout_day(request)
        assert response.status == 404

    async def test_deletes_the_day_from_the_db(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=False)
        await _add_exercises(user.id, 1, [CHEST_ITEM, LEGS_ITEM])

        request = _mock_request("DELETE", "/api/workout/day?day=1", telegram_id=1)
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            response = await api_delete_workout_day(request)
            mock_sheets_cls.assert_not_called()

        assert response.status == 200
        async with async_session_maker() as session:
            remaining = await WorkoutProgramRepository(session).get_program(user.id)
        assert remaining == []

    async def test_mirrors_to_sheets_when_sync_enabled(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=True)
        await _add_exercises(user.id, 1, [CHEST_ITEM])

        request = _mock_request("DELETE", "/api/workout/day?day=1", telegram_id=1)
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.delete_workout_day = AsyncMock(return_value=True)
            response = await api_delete_workout_day(request)
            instance.delete_workout_day.assert_awaited_once_with("lifter", "1")

        assert response.status == 200

    async def test_sheets_failure_does_not_fail_the_request(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=True)
        await _add_exercises(user.id, 1, [CHEST_ITEM])

        request = _mock_request("DELETE", "/api/workout/day?day=1", telegram_id=1)
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.delete_workout_day = AsyncMock(side_effect=RuntimeError("boom"))
            response = await api_delete_workout_day(request)

        assert response.status == 200

    async def test_non_admin_requesting_another_user_gets_403(self):
        await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "DELETE", "/api/workout/day?day=1&user=lifter", telegram_id=999
        )
        response = await api_delete_workout_day(request)
        assert response.status == 403


class TestApiDeleteExercise:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "DELETE", "/api/workout/exercise?day=1&exercise=X",
            headers={"Authorization": "garbage"},
        )
        response = await api_delete_exercise(request)
        assert response.status == 401

    async def test_missing_params_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "DELETE", "/api/workout/exercise?day=1", telegram_id=1
        )
        response = await api_delete_exercise(request)
        assert response.status == 400

    async def test_nonexistent_exercise_returns_404(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "DELETE", "/api/workout/exercise?day=1&exercise=Немає", telegram_id=1
        )
        response = await api_delete_exercise(request)
        assert response.status == 404

    async def test_deletes_only_the_matching_exercise(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=False)
        await _add_exercises(user.id, 1, [CHEST_ITEM, LEGS_ITEM])

        request = _mock_request(
            "DELETE",
            "/api/workout/exercise?day=1&exercise=" + "Жим лежачи",
            telegram_id=1,
        )
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            response = await api_delete_exercise(request)
            mock_sheets_cls.assert_not_called()

        assert response.status == 200
        async with async_session_maker() as session:
            remaining = await WorkoutProgramRepository(session).get_program(user.id)
        assert [r["exercise"] for r in remaining] == ["Присідання"]

    async def test_mirrors_to_sheets_when_sync_enabled(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=True)
        await _add_exercises(user.id, 1, [CHEST_ITEM])

        request = _mock_request(
            "DELETE", "/api/workout/exercise?day=1&exercise=Жим лежачи",
            telegram_id=1,
        )
        with patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.delete_exercise = AsyncMock(return_value=True)
            response = await api_delete_exercise(request)
            instance.delete_exercise.assert_awaited_once_with(
                "lifter", "1", "Жим лежачи"
            )

        assert response.status == 200

    async def test_non_admin_requesting_another_user_gets_403(self):
        await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "DELETE", "/api/workout/exercise?day=1&exercise=X&user=lifter",
            telegram_id=999,
        )
        response = await api_delete_exercise(request)
        assert response.status == 403
