"""Tests for GYM-4: GET /api/statistics/volume (src/webapp/server.py)."""

import json
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_volume_statistics
from tests.test_webapp_auth import build_init_data

import pytest

# settings.timezone defaults to Europe/Kyiv (src/config.py); winter offset
# is UTC+2, so local midnight boundaries land at 22:00 the previous UTC day.


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


class TestAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/volume", headers={"Authorization": "garbage"}
        )
        response = await api_get_volume_statistics(request)
        assert response.status == 401

    async def test_invalid_period_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/volume?period=year", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        assert response.status == 400

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/volume", telegram_id=999)
        response = await api_get_volume_statistics(request)
        assert response.status == 404

    async def test_unknown_user_param_returns_404(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/volume?user=ghost", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        assert response.status == 404


class TestEmptyPeriod:
    async def test_no_sessions_returns_zeroed_empty_response(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/volume?period=all", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {
            "success": True,
            "data": {"by_day": [], "by_muscle": [], "total_volume": 0.0},
        }


class TestAggregation:
    async def test_aggregates_by_day_and_muscle(self):
        user = await _make_user("lifter", telegram_id=1)
        # Two sets, same day, different muscle groups.
        await _add_completed_session(
            user.id,
            datetime(2026, 1, 7, 8, 0),  # 10:00 Kyiv, Jan 7
            sets=[
                {
                    "exercise_name": "Жим лежачи",
                    "muscle_group": "Груди",
                    "set_number": 1,
                    "weight": 60.0,
                    "reps": 10,
                },
                {
                    "exercise_name": "Присідання",
                    "muscle_group": "Ноги",
                    "set_number": 1,
                    "weight": 100.0,
                    "reps": 5,
                },
            ],
        )

        request = _mock_get_request(
            "/api/statistics/volume?period=all", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert payload["total_volume"] == 1100.0  # 60*10 + 100*5
        assert payload["by_day"] == [{"date": "2026-01-07", "volume": 1100.0}]
        by_muscle = {b["muscle_group"]: b for b in payload["by_muscle"]}
        assert by_muscle["Груди"] == {
            "muscle_group": "Груди", "volume": 600.0, "sets_count": 1,
        }
        assert by_muscle["Ноги"] == {
            "muscle_group": "Ноги", "volume": 500.0, "sets_count": 1,
        }

    async def test_muscle_filter_narrows_both_by_day_and_by_muscle(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id,
            datetime(2026, 1, 7, 8, 0),
            sets=[
                {
                    "exercise_name": "Жим лежачи",
                    "muscle_group": "Груди",
                    "set_number": 1,
                    "weight": 60.0,
                    "reps": 10,
                },
                {
                    "exercise_name": "Присідання",
                    "muscle_group": "Ноги",
                    "set_number": 1,
                    "weight": 100.0,
                    "reps": 5,
                },
            ],
        )

        request = _mock_get_request(
            "/api/statistics/volume?period=all&muscle=Ноги", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)["data"]

        assert payload["total_volume"] == 500.0
        assert payload["by_day"] == [{"date": "2026-01-07", "volume": 500.0}]
        assert payload["by_muscle"] == [
            {"muscle_group": "Ноги", "volume": 500.0, "sets_count": 1}
        ]

    async def test_draft_session_is_excluded(self):
        """An in-progress session (no completed_at) must not count."""
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request(
            "/api/statistics/volume?period=all", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)["data"]

        assert payload == {"by_day": [], "by_muscle": [], "total_volume": 0.0}

    async def test_session_outside_period_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        # Well outside "this week" no matter when the test runs.
        await _add_completed_session(
            user.id,
            datetime(2020, 1, 1, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи",
                "muscle_group": "Груди",
                "set_number": 1,
                "weight": 60.0,
                "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/volume?period=week", telegram_id=1
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)["data"]

        assert payload["total_volume"] == 0.0


class TestTrainerViewsClient:
    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id,
            datetime(2026, 1, 7, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи",
                "muscle_group": "Груди",
                "set_number": 1,
                "weight": 60.0,
                "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/volume?period=all&user=lifter", telegram_id=999
        )
        response = await api_get_volume_statistics(request)
        payload = json.loads(response.body)["data"]

        assert payload["total_volume"] == 600.0
