"""Tests for GYM-5a: GET /api/statistics/exercises and
GET /api/statistics/exercise-progress (src/webapp/server.py).
"""

import json
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_exercise_progress, api_get_exercises
from tests.test_webapp_auth import build_init_data

import pytest

# settings.timezone defaults to Europe/Kyiv (src/config.py).


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(username: str, telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        await session.commit()
        return user


async def _add_completed_session(
    user_id, performed_at: datetime, sets: list[dict], **kwargs
):
    async with async_session_maker() as session:
        await WorkoutSessionRepository(session).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=sets, **kwargs
        )
        await session.commit()


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )


class TestApiGetExercises:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/exercises", headers={"Authorization": "garbage"}
        )
        response = await api_get_exercises(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/exercises", telegram_id=999)
        response = await api_get_exercises(request)
        assert response.status == 404

    async def test_no_sessions_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request("/api/statistics/exercises", telegram_id=1)
        response = await api_get_exercises(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": []}

    async def test_lists_unique_exercises_sorted_by_muscle_then_name(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[
                {
                    "exercise_name": "Присідання", "muscle_group": "Ноги",
                    "set_number": 1, "weight": 100.0, "reps": 5,
                },
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 1, "weight": 60.0, "reps": 10,
                },
            ],
        )
        # Same exercise again in a later session -> still one entry.
        await _add_completed_session(
            user.id, datetime(2026, 1, 8, 8, 0),
            sets=[{
                "exercise_name": "Присідання", "muscle_group": "Ноги",
                "set_number": 1, "weight": 105.0, "reps": 5,
            }],
        )

        request = _mock_get_request("/api/statistics/exercises", telegram_id=1)
        response = await api_get_exercises(request)
        payload = json.loads(response.body)["data"]

        assert payload == [
            {"exercise_name": "Жим лежачи", "muscle_group": "Груди"},
            {"exercise_name": "Присідання", "muscle_group": "Ноги"},
        ]

    async def test_muscle_group_uses_most_recent_value(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 1, 8, 0),
            sets=[{
                "exercise_name": "Тяга блоку", "muscle_group": "Спина",
                "set_number": 1, "weight": 50.0, "reps": 10,
            }],
        )
        # Program edit reclassified the exercise's muscle group later on.
        await _add_completed_session(
            user.id, datetime(2026, 1, 8, 8, 0),
            sets=[{
                "exercise_name": "Тяга блоку", "muscle_group": "Руки",
                "set_number": 1, "weight": 52.0, "reps": 10,
            }],
        )

        request = _mock_get_request("/api/statistics/exercises", telegram_id=1)
        response = await api_get_exercises(request)
        payload = json.loads(response.body)["data"]

        assert payload == [{"exercise_name": "Тяга блоку", "muscle_group": "Руки"}]

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request("/api/statistics/exercises", telegram_id=1)
        response = await api_get_exercises(request)
        payload = json.loads(response.body)["data"]

        assert payload == []

    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/exercises?user=lifter", telegram_id=999
        )
        response = await api_get_exercises(request)
        payload = json.loads(response.body)["data"]

        assert payload == [{"exercise_name": "Жим лежачи", "muscle_group": "Груди"}]


class TestApiGetExerciseProgress:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET",
            "/api/statistics/exercise-progress?exercise=Жим",
            headers={"Authorization": "garbage"},
        )
        response = await api_get_exercise_progress(request)
        assert response.status == 401

    async def test_missing_exercise_param_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/exercise-progress", telegram_id=1
        )
        response = await api_get_exercise_progress(request)
        assert response.status == 400

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request(
            "/api/statistics/exercise-progress?exercise=Жим", telegram_id=999
        )
        response = await api_get_exercise_progress(request)
        assert response.status == 404

    async def test_never_logged_exercise_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/exercise-progress?exercise=Жим", telegram_id=1
        )
        response = await api_get_exercise_progress(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": []}

    async def test_aggregates_per_session_oldest_first(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 8, 8, 0),  # later session first...
            sets=[
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 1, "weight": 65.0, "reps": 8,
                },
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 2, "weight": 70.0, "reps": 5,
                },
            ],
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 1, 8, 0),  # ...but this one is earlier.
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/exercise-progress?exercise=Жим лежачи", telegram_id=1
        )
        response = await api_get_exercise_progress(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert len(payload) == 2
        # Oldest first.
        assert payload[0]["date"] == "2026-01-01"
        assert payload[0]["max_weight"] == 60.0
        assert payload[0]["total_reps"] == 10
        assert payload[0]["total_volume"] == 600.0
        assert payload[0]["top_set"] == {"weight": 60.0, "reps": 10}

        assert payload[1]["date"] == "2026-01-08"
        assert payload[1]["max_weight"] == 70.0
        assert payload[1]["total_reps"] == 13
        assert payload[1]["total_volume"] == 65.0 * 8 + 70.0 * 5
        assert payload[1]["top_set"] == {"weight": 70.0, "reps": 5}

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            draft = await WorkoutSessionRepository(session).start_draft_session(
                user.id
            )
            from src.database.repository import WorkoutSetRepository
            await WorkoutSetRepository(session).replace_exercise_sets(
                session_id=draft.id,
                user_id=user.id,
                exercise_name="Жим лежачи",
                muscle_group="Груди",
                sets=[{"set_number": 1, "weight": 60.0, "reps": 10}],
                performed_at=draft.performed_at,
            )
            await session.commit()

        request = _mock_get_request(
            "/api/statistics/exercise-progress?exercise=Жим лежачи", telegram_id=1
        )
        response = await api_get_exercise_progress(request)
        payload = json.loads(response.body)["data"]

        assert payload == []

    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/exercise-progress?exercise=Жим лежачи&user=lifter",
            telegram_id=999,
        )
        response = await api_get_exercise_progress(request)
        payload = json.loads(response.body)["data"]

        assert len(payload) == 1
